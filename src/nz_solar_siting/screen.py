"""Main screening pipeline with quarantine and reject-rate gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import geopandas as gpd

from .demo_data import build_demo_layers
from .grid_distance import compare_top_n
from .siting import SitingConfig, evaluate_sites


class RejectRateExceeded(RuntimeError):
    """Raised when rejection suggests a broken input or wrong rule configuration."""


def run_screening(
    sites: gpd.GeoDataFrame,
    conservation: gpd.GeoDataFrame,
    powerlines: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    output_dir: str | Path,
    reject_rate_threshold: float = 0.80,
    config: SitingConfig | None = None,
) -> dict[str, object]:
    results, audit = evaluate_sites(sites, conservation, powerlines, roads, config)
    reject_rate = float((results["status"] == "quarantine").mean())
    if reject_rate > reject_rate_threshold:
        raise RejectRateExceeded(
            f"reject rate {reject_rate:.1%} exceeds {reject_rate_threshold:.1%}; publication aborted"
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    candidates = results[results["status"] == "candidate_review"].copy()
    quarantine = results[results["status"] == "quarantine"].copy()
    candidates.to_file(output / "candidates.gpkg", layer="candidates", driver="GPKG")
    quarantine.to_file(output / "quarantine.gpkg", layer="quarantine", driver="GPKG")
    audit.to_csv(output / "rule_results.csv", index=False)
    comparison = compare_top_n(candidates, min(4, len(candidates)))
    summary = {
        "scope": "screening only; demo geometries are not real parcels",
        "crs": "EPSG:2193",
        "total": len(results),
        "candidates": len(candidates),
        "quarantine": len(quarantine),
        "reject_rate": round(reject_rate, 4),
        "grid_comparison": comparison,
    }
    (output / "run_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Run deterministic NZTM demonstration")
    parser.add_argument("--output", default="outputs/demo")
    args = parser.parse_args()
    if not args.demo:
        parser.error("Use scripts/reproduce.py for the configured real-data workflow, or pass --demo")
    layers = build_demo_layers()
    print(json.dumps(run_screening(*layers, args.output), indent=2))


if __name__ == "__main__":
    main()
