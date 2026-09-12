import geopandas as gpd
import pytest
from shapely.geometry import Point

from nz_solar_siting.load import InputValidationError, assert_nztm


def test_accepts_nztm():
    assert_nztm(gpd.GeoDataFrame(geometry=[Point(1_500_000, 5_200_000)], crs="EPSG:2193"))


def test_rejects_wgs84():
    with pytest.raises(InputValidationError, match="EPSG:2193"):
        assert_nztm(gpd.GeoDataFrame(geometry=[Point(172.6, -43.5)], crs="EPSG:4326"))

