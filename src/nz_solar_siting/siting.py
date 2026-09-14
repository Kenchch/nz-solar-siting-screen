"""M1: auditable exclusion, flag and ranking rules.

``screen_score`` orders a review queue from the two attributes the screen can
actually measure from open data: solar resource and usable area. Every weight
and threshold comes from ``config/assumptions.yml`` via :class:`SitingConfig`.
Grid distance is reported as per-voltage-tier distances, two ranks, a rank
shift and the ``S06_verify_grid`` flag, and is not folded into the score. S-06
itself lives in :mod:`grid_distance` so that the screen and every study share
one implementation of it.
"""

from __future__ import annotations

from dataclasses import dataclass
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

from .geometry import area_hectares, has_width_core, mean_width_area_perimeter
from .grid_distance import add_grid_proxies, nearest_distance_m, verify_grid_flag
from .load import assert_nztm


@dataclass(frozen=True)
class VoltageTier:
    """One band of the network, and how far from it is worth a human look."""

    name: str
    minimum_v: float
    maximum_v: float
    review_distance_m: float


# A project of tens of megawatts connects at 33 or 66 kV. It does not connect to
# an HVDC pole, and a 220 kV connection is a different project with a different
# budget, so the bands are the ones a connection decision distinguishes.
DEFAULT_VOLTAGE_TIERS: tuple[VoltageTier, ...] = (
    VoltageTier("transmission_110kv_plus", 110_000.0, 349_999.0, 20_000.0),
    VoltageTier("subtransmission_33_66kv", 33_000.0, 109_999.0, 5_000.0),
    VoltageTier("distribution_22kv", 0.0, 32_999.0, 1_000.0),
)


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
    # Fallback review distance, used only when the powerline layer carries no
    # voltage attribute and the tiers cannot be applied.
    grid_distance_review_m: float = 5000.0
    voltage_tiers: tuple[VoltageTier, ...] = DEFAULT_VOLTAGE_TIERS
    connection_tier: str = "subtransmission_33_66kv"
    excluded_voltage_v: float = 350_000.0
    voltage_column: str = "voltage"
    # S-08 exclusion threshold, and S-10 review distance. The slope value itself
    # is computed elsewhere and arrives as a column, so this module never needs
    # a raster reader.
    maximum_mean_slope_deg: float = 10.0
    coastal_review_distance_m: float = 1000.0
    # Published for inspection and used to select review queues. Deliberately
    # not part of S-06: a threshold counted in ranks does not transfer between
    # sample sizes.
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
    terrain: pd.DataFrame | None = None,
    water: gpd.GeoDataFrame | None = None,
    coastline: gpd.GeoDataFrame | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Apply every rule in the register to one set of layers.

    ``terrain`` is a table keyed on ``site_id`` carrying ``mean_slope_deg``,
    produced by ``scripts/compute_site_terrain.py``. Slope arrives as a column
    rather than as a raster on purpose: this module stays free of a raster
    reader, so the library's dependency surface does not grow and CI never has
    to download a DEM. A site with no slope value is neither excluded nor
    quietly passed - S-08 leaves it in and raises ``S08_verify_slope``.

    ``water`` and ``coastline`` are vector layers and are read directly.
    Omitting any of the three leaves its rule unapplied and says so in the
    audit, rather than reporting a pass it did not earn.
    """
    cfg = config or SitingConfig()
    for name, frame in {
        "sites": sites,
        "conservation": conservation,
        "powerlines": powerlines,
        "roads": roads,
    }.items():
        assert_nztm(frame, name)
    for name, frame in {"water": water, "coastline": coastline}.items():
        if frame is not None:
            assert_nztm(frame, name)
    required = {"site_id", "lcdb_class", "luc_class", "solar_kwh_m2"}
    missing = required - set(sites.columns)
    if missing:
        raise ValueError(f"sites missing columns: {', '.join(sorted(missing))}")
    if sites["site_id"].isna().any() or sites["site_id"].astype(str).str.strip().eq("").any():
        raise ValueError("sites.site_id contains missing or blank values")
    if sites["site_id"].astype(str).duplicated().any():
        raise ValueError("sites.site_id must be unique")
    # Every per-site distance is a spatial join collapsed back onto one row per
    # site. Two rows sharing an index label collapse into one another, and both
    # then report the nearest distance either of them had - a silent wrong
    # number, not an error. explode() leaves exactly such an index behind, so
    # this is the state a caller following the multipart advice below lands in.
    if not sites.index.is_unique:
        raise ValueError(
            "sites has a non-unique index; distances are joined per row, so duplicate "
            "index labels would silently give sites each other's distances. "
            "Call reset_index(drop=True) before screening."
        )
    # S-01 and S-02 are about one contiguous block of land. A MultiPolygon's
    # area is the sum of its parts, so two 10 ha squares five kilometres apart
    # would pass a 20 ha rule and a width test neither part can satisfy. The
    # assembly step already explodes multiparts, so this refuses rather than
    # silently measuring the wrong thing.
    multipart = sites.geom_type.eq("MultiPolygon")
    if multipart.any():
        example = sites.loc[multipart, "site_id"].iloc[0]
        raise ValueError(
            f"sites contains {int(multipart.sum())} MultiPolygon features, first {example!r}. "
            "Area and width are contiguity rules; explode multiparts before screening "
            "(GeoDataFrame.explode(index_parts=False).reset_index(drop=True))."
        )
    if not sites.geom_type.eq("Polygon").all():
        raise ValueError("sites geometry must contain only Polygon features")
    solar = pd.to_numeric(sites["solar_kwh_m2"], errors="coerce")
    luc = pd.to_numeric(sites["luc_class"], errors="coerce")
    if not np.isfinite(solar).all():
        raise ValueError("sites.solar_kwh_m2 must contain only finite numbers")
    if luc.isna().any():
        raise ValueError("sites.luc_class must contain only numeric values")

    out = sites.copy()
    # Round for publication, compare on the measurement: rounding first lets
    # 19.995 ha pass a 20 ha rule.
    exact_area_ha = out.geometry.map(area_hectares)
    out["area_ha"] = exact_area_ha.round(2)
    out["width_2ap_m"] = out.geometry.map(mean_width_area_perimeter).round(1)
    out["width_core_pass"] = out.geometry.map(
        lambda geometry: has_width_core(geometry, cfg.minimum_average_width_m)
    )
    out["width_methods_disagree"] = (
        out["width_2ap_m"] >= cfg.minimum_average_width_m
    ) != out["width_core_pass"]
    out["S01_pass"] = exact_area_ha >= cfg.minimum_area_ha
    out["S02_pass"] = out["width_core_pass"]
    out["S03_pass"] = out["lcdb_class"].isin(cfg.usable_lcdb_classes)
    # A spatial-index join rather than a union and a row loop: the union of a
    # national conservation layer is expensive to build and slow to test against.
    if conservation.empty:
        out["S04_pass"] = True
    else:
        # The register asks for a *material* intersection; "intersects" is also
        # true of a shared boundary, which is an overlap of nothing at all. The
        # spatial index still finds the candidate pairs and only those pairs are
        # intersected, so the national layer is still never unioned.
        #
        # Measured, this releases nobody: on the 10,684 cadastral units all
        # 1,473 conservation hits have a positive overlap, because two
        # independently digitised LINZ layers do not share exact edges. What
        # they do share is slivers - 1,103 of those 1,473 overlap by 1 m2 or
        # less - and "> 0" does not touch those either. So this closes the gap
        # between the code and the register without yet answering what
        # "material" should mean; see the sliver note in the README.
        neighbours = conservation.geometry.reset_index(drop=True)
        hits = gpd.sjoin(
            out[["geometry"]],
            gpd.GeoDataFrame(geometry=neighbours, crs=conservation.crs),
            how="inner", predicate="intersects",
        )
        matched = gpd.GeoSeries(
            neighbours.to_numpy()[hits["index_right"].to_numpy()],
            index=hits.index, crs=conservation.crs,
        )
        overlap_m2 = out.geometry.loc[hits.index].intersection(matched, align=False).area
        out["S04_pass"] = ~out.index.isin(hits.index[overlap_m2.to_numpy() > 0.0])
    out["solar_kwh_m2"] = solar
    out["luc_class"] = luc
    out["S05_hpl_flag"] = out["luc_class"].isin([1, 2, 3])
    out = add_grid_proxies(out, powerlines, roads, cfg)

    # S-08 slope. The value is precomputed into a per-site table, so a missing
    # row is a gap in the inputs rather than a property of the land: it must not
    # read as "this site is flat".
    supplied_column = "mean_slope_deg" in sites.columns
    if terrain is not None:
        if "site_id" not in terrain.columns or "mean_slope_deg" not in terrain.columns:
            raise ValueError("terrain must carry site_id and mean_slope_deg")
        if supplied_column:
            raise ValueError(
                "mean_slope_deg is present on sites and a terrain table was also given; "
                "pass one or the other so it is unambiguous which slope was screened"
            )
        slope = pd.to_numeric(
            out["site_id"].map(
                terrain.drop_duplicates("site_id").set_index("site_id")["mean_slope_deg"]
            ),
            errors="coerce",
        )
    elif supplied_column:
        # A caller who has already joined slope on must not have it silently
        # overwritten with NaN and then read S-08 as inapplicable.
        slope = pd.to_numeric(sites["mean_slope_deg"], errors="coerce")
    else:
        slope = pd.Series(np.nan, index=out.index, dtype=float)
    out["mean_slope_deg"] = slope.round(3)
    out["S08_pass"] = ~(slope > cfg.maximum_mean_slope_deg)
    out["S08_verify_slope"] = slope.isna()

    # S-09 mapped water, S-10 coastal proximity. Round for publication, compare
    # on the measurement - the same order S-01 already follows. It matters most
    # for S-09, whose threshold is zero: a site 4 cm from a mapped lake rounds
    # to 0.0 m and used to be quarantined for intersecting water it does not
    # touch.
    if water is not None and not water.empty:
        water_m = nearest_distance_m(out, water)
    else:
        water_m = pd.Series(np.nan, index=out.index, dtype=float)
    out["water_m"] = water_m.round(1)
    out["S09_pass"] = ~(water_m <= 0.0)
    if coastline is not None and not coastline.empty:
        coastline_m = nearest_distance_m(out, coastline)
    else:
        coastline_m = pd.Series(np.nan, index=out.index, dtype=float)
    out["coastline_m"] = coastline_m.round(1)
    out["S10_coastal_flag"] = coastline_m < cfg.coastal_review_distance_m

    exclude_columns = ["S01_pass", "S02_pass", "S03_pass", "S04_pass", "S08_pass", "S09_pass"]
    rule_ids = ["S-01", "S-02", "S-03", "S-04", "S-08", "S-09"]
    failed = pd.DataFrame(
        {rule: ~out[column].astype(bool) for rule, column in zip(rule_ids, exclude_columns)},
        index=out.index,
    )
    out["failed_rule_ids"] = [
        ";".join(rule for rule in rule_ids if row[rule])
        for row in failed.to_dict(orient="records")
    ]
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
    out["S06_verify_grid"] = candidate & verify_grid_flag(out, cfg)
    weight_total = cfg.solar_score_weight + cfg.area_score_weight
    if weight_total <= 0:
        raise ValueError("screen-score weights must sum to a positive number")
    out["screen_score"] = np.nan
    out.loc[candidate, "screen_score"] = (
        cfg.solar_score_weight * out.loc[candidate, "solar_kwh_m2"].rank(pct=True)
        + cfg.area_score_weight * out.loc[candidate, "area_ha"].rank(pct=True)
    ) / weight_total
    out["screen_score"] = out["screen_score"].round(4)

    out["rules_not_applied"] = ";".join(
        rule for rule, supplied in (
            ("S-08", terrain is not None or supplied_column),
            ("S-09", water is not None),
            ("S-10", coastline is not None),
        ) if not supplied
    )

    audit = out[[
        "site_id", "status", "failed_rule_ids", "rules_not_applied",
        "width_2ap_m", "width_core_pass", "width_methods_disagree",
        "S05_hpl_flag", "S06_verify_grid", "S08_verify_slope", "S10_coastal_flag",
    ]].copy()
    return out, audit
