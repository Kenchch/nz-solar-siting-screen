"""M1: auditable exclusion, flag and ranking rules.

``screen_score`` orders a review queue from the two attributes the screen can
actually measure from open data: solar resource and usable area. Every weight
and threshold comes from ``config/assumptions.yml`` via :class:`SitingConfig`.
Grid distance is reported as two distances, two ranks, a rank shift and the
``S06_verify_grid`` flag, and is not folded into the score.
"""

from __future__ import annotations

from dataclasses import dataclass
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

from .geometry import area_hectares, has_width_core, mean_width_area_perimeter
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
    rank_shift_review: int = 3
    # Review-ordering weights only. Grid distance is deliberately absent: the
    # project's own argument is that network proximity is too uncertain to act
    # as a score, so it stays a published distance pair plus a verify flag.
    solar_score_weight: float = 0.6
    area_score_weight: float = 0.4


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
    if sites["site_id"].isna().any() or sites["site_id"].astype(str).str.strip().eq("").any():
        raise ValueError("sites.site_id contains missing or blank values")
    if sites["site_id"].astype(str).duplicated().any():
        raise ValueError("sites.site_id must be unique")
    if not sites.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("sites geometry must contain only Polygon or MultiPolygon features")
    solar = pd.to_numeric(sites["solar_kwh_m2"], errors="coerce")
    luc = pd.to_numeric(sites["luc_class"], errors="coerce")
    if not np.isfinite(solar).all():
        raise ValueError("sites.solar_kwh_m2 must contain only finite numbers")
    if luc.isna().any():
        raise ValueError("sites.luc_class must contain only numeric values")

    out = sites.copy()
    out["area_ha"] = out.geometry.map(area_hectares).round(2)
    out["width_2ap_m"] = out.geometry.map(mean_width_area_perimeter).round(1)
    out["width_core_pass"] = out.geometry.map(
        lambda geometry: has_width_core(geometry, cfg.minimum_average_width_m)
    )
    out["width_methods_disagree"] = (
        out["width_2ap_m"] >= cfg.minimum_average_width_m
    ) != out["width_core_pass"]
    protected = unary_union(conservation.geometry.tolist()) if not conservation.empty else None
    out["S01_pass"] = out["area_ha"] >= cfg.minimum_area_ha
    out["S02_pass"] = out["width_core_pass"]
    out["S03_pass"] = out["lcdb_class"].isin(cfg.usable_lcdb_classes)
    out["S04_pass"] = ~out.geometry.map(
        lambda geom: bool(protected is not None and geom.intersects(protected))
    )
    out["solar_kwh_m2"] = solar
    out["luc_class"] = luc
    out["S05_hpl_flag"] = out["luc_class"].isin([1, 2, 3])
    out = add_grid_proxies(out, powerlines, roads)

    exclude_columns = ["S01_pass", "S02_pass", "S03_pass", "S04_pass"]
    rule_ids = ["S-01", "S-02", "S-03", "S-04"]
    out["failed_rule_ids"] = out.apply(
        lambda row: ";".join(rule for rule, col in zip(rule_ids, exclude_columns) if not row[col]),
        axis=1,
    )
    out["status"] = out["failed_rule_ids"].map(
        lambda rules: "candidate_review" if not rules else "quarantine"
    )
    candidate = out["status"].eq("candidate_review")
    for column in ("grid_rank", "road_rank", "solar_rank"):
        out[column] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out.loc[candidate, "grid_rank"] = out.loc[candidate, "grid_line_m"].rank(method="min").astype("Int64")
    out.loc[candidate, "road_rank"] = out.loc[candidate, "road_proxy_m"].rank(method="min").astype("Int64")
    out.loc[candidate, "solar_rank"] = out.loc[candidate, "solar_kwh_m2"].rank(
        ascending=False, method="min"
    ).astype("Int64")
    out["rank_shift"] = (out["grid_rank"] - out["road_rank"]).abs().astype("Int64")
    out["S06_verify_grid"] = candidate & (
        (out[["grid_line_m", "road_proxy_m"]].max(axis=1) > cfg.grid_distance_review_m)
        | (out["rank_shift"].fillna(0) >= cfg.rank_shift_review)
    )
    weight_total = cfg.solar_score_weight + cfg.area_score_weight
    if weight_total <= 0:
        raise ValueError("screen-score weights must sum to a positive number")
    out["screen_score"] = np.nan
    out.loc[candidate, "screen_score"] = (
        cfg.solar_score_weight * out.loc[candidate, "solar_kwh_m2"].rank(pct=True)
        + cfg.area_score_weight * out.loc[candidate, "area_ha"].rank(pct=True)
    ) / weight_total
    out["screen_score"] = out["screen_score"].round(4)

    audit = out[[
        "site_id", "status", "failed_rule_ids", "width_2ap_m", "width_core_pass",
        "width_methods_disagree", "S05_hpl_flag", "S06_verify_grid",
    ]].copy()
    return out, audit
