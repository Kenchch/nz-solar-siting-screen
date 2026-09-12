"""Deterministic NZTM fixtures for reproducible public demonstrations."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, box

CRS = "EPSG:2193"


def build_demo_layers() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    x0, y0 = 1_550_000.0, 5_180_000.0
    classes = [
        "High Producing Exotic Grassland", "Low Producing Grassland", "Short-rotation Cropland",
        "Built-up Area", "High Producing Exotic Grassland", "Indigenous Forest",
        "Low Producing Grassland", "High Producing Exotic Grassland", "Short-rotation Cropland",
        "High Producing Exotic Grassland", "Low Producing Grassland", "Short-rotation Cropland",
    ]
    geometries = []
    for i in range(12):
        col, row = i % 4, i // 4
        width = 650 + (i % 3) * 180
        height = 520 + ((i + 1) % 3) * 160
        if i == 10:
            # Deliberate width-method stress case: a compact 200 m square has
            # an erosion core at 180 m, while 2A/P reports only 100 m.
            width = height = 200
        geometries.append(box(x0 + col * 2600, y0 + row * 2400, x0 + col * 2600 + width, y0 + row * 2400 + height))
    sites = gpd.GeoDataFrame(
        {
            "site_id": [f"DEMO-{i+1:02d}" for i in range(12)],
            "lcdb_class": classes,
            "luc_class": [2, 4, 3, 2, 5, 6, 1, 4, 3, 5, 2, 4],
            "solar_kwh_m2": [1410, 1426, 1435, 1408, 1442, 1420, 1432, 1450, 1418, 1446, 1438, 1429],
        }, geometry=geometries, crs=CRS,
    )
    powerlines = gpd.GeoDataFrame(
        {"network": ["public_line_A", "public_line_B"]},
        geometry=[LineString([(x0 - 500, y0 + 1000), (x0 + 5000, y0 + 7500)]), LineString([(x0 + 9800, y0 - 500), (x0 + 9800, y0 + 7600)])],
        crs=CRS,
    )
    roads = gpd.GeoDataFrame(
        {"network": ["road_proxy_A", "road_proxy_B", "road_proxy_C"]},
        geometry=[LineString([(x0 - 500, y0 + 2100), (x0 + 11000, y0 + 2100)]), LineString([(x0 - 500, y0 + 4700), (x0 + 11000, y0 + 4700)]), LineString([(x0 + 7200, y0 - 500), (x0 + 7200, y0 + 7600)])],
        crs=CRS,
    )
    conservation = gpd.GeoDataFrame(
        {"name": ["DEMO conservation area"]},
        geometry=[box(x0 + 7600, y0 + 4400, x0 + 9000, y0 + 6100)],
        crs=CRS,
    )
    return sites, conservation, powerlines, roads
