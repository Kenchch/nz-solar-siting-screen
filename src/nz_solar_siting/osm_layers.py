"""Read the committed OpenStreetMap extract used by the grid-distance study.

These layers are an open substitute for LINZ Topo50 powerlines, LINZ road
centrelines and LCDB land cover, which all need portal credentials. They carry
real geometry, so a distance comparison built on them is measured rather than
illustrated - but OSM completeness is uneven, and a mapped ``landuse`` polygon
is a land-use observation, not a parcel title. Attribution: (c) OpenStreetMap
contributors, ODbL.
"""

from __future__ import annotations

import gzip
from io import BytesIO
from pathlib import Path

import geopandas as gpd

from .load import assert_nztm

DEFAULT_DIRECTORY = Path("data/derived/osm")
LAYER_NAMES = ("farmland", "powerlines", "roads")


def read_osm_layer(name: str, directory: str | Path = DEFAULT_DIRECTORY) -> gpd.GeoDataFrame:
    """Read one gzipped GeoJSON layer and refuse anything that is not NZTM."""
    path = Path(directory) / f"{name}.geojson.gz"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run scripts/download_osm_networks.py to rebuild the extract"
        )
    with gzip.open(path, "rb") as handle:
        frame = gpd.read_file(BytesIO(handle.read()))
    assert_nztm(frame, f"osm:{name}")
    return frame


def read_osm_layers(
    directory: str | Path = DEFAULT_DIRECTORY,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return farmland polygons, powerlines and road centrelines."""
    return tuple(read_osm_layer(name, directory) for name in LAYER_NAMES)
