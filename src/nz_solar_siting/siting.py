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

from .geometry import (
    area_hectares,
    has_width_core,
    mean_width_area_perimeter,
    overlap_noise_band_m2,
)
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
    # Positional accuracy of each pair of layers a rule intersects, in metres.
    # An overlap smaller than accuracy x boundary length cannot be told apart
    # from the two publishers disagreeing about where the boundary runs. Both
    # come from the publishers' own statements, quoted in assumptions.yml under
    # siting.source_accuracy; neither is tuned against the screened population.
    conservation_overlay_accuracy_m: float = 0.5
    luc_overlay_accuracy_m: float = 32.0
    # Published for inspection and used to select review queues. Deliberately
    # not part of S-06: a threshold counted in ranks does not transfer between
    # sample sizes.
    rank_shift_review: int = 3
    # Review-ordering weights only. Grid distance is deliberately absent: the
    # project's own argument is that network proximity is too uncertain to act
    # as a score, so it stays a published distance pair plus a verify flag.
    solar_score_weight: float = 0.6
    area_score_weight: float = 0.4


def _overlap_area_m2(sites: gpd.GeoDataFrame, others: gpd.GeoDataFrame) -> pd.Series:
    """Total area each site shares with another layer, in square metres.

    The spatial index finds the candidate pairs and only those pairs are
    intersected, so a national layer is never unioned. Overlapping features in
    ``others`` are counted once each, which can double-count where they overlap
    one another; that errs towards calling an intersection material, which is
    the safe direction for an exclusion rule.
    """
    result = pd.Series(0.0, index=sites.index, dtype=float)
    if sites.empty or others.empty:
        return result
    right = others.geometry.reset_index(drop=True)
    hits = gpd.sjoin(
        sites[["geometry"]],
        gpd.GeoDataFrame(geometry=right, crs=others.crs),
        how="inner", predicate="intersects",
    )
    if hits.empty:
        return result
    matched = gpd.GeoSeries(
        right.to_numpy()[hits["index_right"].to_numpy()], index=hits.index, crs=others.crs
    )
    area = sites.geometry.loc[hits.index].intersection(matched, align=False).area
    summed = area.groupby(level=0).sum()
    result.loc[summed.index] = summed.to_numpy()
    return result


def evaluate_sites(
    sites: gpd.GeoDataFrame,
    conservation: gpd.GeoDataFrame,
    powerlines: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    config: SitingConfig | None = None,
    terrain: pd.DataFrame | None = None,
    water: gpd.GeoDataFrame | None = None,
    coastline: gpd.GeoDataFrame | None = None,
    conservation_parcels: pd.DataFrame | None = None,
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
    # S-04. Asking this question with geometry was the wrong question. LINZ
    # says of Protected Areas that "the boundaries for most protected areas are
    # derived from the Landonline Primary Parcel(s)", so for most of the layer
    # the parcel boundary and the protected-area boundary are two renderings of
    # one line. Intersecting them measures the residual between the renderings:
    # on the 10,684 cadastral units, 1,103 of 1,473 hits overlapped by 1 m2 or
    # less and 771 units were quarantined on that alone.
    #
    # LINZ publishes the answer instead. Table 3561 associates each protected
    # area with the parcels it is made of, so where a unit carries its parcel
    # id the rule is an identity test and no threshold is needed. It is "most"
    # and not "all", so protected areas with no association row - marine areas,
    # and areas not defined from the cadastre - still need geometry, and those
    # get the material-overlap test against the sub-metre band that two
    # renderings of one boundary can differ by. Every unit records which path
    # decided it in ``s04_basis``.
    identity_excluded = pd.Series(False, index=out.index)
    identity_available = (
        conservation_parcels is not None
        and "parcel_id" in out.columns
        and "parcel_id" in getattr(conservation_parcels, "columns", [])
    )
    geometric_layer = conservation
    if identity_available:
        protected_parcels = set(
            pd.to_numeric(conservation_parcels["parcel_id"], errors="coerce").dropna().astype("int64")
        )
        identity_excluded = pd.to_numeric(out["parcel_id"], errors="coerce").isin(protected_parcels)
        if "napalis_id" in conservation.columns and "napalis_id" in conservation_parcels.columns:
            associated = set(
                pd.to_numeric(conservation_parcels["napalis_id"], errors="coerce").dropna().astype("int64")
            )
            geometric_layer = conservation.loc[
                ~pd.to_numeric(conservation["napalis_id"], errors="coerce").isin(associated)
            ]
    conservation_overlap_m2 = _overlap_area_m2(out, geometric_layer)
    conservation_band_m2 = out.geometry.map(
        lambda geometry: overlap_noise_band_m2(geometry, cfg.conservation_overlay_accuracy_m)
    )
    geometric_excluded = conservation_overlap_m2 > conservation_band_m2
    out["conservation_overlap_m2"] = conservation_overlap_m2.round(1)
    out["conservation_noise_band_m2"] = conservation_band_m2.round(1)
    out["S04_pass"] = ~(identity_excluded | geometric_excluded)
    out["s04_basis"] = [
        "+".join(
            name for name, fired in (("association", by_id), ("geometry", by_geometry)) if fired
        )
        for by_id, by_geometry in zip(identity_excluded, geometric_excluded)
    ]
    # The reconciliation the identity join has to survive: how often do the two
    # methods disagree? Geometry here is run against the whole conservation
    # layer, not just the part the table does not cover, so the comparison is
    # like for like.
    if identity_available:
        all_overlap = _overlap_area_m2(out, conservation)
        geometry_says = all_overlap > conservation_band_m2
        out.attrs["s04_reconciliation"] = {
            "identity_available": True,
            "agree_excluded": int((identity_excluded & geometry_says).sum()),
            "identity_only": int((identity_excluded & ~geometry_says).sum()),
            "geometry_only": int((~identity_excluded & geometry_says).sum()),
            "agree_clear": int((~identity_excluded & ~geometry_says).sum()),
            "protected_areas_without_association": int(len(geometric_layer)),
        }
    else:
        out.attrs["s04_reconciliation"] = {"identity_available": False}
    out["solar_kwh_m2"] = solar
    out["luc_class"] = luc
    # S-05. The flag is a coverage question, not a point question: how much of
    # this unit is LUC 1-3, against how much of it the LUC layer cannot place.
    # The band is this unit's own, ``accuracy x perimeter / area``, so a long
    # thin unit is held to a weaker claim than a compact one - a 20 ha square
    # has a band near 29%, and a coverage fraction under its own band is not
    # distinguishable from zero. ``hpl_fraction`` is an overlay result and
    # arrives as a column, the same way slope does, so this module needs no LUC
    # layer. Without it the rule falls back to the single dominant class and
    # says so, which is what the demo fixtures use.
    luc_band = (
        out.geometry.map(
            lambda geometry: overlap_noise_band_m2(geometry, cfg.luc_overlay_accuracy_m)
        )
        / out.geometry.area
    )
    out["luc_noise_band"] = luc_band.round(4)
    if "hpl_fraction" in sites.columns:
        hpl_fraction = pd.to_numeric(sites["hpl_fraction"], errors="coerce")
        out["hpl_fraction"] = hpl_fraction.round(4)
        out["S05_hpl_flag"] = hpl_fraction > luc_band
        out["s05_basis"] = "coverage_fraction"
    else:
        out["hpl_fraction"] = np.nan
        out["S05_hpl_flag"] = out["luc_class"].isin([1, 2, 3])
        out["s05_basis"] = "dominant_class"
    out = add_grid_proxies(out, powerlines, roads, cfg)

    # S-08 slope. The value is precomputed into a per-site table, so a missing
    # row is a gap in the inputs rather than a property of the land: it must not
    # read as "this site is flat".
    supplied_column = "mean_slope_deg" in sites.columns
    if terrain is not None:
        if "site_id" not in terrain.columns or "mean_slope_deg" not in terrain.columns:
            raise ValueError("terrain must carry site_id and mean_slope_deg")
        # The table is keyed on site_id, and two rows for one site disagree
        # about the land. Keeping the first meant the answer depended on the
        # order the rows happened to sit in the file - and a slope that decides
        # an exclusion must not be decided by that. The producing script
        # already refuses a duplicated site_id on the way in; this refuses one
        # on the way out, which is where two tables concatenated by hand arrive.
        duplicated = terrain["site_id"].astype(str).duplicated(keep=False)
        if duplicated.any():
            example = terrain.loc[duplicated, "site_id"].iloc[0]
            raise ValueError(
                f"terrain has {int(duplicated.sum())} rows sharing a site_id, first "
                f"{example!r}. The table is keyed on site_id, so a duplicate makes the "
                "screened slope depend on row order; de-duplicate it before screening."
            )
        if supplied_column:
            raise ValueError(
                "mean_slope_deg is present on sites and a terrain table was also given; "
                "pass one or the other so it is unambiguous which slope was screened"
            )
        slope = pd.to_numeric(
            out["site_id"].map(terrain.set_index("site_id")["mean_slope_deg"]),
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
        "S05_hpl_flag", "s05_basis", "hpl_fraction", "luc_noise_band",
        "s04_basis", "conservation_overlap_m2", "conservation_noise_band_m2",
        "S06_verify_grid", "S08_verify_slope", "S10_coastal_flag",
    ]].copy()
    audit.attrs["s04_reconciliation"] = out.attrs["s04_reconciliation"]
    return out, audit
