"""Main screening pipeline with explicit input gates and quarantine outputs."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import geopandas as gpd
import pandas as pd

from .config import load_project_config
from .demo_data import build_demo_layers
from .grid_distance import compare_top_n
from .load import read_layer
from .siting import SitingConfig, evaluate_sites


def _write_deterministic_gpkg(frame: gpd.GeoDataFrame, path: Path, layer: str) -> None:
    """Write a fresh GeoPackage and remove creation-time-only differences.

    ``with sqlite3.connect(...)`` commits the transaction; it does not close the
    connection. The open handle kept a lock on the file, so a caller that wrote
    its outputs and then cleaned the directory up - which is what every run of
    scripts/reproduce.py does on its second pass - failed on Windows with a
    file-in-use error from code that had finished its work.
    """
    path.unlink(missing_ok=True)
    frame.to_file(path, layer=layer, driver="GPKG")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE gpkg_contents SET last_change = '2000-01-01T00:00:00.000Z'"
        )
        connection.commit()
        connection.execute("VACUUM")


def run_screening(
    sites: gpd.GeoDataFrame,
    conservation: gpd.GeoDataFrame,
    powerlines: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    output_dir: str | Path,
    config: SitingConfig | None = None,
    top_n_comparison: int = 10,
    scope: str = "screening results",
    terrain: pd.DataFrame | None = None,
    water: gpd.GeoDataFrame | None = None,
    coastline: gpd.GeoDataFrame | None = None,
    conservation_parcels: pd.DataFrame | None = None,
) -> dict[str, object]:
    results, audit = evaluate_sites(
        sites, conservation, powerlines, roads, config,
        terrain=terrain, water=water, coastline=coastline,
        conservation_parcels=conservation_parcels,
    )
    reject_rate = float((results["status"] == "quarantine").mean())
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    candidates = results[results["status"] == "candidate_review"].copy()
    quarantine = results[results["status"] == "quarantine"].copy()
    _write_deterministic_gpkg(candidates, output / "candidates.gpkg", "candidates")
    _write_deterministic_gpkg(quarantine, output / "quarantine.gpkg", "quarantine")
    audit.to_csv(output / "rule_results.csv", index=False)
    comparison = compare_top_n(candidates, top_n_comparison)
    summary = {
        "scope": scope,
        "crs": "EPSG:2193",
        "total": len(results),
        "candidates": len(candidates),
        "quarantine": len(quarantine),
        "reject_rate": round(reject_rate, 4),
        "selection_rate": round(1.0 - reject_rate, 4),
        "width_method_disagreements": int(results["width_methods_disagree"].sum()),
        "rules_not_applied": [
            rule for rule in str(results["rules_not_applied"].iloc[0]).split(";") if rule
        ] if len(results) else [],
        "slope_unknown": int(results["S08_verify_slope"].sum()),
        "hpl_flagged": int(results["S05_hpl_flag"].sum()),
        "s05_basis": sorted(set(results["s05_basis"])) if len(results) else [],
        "s04_reconciliation": results.attrs.get("s04_reconciliation", {}),
        "coastal_review_flagged": int(results["S10_coastal_flag"].sum()),
        "grid_comparison": comparison,
    }
    (output / "run_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="Run deterministic NZTM demonstration")
    mode.add_argument("--sites", help="Preprocessed polygon layer with required site attributes")
    parser.add_argument("--conservation", help="Conservation polygon layer")
    parser.add_argument("--powerlines", help="Powerline layer")
    parser.add_argument("--roads", help="Road proxy layer")
    parser.add_argument(
        "--terrain",
        help="CSV with site_id and mean_slope_deg, from scripts/compute_site_terrain.py. "
             "Without it S-08 is not applied and every site is flagged slope-unknown.",
    )
    parser.add_argument(
        "--conservation-parcels",
        help="CSV of the LINZ Protected Area / Parcel association (table 3561) with "
             "napalis_id and parcel_id. With it S-04 is an identity test on parcel_id and "
             "geometry is used only for protected areas the table does not cover.",
    )
    parser.add_argument("--water", help="Mapped water and wetland polygons for S-09")
    parser.add_argument("--coastline", help="Coastline for the S-10 proximity flag")
    parser.add_argument("--config", default="config/assumptions.yml")
    parser.add_argument("--output", help="Output directory (defaults to outputs/demo or outputs/real)")
    args = parser.parse_args()
    project = load_project_config(args.config)
    if args.demo:
        layers = build_demo_layers()
        scope = "screening only; demo geometries are not real parcels"
        top_n = project.demo_top_n_comparison
        output = args.output or "outputs/demo"
    else:
        missing = [name for name in ("conservation", "powerlines", "roads") if not getattr(args, name)]
        if missing:
            parser.error("--sites requires --conservation, --powerlines and --roads")
        layers = (
            read_layer(args.sites, ("site_id", "lcdb_class", "luc_class", "solar_kwh_m2"), "sites"),
            read_layer(args.conservation, name="conservation"),
            read_layer(args.powerlines, name="powerlines"),
            read_layer(args.roads, name="roads"),
        )
        scope = "screening only; user-supplied preprocessed spatial layers"
        top_n = project.top_n_comparison
        output = args.output or "outputs/real"
    result = run_screening(
        *layers, output, config=project.siting,
        top_n_comparison=top_n, scope=scope,
        terrain=pd.read_csv(args.terrain) if args.terrain else None,
        water=read_layer(args.water, name="water") if args.water else None,
        coastline=read_layer(args.coastline, name="coastline") if args.coastline else None,
        conservation_parcels=(
            pd.read_csv(args.conservation_parcels) if args.conservation_parcels else None
        ),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
