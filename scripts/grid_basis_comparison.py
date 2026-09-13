"""Compare the network layers a screen could call "the grid", side by side.

The question S-06 has always been about is which line layer a distance rule
should measure to. Three public answers exist for Canterbury and they disagree:

* **LINZ Topo50 powerline centrelines** — the layer the original method named.
  CC BY, and carries no voltage attribute at all, so every circuit from an 11 kV
  spur to a 220 kV transmission line is one undifferentiated population.
* **OpenStreetMap**, tagged with voltage, which is what made the connection-tier
  analysis possible in the first place.
* **Transpower's own transmission lines**, CC BY and authoritative for the
  national grid, covering 110 kV and above and nothing below it.

They are reported beside each other, never merged. Merging would destroy the one
column that says which question a distance answered, and the disagreement is the
finding: if an undifferentiated layer tracks road distance more closely than the
33-66 kV tier does, then an undifferentiated layer cannot answer a connection
question.

Transpower also gives the only available check on how complete OpenStreetMap's
transmission mapping is, which is reported as a recall against it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from nz_solar_siting.config import load_project_config
from nz_solar_siting.geometry import area_hectares, has_width_core
from nz_solar_siting.grid_distance import (
    compare_top_n,
    grid_review_distance_m,
    nearest_distance_m,
    split_by_voltage,
)
from nz_solar_siting.load import read_layer
from nz_solar_siting.osm_layers import read_osm_layer

SHORTLIST = 50


def rank_correlation(left: pd.Series, right: pd.Series) -> dict[str, object]:
    result = stats.spearmanr(left, right)
    rho = float(result.statistic)
    n = int(min(left.notna().sum(), right.notna().sum()))
    interval = None
    if n > 3 and abs(rho) < 1.0:
        margin = 1.959963985 / np.sqrt(n - 3)
        z = np.arctanh(rho)
        interval = [round(float(np.tanh(z - margin)), 4), round(float(np.tanh(z + margin)), 4)]
    return {
        "spearman_rho": round(rho, 4),
        "p_value": float(f"{float(result.pvalue):.3g}"),
        "variance_explained": round(rho ** 2, 4),
        "confidence_interval_95": interval,
        "n": n,
    }


def transmission_recall(osm: gpd.GeoDataFrame, transpower: gpd.GeoDataFrame,
                        tolerance_m: float) -> dict[str, object]:
    """How much of Transpower's grid has an OSM line within ``tolerance_m``.

    A line-for-line match is the wrong test: the two are digitised
    independently, so a shared corridor shows up as two lines a few tens of
    metres apart. Measuring the share of Transpower's length that has any OSM
    transmission line nearby answers the question that matters - whether a
    screen built on OSM would miss a piece of the national grid.
    """
    if osm.empty or transpower.empty:
        return {"transpower_length_km": 0.0, "covered_km": 0.0, "recall": None}
    buffer = osm.geometry.union_all().buffer(tolerance_m)
    total = float(transpower.geometry.length.sum())
    covered = float(transpower.geometry.intersection(buffer).length.sum())
    return {
        "tolerance_m": tolerance_m,
        "transpower_length_km": round(total / 1000.0, 1),
        "covered_km": round(covered / 1000.0, 1),
        "recall": round(covered / total, 3) if total else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", help="Screened polygon layer; defaults to the OSM population")
    parser.add_argument("--output", default="outputs/osm/grid_basis_comparison.json")
    parser.add_argument("--recall-tolerance-m", type=float, default=250.0)
    arguments = parser.parse_args()

    project = load_project_config(ROOT / "config" / "assumptions.yml")
    config = project.siting
    osm_dir = ROOT / "data" / "derived" / "osm"
    grid_dir = ROOT / "data" / "derived" / "grid"

    if arguments.sites:
        sites = read_layer(arguments.sites, ("site_id",), "sites")[["site_id", "geometry"]].copy()
        population = f"supplied: {arguments.sites}"
    else:
        farmland = read_osm_layer("farmland", osm_dir)
        sites = farmland.copy()
        sites["area_ha"] = sites.geometry.map(area_hectares)
        sites = sites.loc[sites["area_ha"] >= config.minimum_area_ha]
        sites = sites.loc[
            sites.geometry.map(lambda g: has_width_core(g, config.minimum_average_width_m))
        ].copy()
        sites["site_id"] = "OSM-" + sites["osm_id"].astype("int64").astype(str)
        sites = sites[["site_id", "geometry"]].sort_values("site_id").reset_index(drop=True)
        population = "OpenStreetMap farmland passing S-01 and S-02"

    roads = read_osm_layer("roads", osm_dir)
    osm_lines = read_osm_layer("powerlines", osm_dir)
    topo = read_layer(grid_dir / "topo50_powerlines.geojson.gz", name="topo50")
    transpower = read_layer(grid_dir / "transpower_lines.geojson.gz", name="transpower")
    live = transpower.loc[transpower["status"].astype(str).str.upper() == "COMMISSIONED"]

    osm_tiers, osm_counts = split_by_voltage(
        osm_lines, config.voltage_tiers, config.excluded_voltage_v, config.voltage_column
    )
    transpower_tiers, transpower_counts = split_by_voltage(
        live, config.voltage_tiers, config.excluded_voltage_v, config.voltage_column
    )

    bases = {
        "topo50_all_lines": topo,
        "osm_33_66kv": osm_tiers[config.connection_tier],
        "osm_22kv_and_below": osm_tiers["distribution_22kv"],
        "osm_110kv_plus": osm_tiers["transmission_110kv_plus"],
        "transpower_110kv_plus": transpower_tiers["transmission_110kv_plus"],
        "road": roads,
    }
    for name, network in bases.items():
        sites[f"{name}_m"] = nearest_distance_m(sites, network).round(1)

    review = grid_review_distance_m(config, config.connection_tier)
    flags = {
        name: (sites[f"{name}_m"] > review) | sites[f"{name}_m"].isna()
        for name in ("topo50_all_lines", "osm_33_66kv", "transpower_110kv_plus")
    }
    agreement = {}
    names = list(flags)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            same = float((flags[left] == flags[right]).mean())
            agreement[f"{left}|{right}"] = round(same, 4)

    summary = {
        "population": population,
        "sites": int(len(sites)),
        "review_distance_m": review,
        "note": (
            "Bases are reported side by side and never merged: grid_basis in the screen "
            "records which layer a distance came from, and combining layers would destroy "
            "that column's meaning."
        ),
        "sources": {
            "topo50_all_lines": "LINZ Topo50 powerline centrelines, CC BY; no voltage attribute",
            "osm_33_66kv": "OpenStreetMap, ODbL; voltage tagged",
            "osm_22kv_and_below": "OpenStreetMap, ODbL; voltage tagged",
            "osm_110kv_plus": "OpenStreetMap, ODbL; voltage tagged",
            "transpower_110kv_plus": "Transpower open data, CC BY; designvolt, commissioned only",
            "road": "OpenStreetMap road centrelines, ODbL",
        },
        "features": {
            "topo50_all_lines": int(len(topo)),
            "osm_tiers": osm_counts,
            "transpower_tiers": transpower_counts,
        },
        "median_distance_m": {
            name: round(float(sites[f"{name}_m"].median()), 1) for name in bases
        },
        "correlation_with_road_distance": {
            name: rank_correlation(sites[f"{name}_m"], sites["road_m"])
            for name in bases if name != "road"
        },
        "top_50_overlap_with_road": {
            name: compare_top_n(
                sites.rename(columns={f"{name}_m": "grid_line_m", "road_m": "road_proxy_m"}),
                SHORTLIST,
            )["jaccard"]
            for name in bases if name != "road"
        },
        "verify_flag_agreement": agreement,
        "osm_transmission_recall_against_transpower": transmission_recall(
            osm_tiers["transmission_110kv_plus"],
            transpower_tiers["transmission_110kv_plus"],
            arguments.recall_tolerance_m,
        ),
    }

    output = ROOT / arguments.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
