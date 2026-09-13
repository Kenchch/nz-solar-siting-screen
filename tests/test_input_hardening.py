"""Inputs that are wrong in a way the code used to absorb silently."""

import math
from dataclasses import replace
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, box

from nz_solar_siting.config import resolve_output_directory
from nz_solar_siting.siting import SitingConfig, evaluate_sites

ROOT = Path(__file__).resolve().parents[1]
X, Y = 1_500_000.0, 5_150_000.0
EMPTY = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:2193")
NETWORK = gpd.GeoDataFrame(
    {"n": [1]},
    geometry=gpd.GeoSeries.from_wkt([f"LINESTRING({X} {Y - 200}, {X + 30000} {Y - 200})"]),
    crs="EPSG:2193",
)


def _sites(geometry, **extra) -> gpd.GeoDataFrame:
    frame = gpd.GeoDataFrame(
        {"site_id": ["A"], "lcdb_class": ["Short-rotation Cropland"],
         "luc_class": [3], "solar_kwh_m2": [1400.0], **extra},
        geometry=[geometry], crs="EPSG:2193",
    )
    return frame


def test_a_multipart_site_is_refused_because_area_is_a_contiguity_rule():
    """Two 10 ha squares 5 km apart summed to 20 ha and passed S-01 and S-02."""
    far_apart = MultiPolygon([box(X, Y, X + 320, Y + 320), box(X + 5000, Y, X + 5320, Y + 320)])
    with pytest.raises(ValueError, match="MultiPolygon"):
        evaluate_sites(_sites(far_apart), EMPTY, NETWORK, NETWORK)


def test_the_refusal_names_the_remedy():
    multi = MultiPolygon([box(X, Y, X + 320, Y + 320), box(X + 5000, Y, X + 5320, Y + 320)])
    with pytest.raises(ValueError, match="explode"):
        evaluate_sites(_sites(multi), EMPTY, NETWORK, NETWORK)


def test_area_is_compared_before_it_is_rounded():
    """19.998 ha rounds to 20.00 and used to clear a 20 ha threshold."""
    side = math.sqrt(19.998 * 10_000)
    results, _ = evaluate_sites(_sites(box(X, Y, X + side, Y + side)), EMPTY, NETWORK, NETWORK)
    assert results["area_ha"].iloc[0] == 20.0, "still rounded for publication"
    assert not bool(results["S01_pass"].iloc[0]), "but compared on the measurement"
    assert results["status"].iloc[0] == "quarantine"


def test_a_slope_column_already_on_sites_is_used_not_discarded():
    """It used to be overwritten with NaN, so a 30 degree site stayed a candidate."""
    side = math.sqrt(50 * 10_000)
    sites = _sites(box(X, Y, X + side, Y + side), mean_slope_deg=[30.0])
    results, _ = evaluate_sites(sites, EMPTY, NETWORK, NETWORK)
    assert results["mean_slope_deg"].iloc[0] == 30.0
    assert not bool(results["S08_pass"].iloc[0])
    assert results["status"].iloc[0] == "quarantine"
    assert "S-08" not in str(results["rules_not_applied"].iloc[0])
    assert not bool(results["S08_verify_slope"].iloc[0])


def test_supplying_slope_twice_is_an_error_rather_than_a_silent_winner():
    side = math.sqrt(50 * 10_000)
    sites = _sites(box(X, Y, X + side, Y + side), mean_slope_deg=[2.0])
    terrain = pd.DataFrame({"site_id": ["A"], "mean_slope_deg": [30.0]})
    with pytest.raises(ValueError, match="one or the other"):
        evaluate_sites(sites, EMPTY, NETWORK, NETWORK, terrain=terrain)


@pytest.mark.parametrize("candidate", ["src", "data", ".", "outputs", "../elsewhere", "tests"])
def test_only_directories_under_outputs_can_be_deleted_and_rewritten(candidate: str):
    """The old guard allowed --output src, which reached rmtree."""
    with pytest.raises(ValueError, match="inside outputs/"):
        resolve_output_directory(candidate, ROOT)


@pytest.mark.parametrize("candidate", ["outputs/demo", "outputs/osm", "outputs/real"])
def test_the_real_output_directories_are_still_allowed(candidate: str):
    assert resolve_output_directory(candidate, ROOT).is_relative_to(ROOT / "outputs")


def test_the_terrain_table_pools_samples_across_dem_tiles():
    """A polygon on a tile boundary must be averaged over all of itself."""
    terrain = pd.read_csv(ROOT / "data" / "derived" / "osm" / "site_terrain.csv")
    assert "dem_tiles_used" in terrain.columns
    assert terrain["site_id"].is_unique
    straddling = terrain[terrain["dem_tiles_used"] > 1]
    assert not straddling.empty, "the study area does span more than one tile"
    assert straddling["dem_tile"].str.contains(";").all(), "both tiles must be named"
