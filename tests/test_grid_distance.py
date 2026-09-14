from dataclasses import replace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from nz_solar_siting.grid_distance import (
    add_grid_proxies,
    compare_top_n,
    grid_review_distance_m,
    nearest_distance_m,
    verify_grid_flag,
)
from nz_solar_siting.siting import SitingConfig


def test_known_point_line_distance():
    sites = gpd.GeoDataFrame(geometry=[Point(100, 50)], crs="EPSG:2193")
    network = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (200, 0)])], crs="EPSG:2193")
    assert nearest_distance_m(sites, network).iloc[0] == pytest.approx(50.0)


def test_spatial_join_uses_nearest_of_multiple_lines():
    sites = gpd.GeoDataFrame(geometry=[Point(100, 50)], crs="EPSG:2193")
    network = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (200, 0)]), LineString([(0, 40), (200, 40)])],
        crs="EPSG:2193",
    )
    assert nearest_distance_m(sites, network).iloc[0] == pytest.approx(10.0)


def test_an_empty_network_is_unknown_distance_not_infinite_distance():
    """Missing data must not masquerade as a measurement.

    Infinity would rank the site last on the strength of an absent layer. NaN
    says the distance is unknown, and S-06 turns unknown into a review flag.
    """
    sites = gpd.GeoDataFrame(geometry=[Point(100, 50)], crs="EPSG:2193")
    network = gpd.GeoDataFrame(geometry=[], crs="EPSG:2193")
    distance = nearest_distance_m(sites, network)
    assert pd.isna(distance.iloc[0])


def test_an_unknown_grid_distance_raises_the_verify_flag():
    frame = pd.DataFrame({"grid_line_m": [10.0, float("nan"), 9_999_999.0]})
    flag = verify_grid_flag(frame, SitingConfig())
    assert flag.tolist() == [False, True, True]


def test_the_verify_flag_uses_the_connection_tier_distance():
    """5 km from 33-66 kV, not 20 km from transmission and not the fallback."""
    config = SitingConfig()
    assert grid_review_distance_m(config) == 5000.0
    assert grid_review_distance_m(replace(config, connection_tier="transmission_110kv_plus")) == 20000.0
    assert grid_review_distance_m(replace(config, voltage_tiers=())) == config.grid_distance_review_m


def test_rank_shift_is_published_but_not_part_of_the_flag():
    """The rejected rule must not come back: rank thresholds do not scale."""
    frame = pd.DataFrame({"grid_line_m": [10.0], "rank_shift": [10_000]})
    assert not bool(verify_grid_flag(frame, SitingConfig()).iloc[0])


def test_grid_distance_follows_the_connection_tier_when_voltage_is_present():
    sites = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:2193")
    powerlines = gpd.GeoDataFrame(
        {"voltage": ["220000", "66000", "11000"]},
        geometry=[
            LineString([(-100, 100), (100, 100)]),      # 100 m, transmission
            LineString([(-100, 900), (100, 900)]),      # 900 m, connection tier
            LineString([(-100, 300), (100, 300)]),      # 300 m, distribution
        ],
        crs="EPSG:2193",
    )
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(-100, 50), (100, 50)])], crs="EPSG:2193"
    )
    out = add_grid_proxies(sites, powerlines, roads, SitingConfig())
    assert out["grid_basis"].iloc[0] == "subtransmission_33_66kv"
    assert out["grid_line_m"].iloc[0] == pytest.approx(900.0)
    assert out["transmission_110kv_plus_m"].iloc[0] == pytest.approx(100.0)
    assert out["distribution_22kv_m"].iloc[0] == pytest.approx(300.0)


def test_a_layer_without_voltage_falls_back_and_says_so():
    sites = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:2193")
    network = gpd.GeoDataFrame(
        geometry=[LineString([(-100, 100), (100, 100)])], crs="EPSG:2193"
    )
    out = add_grid_proxies(sites, network, network, SitingConfig())
    assert out["grid_basis"].iloc[0] == "all_mapped_powerlines"
    assert out["grid_line_m"].iloc[0] == pytest.approx(100.0)


def test_sites_sharing_an_index_label_keep_their_own_distances():
    """A duplicated index used to give every site in the group one distance.

    The join emits a row per nearest neighbour and is collapsed per site. On the
    index label that collapse merges distinct sites, and the group's minimum is
    then reported for all of them. ``explode(index_parts=False)`` - the call the
    screen's own multipart refusal recommends - leaves exactly such an index.
    """
    near, far = Point(100, 50), Point(100, 5050)
    sites = gpd.GeoDataFrame(geometry=[near, far], crs="EPSG:2193")
    sites.index = [0, 0]
    network = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (200, 0)])], crs="EPSG:2193")
    assert nearest_distance_m(sites, network).tolist() == pytest.approx([50.0, 5050.0])


def test_exploding_a_multipart_reproduces_the_duplicated_index():
    """The precondition above is what the documented remedy actually produces."""
    from shapely.geometry import MultiPolygon, box

    multi = gpd.GeoDataFrame(
        geometry=[MultiPolygon([box(0, 0, 10, 10), box(0, 5000, 10, 5010)])], crs="EPSG:2193"
    )
    assert not multi.explode(index_parts=False).index.is_unique


def test_an_unmeasured_distance_is_not_a_shortlist_member():
    """A site with no grid distance is not one of the N nearest to the grid.

    ``nsmallest`` orders NaN last but still returns it, so unmeasured sites used
    to fill the shortlist. A run whose powerline layer mapped nothing published
    a perfect overlap between the two proxies on no measurement at all.
    """
    frame = pd.DataFrame({
        "site_id": [f"S{index}" for index in range(5)],
        "grid_line_m": [float("nan")] * 5,
        "road_proxy_m": [1.0, 2.0, 3.0, 4.0, 5.0],
    })
    comparison = compare_top_n(frame, 3)
    assert comparison["grid_distance_unknown"] == 5
    assert comparison["grid_only"] == []
    assert comparison["overlap_count"] == 0
    assert comparison["jaccard"] == 0.0


def test_a_comparison_with_nothing_in_it_is_not_perfect_agreement():
    frame = pd.DataFrame({"site_id": [], "grid_line_m": [], "road_proxy_m": []})
    assert compare_top_n(frame, 3)["jaccard"] is None


def test_a_measured_shortlist_ignores_the_unmeasured_rows_around_it():
    frame = pd.DataFrame({
        "site_id": ["near", "far", "unknown"],
        "grid_line_m": [10.0, 900.0, float("nan")],
        "road_proxy_m": [10.0, 900.0, 5.0],
    })
    comparison = compare_top_n(frame, 2)
    assert comparison["grid_only"] == ["far"]
    assert comparison["road_only"] == ["unknown"]
    assert comparison["grid_distance_unknown"] == 1
    assert comparison["road_distance_unknown"] == 0
