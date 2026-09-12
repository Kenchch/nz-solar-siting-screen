import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from nz_solar_siting.grid_distance import nearest_distance_m


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


def test_empty_network_returns_infinity():
    sites = gpd.GeoDataFrame(geometry=[Point(100, 50)], crs="EPSG:2193")
    network = gpd.GeoDataFrame(geometry=[], crs="EPSG:2193")
    assert nearest_distance_m(sites, network).iloc[0] == float("inf")
