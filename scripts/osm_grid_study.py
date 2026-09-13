"""Measure grid-proxy disagreement on real Canterbury geometry.

The demo run answers "does the code work" on twelve deterministic rectangles.
This script answers "how much do the two network proxies actually disagree" on
2,000-plus real OpenStreetMap farmland polygons, real mapped power lines and
real road centrelines. Only the geometric rules that OSM can support are
applied - S-01 minimum area and S-02 usable width - because land-cover class,
LUC class and solar resource still need portal-controlled datasets.

Read the result as an OSM-based measurement, not as a LINZ result: OSM
completeness varies by area and a mapped land-use polygon is not a parcel title.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from nz_solar_siting.geometry import area_hectares, has_width_core
from nz_solar_siting.grid_distance import compare_top_n, nearest_distance_m
from nz_solar_siting.osm_layers import read_osm_layers
from nz_solar_siting.siting import SitingConfig

SHORTLIST_SIZES = (10, 25, 50, 100, 250, 500)
# Three proxies, because "distance to the network" has no single meaning.
# Transmission (power=line) is the closest analogue to the LINZ Topo50 powerline
# layer the original method named; distribution (power=minor_line) is the denser
# rural network; roads are the access proxy. They answer different questions and
# the study reports all three rather than picking one.
PROXIES = {
    "transmission_m": "transmission",
    "distribution_m": "distribution",
    "road_m": "roads",
}


def screen_geometry(farmland: gpd.GeoDataFrame, config: SitingConfig) -> gpd.GeoDataFrame:
    """Apply only the rules that open OSM geometry can actually support."""
    sites = farmland.copy()
    sites["area_ha"] = sites.geometry.map(area_hectares)
    sites = sites.loc[sites["area_ha"] >= config.minimum_area_ha].copy()
    sites["width_core_pass"] = sites.geometry.map(
        lambda geometry: has_width_core(geometry, config.minimum_average_width_m)
    )
    sites = sites.loc[sites["width_core_pass"]].copy()
    sites["site_id"] = "OSM-" + sites["osm_id"].astype("int64").astype(str)
    return sites.sort_values("site_id").reset_index(drop=True)


def plot_disagreement(sites: pd.DataFrame, sweeps: dict[str, pd.DataFrame], path: Path) -> None:
    fig, (scatter_axis, sweep_axis) = plt.subplots(1, 2, figsize=(11.5, 4.8))
    scatter_axis.scatter(
        sites["transmission_m"].clip(lower=1.0), sites["road_m"].clip(lower=1.0),
        s=9, alpha=0.35, c=sites["transmission_road_rank_shift"], cmap="viridis",
    )
    limit = float(max(sites["transmission_m"].max(), sites["road_m"].max())) * 1.05
    scatter_axis.plot([1, limit], [1, limit], linestyle="--", color="#7d8990", linewidth=1)
    scatter_axis.set(
        xlabel="Distance to mapped transmission line (m)",
        ylabel="Distance to mapped road centreline (m)",
        title=f"OSM Canterbury plains, n = {len(sites):,}",
        xscale="log", yscale="log",
    )
    scatter_axis.grid(alpha=0.2, which="both")

    colours = {"transmission_m|road_m": "#2d6a9f", "transmission_m|distribution_m": "#e5a300",
               "distribution_m|road_m": "#19a974"}
    for pair, sweep in sweeps.items():
        left, right = pair.split("|")
        sweep_axis.plot(
            sweep["n"], sweep["jaccard"], marker="o", color=colours.get(pair, "#6d7f8b"),
            label=f"{left.removesuffix('_m')} vs {right.removesuffix('_m')}",
        )
    sweep_axis.set(
        xlabel="Shortlist size N",
        ylabel="Jaccard overlap of the two top-N sets",
        ylim=(0, 1.02),
        title="Agreement between proxy pairs",
    )
    sweep_axis.legend(frameon=False, fontsize=9)
    sweep_axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=170, facecolor="white", metadata={"Software": "nz-solar-siting-screen"})
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/osm")
    parser.add_argument("--aerial-sample", type=int, default=20)
    arguments = parser.parse_args()

    assumptions = yaml.safe_load((ROOT / "config" / "assumptions.yml").read_text(encoding="utf-8"))
    siting = assumptions["siting"]
    config = SitingConfig(
        minimum_area_ha=float(siting["minimum_area_ha"]),
        minimum_average_width_m=float(siting["minimum_average_width_m"]),
        rank_shift_review=int(siting["rank_shift_review"]),
        grid_distance_review_m=float(siting["grid_distance_review_m"]),
    )
    output = ROOT / arguments.output
    output.mkdir(parents=True, exist_ok=True)

    farmland, powerlines, roads = read_osm_layers(ROOT / "data" / "derived" / "osm")
    networks = {
        "transmission": powerlines.loc[powerlines["power"] == "line"],
        "distribution": powerlines.loc[powerlines["power"] == "minor_line"],
        "roads": roads,
    }
    sites = screen_geometry(farmland, config)
    for column, network in PROXIES.items():
        sites[column] = nearest_distance_m(sites, networks[network]).round(1)
        sites[column.replace("_m", "_rank")] = sites[column].rank(method="min").astype(int)

    pairs = [
        ("transmission_m", "road_m"),
        ("transmission_m", "distribution_m"),
        ("distribution_m", "road_m"),
    ]
    for left, right in pairs:
        shift = (
            sites[left.replace("_m", "_rank")] - sites[right.replace("_m", "_rank")]
        ).abs()
        sites[f"{left.removesuffix('_m')}_{right.removesuffix('_m')}_rank_shift"] = shift

    sites["S06_verify_grid"] = (
        sites[list(PROXIES)].max(axis=1) > config.grid_distance_review_m
    ) | (sites["transmission_road_rank_shift"] >= config.rank_shift_review)

    sweeps: dict[str, pd.DataFrame] = {}
    for left, right in pairs:
        comparison = sites.rename(columns={left: "grid_line_m", right: "road_proxy_m"})
        sweep = pd.DataFrame(
            [compare_top_n(comparison, n) for n in SHORTLIST_SIZES if n <= len(sites)]
        )
        sweep["grid_only"] = sweep["grid_only"].map(len)
        sweep["road_only"] = sweep["road_only"].map(len)
        sweeps[f"{left}|{right}"] = sweep

    summary = {
        "source": "OpenStreetMap contributors, ODbL; Canterbury plains extract",
        "scope": (
            "S-01 area and S-02 width only; land cover, LUC and solar resource "
            "still require portal-controlled datasets"
        ),
        "crs": "EPSG:2193",
        "farmland_polygons_downloaded": int(len(farmland)),
        "sites_passing_area_and_width": int(len(sites)),
        "network_features": {name: int(len(frame)) for name, frame in networks.items()},
        "median_distance_m": {
            column: round(float(sites[column].median()), 1) for column in PROXIES
        },
        "rank_correlation": {
            f"{left}|{right}": round(
                float(
                    sites[left.replace("_m", "_rank")].corr(sites[right.replace("_m", "_rank")])
                ),
                4,
            )
            for left, right in pairs
        },
        "median_rank_shift": {
            f"{left}|{right}": int(
                sites[f"{left.removesuffix('_m')}_{right.removesuffix('_m')}_rank_shift"].median()
            )
            for left, right in pairs
        },
        "rank_shift_p90": {
            f"{left}|{right}": int(
                np.percentile(
                    sites[f"{left.removesuffix('_m')}_{right.removesuffix('_m')}_rank_shift"], 90
                )
            )
            for left, right in pairs
        },
        "verify_grid_flagged": int(sites["S06_verify_grid"].sum()),
        "top_n_sweep": {pair: sweep.to_dict(orient="records") for pair, sweep in sweeps.items()},
    }

    published = sites.drop(columns="geometry").copy()
    published["area_ha"] = published["area_ha"].round(1)
    published.to_csv(output / "osm_grid_distance.csv", index=False)
    (output / "osm_grid_study.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    plot_disagreement(sites, sweeps, output / "osm_grid_disagreement.png")

    # The aerial check still needs a person and a LINZ Basemaps key. Hand them
    # the worst disagreements with coordinates and a link, rather than claiming
    # a visual review that was never done.
    sample = sites.nlargest(arguments.aerial_sample, "transmission_road_rank_shift").copy()
    centroids = sample.geometry.centroid.to_crs("EPSG:4326")
    sample["latitude"] = centroids.y.round(6)
    sample["longitude"] = centroids.x.round(6)
    sample["basemaps_url"] = [
        f"https://basemaps.linz.govt.nz/@{lat},{lon},z16"
        for lat, lon in zip(sample["latitude"], sample["longitude"])
    ]
    log_path = ROOT / "data" / "aerial_review_log.csv"
    log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame(
        columns=["site_id", "reviewed_on", "reviewer", "imagery", "finding"]
    )
    sample = sample.merge(log, on="site_id", how="left", validate="one_to_one")
    summary["aerial_review"] = {
        "queued": int(len(sample)),
        "reviewed": int(sample["finding"].notna().sum()),
        "log": str(log_path.relative_to(ROOT).as_posix()),
    }
    (output / "osm_grid_study.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sample[[
        "site_id", "area_ha", "transmission_m", "distribution_m", "road_m",
        "transmission_rank", "road_rank", "transmission_road_rank_shift",
        "latitude", "longitude", "basemaps_url", "reviewed_on", "reviewer", "imagery", "finding",
    ]].round({"area_ha": 1, "latitude": 6, "longitude": 6}).to_csv(
        output / "aerial_review_queue.csv", index=False
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
