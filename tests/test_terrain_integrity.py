"""A derived table has to prove it describes the geometry being screened.

``site_terrain.csv`` carries a slope that decides S-08, joined on ``site_id``.
The identifier is stable by design, which is exactly the problem: a reissued
parcel can keep its id and move its boundary, and a slope averaged over the old
outline would then be screened against the new one with nothing to notice. The
digest travels with the value so the join can be checked.
"""

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from nz_solar_siting.geometry import geometry_sha256
from nz_solar_siting.siting import evaluate_sites

ROOT = Path(__file__).resolve().parents[1]
X, Y = 1_500_000.0, 5_150_000.0
SIDE = math.sqrt(50 * 10_000)
EMPTY = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:2193")
NETWORK = gpd.GeoDataFrame(
    {"n": [1]},
    geometry=gpd.GeoSeries.from_wkt([f"LINESTRING({X} {Y - 200}, {X + 30000} {Y - 200})"]),
    crs="EPSG:2193",
)
SHAPE = box(X, Y, X + SIDE, Y + SIDE)


def _sites(geometry=SHAPE, **extra) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"site_id": ["A"], "lcdb_class": ["Short-rotation Cropland"],
         "luc_class": [3], "solar_kwh_m2": [1400.0], **extra},
        geometry=[geometry], crs="EPSG:2193",
    )


def _terrain(slope=2.0, digest=None) -> pd.DataFrame:
    frame = pd.DataFrame({"site_id": ["A"], "mean_slope_deg": [slope]})
    if digest is not None:
        frame["geometry_sha256"] = [digest]
    return frame


# ------------------------------------------------------------ the digest

def test_a_digest_that_matches_the_screened_geometry_joins():
    terrain = _terrain(digest=geometry_sha256(SHAPE))
    results, _ = evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK, terrain=terrain)
    assert results["mean_slope_deg"].iloc[0] == 2.0


def test_a_slope_computed_over_different_geometry_is_refused():
    """The id survived a boundary change; the slope behind it did not."""
    reissued = box(X, Y, X + SIDE, Y + SIDE + 40.0)
    terrain = _terrain(slope=2.0, digest=geometry_sha256(SHAPE))
    with pytest.raises(ValueError, match="different geometry"):
        evaluate_sites(_sites(reissued), EMPTY, NETWORK, NETWORK, terrain=terrain)


def test_a_table_without_a_digest_is_still_accepted():
    """The column is opt-in, so a table written before it still screens."""
    results, _ = evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK, terrain=_terrain())
    assert results["mean_slope_deg"].iloc[0] == 2.0


def test_a_change_below_the_digest_precision_does_not_trip_it():
    """Re-reading through another driver must not read as a moved boundary."""
    jittered = box(X, Y, X + SIDE, Y + SIDE + 0.001)
    terrain = _terrain(digest=geometry_sha256(SHAPE))
    results, _ = evaluate_sites(_sites(jittered), EMPTY, NETWORK, NETWORK, terrain=terrain)
    assert results["mean_slope_deg"].iloc[0] == 2.0


def test_the_producer_and_the_screen_agree_on_the_digest():
    """One implementation, imported by both, so they cannot drift apart."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "compute_site_terrain", ROOT / "scripts" / "compute_site_terrain.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.geometry_sha256 is geometry_sha256


# ------------------------------------------------------- the slope value

@pytest.mark.parametrize("slope", [-0.1, 90.5, 1000.0, float("inf"), float("-inf")])
def test_a_slope_that_cannot_be_a_slope_is_refused(slope: float):
    """A radian value, a percentage or a sentinel, silently compared to 10."""
    with pytest.raises(ValueError, match="outside 0-90 degrees"):
        evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK, terrain=_terrain(slope))


@pytest.mark.parametrize("slope", [0.0, 9.9, 10.1, 90.0])
def test_a_slope_inside_the_range_is_screened_normally(slope: float):
    results, _ = evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK, terrain=_terrain(slope))
    assert bool(results["S08_pass"].iloc[0]) == (slope <= 10.0)


def test_an_unknown_slope_is_still_allowed_and_flagged():
    """NaN means the DEM had nothing there, which S-08 reports rather than refuses."""
    results, _ = evaluate_sites(
        _sites(), EMPTY, NETWORK, NETWORK, terrain=_terrain(float("nan"))
    )
    assert bool(results["S08_verify_slope"].iloc[0])
    assert bool(results["S08_pass"].iloc[0]), "unknown is not an exclusion"


# -------------------------------------------------------- LUC coverage

def test_land_the_luc_layer_does_not_reach_is_flagged_for_review():
    """"not highly productive" and "not mapped" are different answers."""
    results, _ = evaluate_sites(
        _sites(hpl_fraction=[0.10], luc_mapped_fraction=[0.20]),
        EMPTY, NETWORK, NETWORK,
    )
    assert bool(results["S05_verify_luc"].iloc[0])
    assert not bool(results["S05_hpl_flag"].iloc[0]), "still not a flag, but not silent"


def test_full_coverage_needs_no_review():
    results, _ = evaluate_sites(
        _sites(hpl_fraction=[0.90], luc_mapped_fraction=[1.0]),
        EMPTY, NETWORK, NETWORK,
    )
    assert not bool(results["S05_verify_luc"].iloc[0])


def test_a_coverage_gap_inside_the_units_own_band_is_not_a_gap():
    """The same registration error already buys this much edge; one threshold."""
    results, _ = evaluate_sites(
        _sites(hpl_fraction=[0.90], luc_mapped_fraction=[0.95]),
        EMPTY, NETWORK, NETWORK,
    )
    band = results["luc_noise_band"].iloc[0]
    assert 1.0 - 0.95 < band
    assert not bool(results["S05_verify_luc"].iloc[0])


def test_a_coverage_fraction_with_no_mapped_share_is_reviewed():
    results, _ = evaluate_sites(_sites(hpl_fraction=[0.9]), EMPTY, NETWORK, NETWORK)
    assert bool(results["S05_verify_luc"].iloc[0])


def test_the_dominant_class_path_has_no_coverage_to_verify():
    results, _ = evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK)
    assert results["s05_basis"].iloc[0] == "dominant_class"
    assert not bool(results["S05_verify_luc"].iloc[0])


def test_the_audit_publishes_the_coverage_columns():
    _, audit = evaluate_sites(
        _sites(hpl_fraction=[0.9], luc_mapped_fraction=[0.4]), EMPTY, NETWORK, NETWORK
    )
    assert {"S05_verify_luc", "luc_mapped_fraction"} <= set(audit.columns)


# ------------------------------------------------- how much was sampled

def _terrain_with_coverage(fraction, slope=2.0) -> pd.DataFrame:
    return pd.DataFrame({
        "site_id": ["A"], "mean_slope_deg": [slope], "sampled_fraction": [fraction],
    })


def test_a_slope_averaged_over_part_of_a_site_is_flagged_for_review():
    """A tile that is ocean returns 404, and the inland half answers for the site."""
    results, _ = evaluate_sites(
        _sites(), EMPTY, NETWORK, NETWORK, terrain=_terrain_with_coverage(0.42)
    )
    assert bool(results["S08_verify_slope"].iloc[0])
    assert results["slope_sampled_fraction"].iloc[0] == 0.42
    assert results["mean_slope_deg"].iloc[0] == 2.0, "the value is still published"


def test_complete_coverage_is_above_one_and_is_not_flagged():
    """Cells count when they touch, so a covered polygon over-samples itself."""
    results, _ = evaluate_sites(
        _sites(), EMPTY, NETWORK, NETWORK, terrain=_terrain_with_coverage(1.11)
    )
    assert not bool(results["S08_verify_slope"].iloc[0])


def test_coverage_short_of_the_threshold_still_excludes_on_a_steep_slope():
    """Unknown coverage is a review flag, not an amnesty for 30 degrees."""
    results, _ = evaluate_sites(
        _sites(), EMPTY, NETWORK, NETWORK,
        terrain=_terrain_with_coverage(0.42, slope=30.0),
    )
    assert not bool(results["S08_pass"].iloc[0])
    assert bool(results["S08_verify_slope"].iloc[0])


def test_a_table_without_the_coverage_column_is_still_accepted():
    results, _ = evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK, terrain=_terrain())
    assert not bool(results["S08_verify_slope"].iloc[0])
    assert pd.isna(results["slope_sampled_fraction"].iloc[0])


def test_the_threshold_is_configurable():
    from dataclasses import replace

    from nz_solar_siting.siting import SitingConfig

    strict = replace(SitingConfig(), minimum_slope_sample_coverage=1.5)
    results, _ = evaluate_sites(
        _sites(), EMPTY, NETWORK, NETWORK, strict, terrain=_terrain_with_coverage(1.11)
    )
    assert bool(results["S08_verify_slope"].iloc[0])


def test_the_committed_terrain_table_would_pass_the_threshold():
    """Every sampled site over-covers itself, which is what makes 0.95 safe.

    The committed table predates the column, so the fraction is recomputed the
    way the producer now writes it: samples x cell area / polygon area, with the
    real 1-arcsecond cell rather than a nominal 30 x 30 m.
    """
    import importlib.util

    from nz_solar_siting.config import load_project_config
    from nz_solar_siting.geometry import area_hectares, has_width_core
    from nz_solar_siting.osm_layers import read_osm_layer

    spec = importlib.util.spec_from_file_location(
        "compute_site_terrain", ROOT / "scripts" / "compute_site_terrain.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    config = load_project_config(ROOT / "config" / "assumptions.yml").siting
    farmland = read_osm_layer("farmland", ROOT / "data" / "derived" / "osm")
    sites = farmland.copy()
    sites["area_ha"] = sites.geometry.map(area_hectares)
    sites = sites.loc[sites["area_ha"] >= config.minimum_area_ha]
    sites = sites.loc[
        sites.geometry.map(lambda g: has_width_core(g, config.minimum_average_width_m))
    ].copy()
    sites["site_id"] = "OSM-" + sites["osm_id"].astype("int64").astype(str)
    sites["area_m2"] = sites.geometry.area

    table = pd.read_csv(ROOT / "data" / "derived" / "osm" / "site_terrain.csv")
    merged = sites[["site_id", "area_m2"]].merge(
        table[["site_id", "slope_samples"]], on="site_id", validate="one_to_one"
    )

    class _Transform:
        a = 1.0 / 3600.0
        e = -1.0 / 3600.0

    cell = module.cell_area_m2(_Transform(), -44.0)
    assert 600.0 < cell < 800.0, "a 1-arcsecond cell here is nowhere near 900 m2"
    fraction = merged["slope_samples"] * cell / merged["area_m2"]
    assert fraction.min() >= 1.0, (
        "touch-based sampling cannot under-count a covered polygon, so a full "
        f"sample sits above 1; lowest was {fraction.min():.3f}"
    )
    assert (fraction >= config.minimum_slope_sample_coverage).all()
