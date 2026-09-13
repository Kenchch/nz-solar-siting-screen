"""Input loading with fail-fast CRS and schema checks."""

from __future__ import annotations

import gzip
from io import BytesIO
from pathlib import Path
from typing import Iterable

import geopandas as gpd

EXPECTED_EPSG = 2193


class InputValidationError(ValueError):
    """Raised when an input cannot support metric screening."""


def assert_nztm(frame: gpd.GeoDataFrame, name: str = "layer") -> None:
    if frame.crs is None:
        raise InputValidationError(f"{name}: CRS is missing; expected EPSG:{EXPECTED_EPSG}")
    if frame.crs.to_epsg() != EXPECTED_EPSG:
        raise InputValidationError(
            f"{name}: CRS is {frame.crs}; expected EPSG:{EXPECTED_EPSG} for area and distance"
        )
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise InputValidationError(f"{name}: contains missing or empty geometry")
    if (~frame.geometry.is_valid).any():
        raise InputValidationError(f"{name}: contains invalid geometry")


def read_layer(
    path: str | Path,
    required_columns: Iterable[str] = (),
    name: str = "layer",
    layer: str | None = None,
) -> gpd.GeoDataFrame:
    """Read a vector layer, transparently handling the gzipped GeoJSON this
    project already commits. Without this a caller has to know which of its own
    layers are compressed, which is a detail the format should carry.
    """
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rb") as handle:
            frame = gpd.read_file(BytesIO(handle.read()), layer=layer)
    else:
        frame = gpd.read_file(source, layer=layer)
    assert_nztm(frame, name)
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        raise InputValidationError(f"{name}: missing columns {', '.join(missing)}")
    return frame

