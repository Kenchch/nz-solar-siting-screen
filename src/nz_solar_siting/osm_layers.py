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
from typing import Mapping

import geopandas as gpd
import numpy as np
import pandas as pd

from .load import assert_nztm

DEFAULT_DIRECTORY = Path("data/derived/osm")
LAYER_NAMES = ("farmland", "powerlines", "roads", "wetland", "coastline")


def max_voltage_v(label: object) -> float:
    """Highest voltage on an OSM way, in volts.

    OSM records shared structures as semicolon lists such as ``66000;11000``:
    one set of poles carrying a 66 kV circuit and an 11 kV circuit. The highest
    circuit present decides which part of the network the way belongs to, so a
    ``66000;11000`` way is subtransmission. Returns NaN when untagged.
    """
    if not isinstance(label, str):
        return float("nan")
    values = []
    for part in label.split(";"):
        try:
            values.append(float(part.strip()))
        except ValueError:
            continue
    return max(values) if values else float("nan")


def split_by_voltage(
    powerlines: gpd.GeoDataFrame,
    tiers: Mapping[str, Mapping[str, float]],
    excluded_voltage_v: float | None = None,
) -> tuple[dict[str, gpd.GeoDataFrame], dict[str, int]]:
    """Split power lines into voltage tiers, not into OSM ``power`` tags.

    ``power=line`` and ``power=minor_line`` do not separate the network the way
    a connection decision does: the committed extract has 66 kV ways under both
    tags, and a 220 kV circuit and a 66 kV circuit are not interchangeable for a
    tens-of-megawatts project. Tiering by voltage puts each way where the
    engineering puts it. Untagged ways are reported rather than silently
    assigned, and ``excluded_voltage_v`` and above is dropped outright.
    """
    voltage = powerlines["voltage"].map(max_voltage_v)
    tagged = voltage.notna()
    excluded = tagged & (voltage >= excluded_voltage_v) if excluded_voltage_v else pd.Series(
        False, index=powerlines.index
    )
    split: dict[str, gpd.GeoDataFrame] = {}
    for name, bounds in tiers.items():
        selected = (
            tagged
            & ~excluded
            & (voltage >= float(bounds["minimum_v"]))
            & (voltage <= float(bounds["maximum_v"]))
        )
        split[name] = powerlines.loc[selected]
    counts = {
        "untagged_voltage": int((~tagged).sum()),
        "excluded_above_threshold": int(excluded.sum()),
        **{name: int(len(frame)) for name, frame in split.items()},
    }
    assert np.isclose(
        sum(counts[name] for name in tiers) + counts["untagged_voltage"]
        + counts["excluded_above_threshold"],
        len(powerlines),
    ), "every power line must land in exactly one tier, the excluded set or the untagged set"
    return split, counts


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
