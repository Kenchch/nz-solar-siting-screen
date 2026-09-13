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
from .grid_distance import max_voltage_v, split_by_voltage  # re-exported
from .load import assert_nztm

__all__ = [
    "DEFAULT_DIRECTORY", "LAYER_NAMES", "max_voltage_v", "read_osm_layer",
    "read_osm_layers", "split_by_voltage",
]

DEFAULT_DIRECTORY = Path("data/derived/osm")
LAYER_NAMES = ("farmland", "powerlines", "roads", "wetland", "coastline")


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
) -> tuple[gpd.GeoDataFrame, ...]:
    """Return farmland, powerlines, roads, water/wetland and coastline layers."""
    return tuple(read_osm_layer(name, directory) for name in LAYER_NAMES)
