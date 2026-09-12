"""M1: auditable exclusion, flag and ranking rules."""

from __future__ import annotations

from dataclasses import dataclass
import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from .geometry import area_hectares, mean_width_area_perimeter
from .grid_distance import add_grid_proxies
from .load import assert_nztm


@dataclass(frozen=True)
class SitingConfig:
    minimum_area_ha: float = 20.0
    minimum_average_width_m: float = 180.0
    usable_lcdb_classes: tuple[str, ...] = (
        "High Producing Exotic Grassland",
        "Low Producing Grassland",
        "Short-rotation Cropland",
        "Orchard Vineyard or Other Perennial Crop",
    )
    grid_distance_review_m: float = 5000.0


def evaluate_sites(
    sites: gpd.GeoDataFrame,
    conservation: gpd.GeoDataFrame,
    powerlines: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    config: SitingConfig | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    cfg = config or SitingConfig()
    for name, frame in {
        "sites": sites,
        "conservation": conservation,
        "powerlines": powerlines,
        "roads": roads,
    }.items():
        assert_nztm(frame, name)
    required = {"site_id", "lcdb_class", "luc_class", "solar_kwh_m2"}
    missing = required - set(sites.columns)
    if missing:
        raise ValueError(f"sites missing columns: {', '.join(sorted(missing))}")

    out = sites.copy()
    out["area_ha"] = out.geometry.map(area_hectares).round(2)
    out["mean_width_m"] = out.geometry.map(mean_width_area_perimeter).round(1)
    protected = unary_union(conservation.geometry.tolist()) if not conservation.empty else None
    out["S01_pass"] = out["area_ha"] >= cfg.minimum_area_ha
    out["S02_pass"] = out["mean_width_m"] >= cfg.minimum_average_width_m
    out["S03_pass"] = out["lcdb_class"].isin(cfg.usable_lcdb_classes)
    out["S04_pass"] = ~out.geometry.map(
        lambda geom: bool(protected is not None and geom.intersects(protected))
    )
    out["S05_hpl_flag"] = out["luc_class"].isin([1, 2, 3])
    out = add_grid_proxies(out, powerlines, roads)
    out["S06_verify_grid"] = (
        out[["grid_line_m", "road_proxy_m"]].max(axis=1) > cfg.grid_distance_review_m
    ) | (out["rank_shift"] >= 3)
    out["solar_rank"] = out["solar_kwh_m2"].rank(ascending=False, method="min").astype(int)

    exclude_columns = ["S01_pass", "S02_pass", "S03_pass", "S04_pass"]
    rule_ids = ["S-01", "S-02", "S-03", "S-04"]
    out["failed_rule_ids"] = out.apply(
        lambda row: ";".join(rule for rule, col in zip(rule_ids, exclude_columns) if not row[col]),
        axis=1,
    )
    out["status"] = out["failed_rule_ids"].map(
        lambda rules: "candidate_review" if not rules else "quarantine"
    )
    out["screen_score"] = (
        0.55 * out["road_proxy_m"].rank(pct=True, ascending=False)
        + 0.25 * out["grid_line_m"].rank(pct=True, ascending=False)
        + 0.20 * out["solar_kwh_m2"].rank(pct=True)
    ).round(4)

    audit = out[["site_id", "status", "failed_rule_ids", "S05_hpl_flag", "S06_verify_grid"]].copy()
    return out, audit

