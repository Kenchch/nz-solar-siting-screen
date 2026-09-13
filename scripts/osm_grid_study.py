"""Measure grid-proxy disagreement on real Canterbury geometry, by voltage.

The demo run answers "does the code work" on twelve deterministic rectangles.
This script answers "how much does a road proxy actually tell you about the
network a project could connect to", on 2,000-plus real OpenStreetMap farmland
polygons and real mapped lines.

Power lines are split by **voltage**, not by OSM ``power`` tag. The committed
extract has 66 kV ways tagged both ``line`` and ``minor_line``, so the tag split
cuts straight through the tier that matters: a Canterbury project of tens of
megawatts connects at 33 or 66 kV, not at 220 kV and not to an HVDC pole.

S-01 area and S-02 width define the study population, and the grid statistics
are reported over it so they stay comparable across runs. The terrain and water
rules added after the aerial review - S-08 mean slope, S-09 mapped water, S-10
coastal proximity - are evaluated on the same population and reported beside it,
including how they score against the twenty hand-labelled sites. Land-cover
class, LUC class and solar resource still need portal-controlled datasets.

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
from nz_solar_siting.osm_layers import read_osm_layer, read_osm_layers, split_by_voltage
from nz_solar_siting.siting import SitingConfig

SHORTLIST_SIZES = (10, 25, 50, 100, 250, 500)
TIER_COLOURS = {
    "transmission_110kv_plus": "#b5179e",
    "subtransmission_33_66kv": "#2d6a9f",
    "distribution_22kv": "#19a974",
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


def plot_disagreement(
    sites: pd.DataFrame, sweeps: dict[str, pd.DataFrame], connection_tier: str, path: Path
) -> None:
    fig, (scatter_axis, sweep_axis) = plt.subplots(1, 2, figsize=(11.5, 4.8))
    scatter_axis.scatter(
        sites[f"{connection_tier}_m"].clip(lower=1.0), sites["road_m"].clip(lower=1.0),
        s=9, alpha=0.35, c=sites[f"{connection_tier}_road_rank_shift"], cmap="viridis",
    )
    limit = float(max(sites[f"{connection_tier}_m"].max(), sites["road_m"].max())) * 1.05
    scatter_axis.plot([1, limit], [1, limit], linestyle="--", color="#7d8990", linewidth=1)
    scatter_axis.set(
        xlabel="Distance to a mapped 33-66 kV line (m)",
        ylabel="Distance to a mapped road centreline (m)",
        title=f"Connection-tier distance vs road, n = {len(sites):,}",
        xscale="log", yscale="log",
    )
    scatter_axis.grid(alpha=0.2, which="both")

    for pair, sweep in sweeps.items():
        left, right = pair.split("|")
        if right != "road_m":
            continue
        tier = left.removesuffix("_m")
        sweep_axis.plot(
            sweep["n"], sweep["jaccard"], marker="o",
            color=TIER_COLOURS.get(tier, "#6d7f8b"), label=f"{tier} vs road",
        )
    sweep_axis.set(
        xlabel="Shortlist size N",
        ylabel="Jaccard overlap with the road-ranked shortlist",
        ylim=(0, 1.02),
        title="How much a road proxy recovers, by voltage tier",
    )
    sweep_axis.legend(frameon=False, fontsize=8)
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
    study_config = assumptions["osm_study"]
    tiers = study_config["voltage_tiers"]
    connection_tier = str(study_config["connection_tier"])
    config = SitingConfig(
        minimum_area_ha=float(siting["minimum_area_ha"]),
        minimum_average_width_m=float(siting["minimum_average_width_m"]),
        rank_shift_review=int(siting["rank_shift_review"]),
        grid_distance_review_m=float(siting["grid_distance_review_m"]),
    )
    output = ROOT / arguments.output
    output.mkdir(parents=True, exist_ok=True)

    osm_dir = ROOT / "data" / "derived" / "osm"
    farmland, powerlines, roads, wetland, coastline = read_osm_layers(osm_dir)
    networks, tier_counts = split_by_voltage(
        powerlines, tiers, float(study_config["excluded_voltage_v"])
    )
    networks["road"] = roads

    sites = screen_geometry(farmland, config)
    proxies = [f"{name}_m" for name in (*tiers, "road")]
    for column in proxies:
        network = networks[column.removesuffix("_m")]
        sites[column] = nearest_distance_m(sites, network).round(1)
        sites[column.replace("_m", "_rank")] = sites[column].rank(method="min").astype(int)

    pairs = [(f"{name}_m", "road_m") for name in tiers]
    pairs.append((f"{connection_tier}_m", "transmission_110kv_plus_m"))

    def shift_column(left: str, right: str) -> str:
        return f"{left.removesuffix('_m')}_{right.removesuffix('_m')}_rank_shift"

    for left, right in pairs:
        sites[shift_column(left, right)] = (
            sites[left.replace("_m", "_rank")] - sites[right.replace("_m", "_rank")]
        ).abs()

    # The flag is distance to the tier a project could actually connect to. The
    # previous version took the maximum across every proxy, which fired on 2,347
    # of 2,356 sites and therefore said nothing. An absolute rank-shift trigger
    # is deliberately not part of it either: rank_shift_review = 3 was chosen
    # against eight demo fixtures and is meaningless at this sample size, where
    # the median shift runs to the hundreds. The shift stays a published column.
    review_distance = float(tiers[connection_tier]["review_distance_m"])
    sites["S06_verify_grid"] = sites[f"{connection_tier}_m"] > review_distance

    # Terrain and water. The aerial review found that none of the screen's worst
    # false positives was a grid problem: they were steep, wet or coastal, and
    # the baseline had no rule for any of that.
    terrain_config = study_config["terrain"]
    terrain = pd.read_csv(osm_dir / "site_terrain.csv")
    sites = sites.merge(terrain, on="site_id", how="left", validate="one_to_one")
    if sites["mean_slope_deg"].isna().any():
        raise RuntimeError(
            "site_terrain.csv does not cover every site; rerun scripts/compute_site_terrain.py"
        )
    sites["water_m"] = nearest_distance_m(sites, wetland).round(1)
    sites["coastline_m"] = nearest_distance_m(sites, coastline).round(1)
    maximum_slope = float(terrain_config["maximum_mean_slope_deg"])
    coastal_review = float(terrain_config["coastal_review_distance_m"])
    sites["S08_slope_pass"] = sites["mean_slope_deg"] <= maximum_slope
    sites["S09_water_pass"] = sites["water_m"] > 0.0
    sites["S10_coastal_flag"] = sites["coastline_m"] < coastal_review
    sites["terrain_water_pass"] = sites["S08_slope_pass"] & sites["S09_water_pass"]

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
            "S-01 area and S-02 width define the population; S-08 slope and S-09 water "
            "exclude, S-10 coastal flags. Land cover, LUC class and solar resource still "
            "require portal-controlled datasets"
        ),
        "crs": "EPSG:2193",
        "farmland_polygons_downloaded": int(len(farmland)),
        "sites_passing_area_and_width": int(len(sites)),
        "connection_tier": connection_tier,
        "connection_tier_review_distance_m": review_distance,
        "voltage_tier_features": tier_counts,
        "road_features": int(len(roads)),
        "median_distance_m": {
            column: round(float(sites[column].median()), 1) for column in proxies
        },
        "distance_p90_m": {
            column: round(float(np.percentile(sites[column], 90)), 1) for column in proxies
        },
        "rank_correlation": {
            f"{left}|{right}": round(
                float(sites[left.replace("_m", "_rank")].corr(sites[right.replace("_m", "_rank")])),
                4,
            )
            for left, right in pairs
        },
        "median_rank_shift": {
            f"{left}|{right}": int(sites[shift_column(left, right)].median())
            for left, right in pairs
        },
        "rank_shift_p90": {
            f"{left}|{right}": int(np.percentile(sites[shift_column(left, right)], 90))
            for left, right in pairs
        },
        "beyond_tier_review_distance": {
            name: int((sites[f"{name}_m"] > float(bounds["review_distance_m"])).sum())
            for name, bounds in tiers.items()
        },
        "verify_grid_flagged": int(sites["S06_verify_grid"].sum()),
        "terrain_water": {
            "maximum_mean_slope_deg": maximum_slope,
            "coastal_review_distance_m": coastal_review,
            "median_mean_slope_deg": round(float(sites["mean_slope_deg"].median()), 2),
            "excluded_by_slope": int((~sites["S08_slope_pass"]).sum()),
            "excluded_by_water": int((~sites["S09_water_pass"]).sum()),
            "excluded_by_either": int((~sites["terrain_water_pass"]).sum()),
            "flagged_coastal": int(sites["S10_coastal_flag"].sum()),
            "surviving_sites": int(sites["terrain_water_pass"].sum()),
        },
        "top_n_sweep": {pair: sweep.to_dict(orient="records") for pair, sweep in sweeps.items()},
    }

    published = sites.drop(columns="geometry").copy()
    published["area_ha"] = published["area_ha"].round(1)
    published.to_csv(output / "osm_grid_distance.csv", index=False)
    plot_disagreement(sites, sweeps, connection_tier, output / "osm_grid_disagreement.png")

    # The aerial check needs a person and imagery. Queue the worst connection-tier
    # disagreements with coordinates and a deep link, and fold in the findings
    # already recorded so a re-run never discards them.
    shift = shift_column(f"{connection_tier}_m", "road_m")
    sample = sites.nlargest(arguments.aerial_sample, shift).copy()
    centroids = sample.geometry.centroid.to_crs("EPSG:4326")
    sample["latitude"] = centroids.y.round(6)
    sample["longitude"] = centroids.x.round(6)
    sample["basemaps_url"] = [
        f"https://basemaps.linz.govt.nz/@{lat},{lon},z16"
        for lat, lon in zip(sample["latitude"], sample["longitude"])
    ]
    log_path = ROOT / "data" / "aerial_review_log.csv"
    log_columns = [
        "site_id", "reviewed_on", "reviewer", "second_pass_on", "second_pass_result",
        "author_confirmed_on", "imagery", "zoom_level", "evidence_image",
        "centroid_to_coastline_m", "centroid_to_water_m",
        "observed_detail", "developable", "finding",
    ]
    log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame(columns=log_columns)
    for image in log.get("evidence_image", pd.Series(dtype=str)).dropna():
        if not (ROOT / image).exists():
            raise FileNotFoundError(f"aerial review log cites missing evidence: {image}")
    sample = sample.merge(log, on="site_id", how="left", validate="one_to_one")
    reviewed = int(sample["finding"].notna().sum())
    not_developable = int((sample["developable"] == "no").sum())
    # Score the new rules against the hand-labelled sample. These thresholds were
    # chosen with these labels in view, so this is in-sample: it says the rules
    # express what the imagery showed, not that they generalise.
    bad = sample["developable"] == "no"
    good = sample["developable"] == "yes"
    # Excluding a site and flagging it for review are different outcomes, the
    # same distinction S-05 rests on. A site that only trips the coastal flag
    # still reaches a human as a candidate, so it is not "caught".
    excluded = ~sample["terrain_water_pass"]
    flagged_only = sample["terrain_water_pass"] & sample["S10_coastal_flag"]
    summary["aerial_review"] = {
        "queued": int(len(sample)),
        "reviewed": reviewed,
        "not_developable": not_developable,
        "false_positive_rate": round(not_developable / reviewed, 3) if reviewed else None,
        "selection": (
            "the largest connection-tier-versus-road rank disagreements; selected on "
            "disagreement, so this rate describes the road proxy's worst cases and "
            "not the candidate population"
        ),
        "in_sample_rule_check": {
            "excluded_by_slope": int((bad & ~sample["S08_slope_pass"]).sum()),
            "excluded_by_water": int((bad & ~sample["S09_water_pass"]).sum()),
            "excluded_total": int((bad & excluded).sum()),
            "flagged_only_by_coast": int((bad & flagged_only).sum()),
            "neither_excluded_nor_flagged": sorted(
                sample.loc[bad & ~excluded & ~flagged_only, "site_id"]
            ),
            "developable_sites_wrongly_excluded": int((good & excluded).sum()),
            "developable_sites_flagged_only": int((good & flagged_only).sum()),
        },
        "second_pass": {
            "confirmed": int((sample["second_pass_result"] == "confirmed").sum()),
            "corrected": int((sample["second_pass_result"] == "corrected").sum()),
            "author_confirmed": int(sample["author_confirmed_on"].notna().sum()),
        },
        "log": log_path.relative_to(ROOT).as_posix(),
    }
    (output / "osm_grid_study.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sample[[
        "site_id", "area_ha", *proxies, f"{connection_tier}_rank", "road_rank", shift,
        "mean_slope_deg", "water_m", "coastline_m",
        "S08_slope_pass", "S09_water_pass", "S10_coastal_flag",
        "latitude", "longitude", "basemaps_url",
        "reviewed_on", "reviewer", "second_pass_on", "second_pass_result",
        "author_confirmed_on", "imagery", "zoom_level", "evidence_image",
        "observed_detail", "developable", "finding",
    ]].round({"area_ha": 1, "latitude": 6, "longitude": 6, "mean_slope_deg": 2}).to_csv(
        output / "aerial_review_queue.csv", index=False
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
