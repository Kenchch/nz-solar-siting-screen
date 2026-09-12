"""Input loading with fail-fast CRS and schema checks."""

from __future__ import annotations

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


def read_layer(
    path: str | Path,
    required_columns: Iterable[str] = (),
    name: str = "layer",
    layer: str | None = None,
) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path, layer=layer)
    assert_nztm(frame, name)
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        raise InputValidationError(f"{name}: missing columns {', '.join(missing)}")
    return frame

