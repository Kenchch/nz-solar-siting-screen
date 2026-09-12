"""Transparent geometry proxies used by screening rules."""

from __future__ import annotations

import math
from shapely.geometry.base import BaseGeometry


def area_hectares(geometry: BaseGeometry) -> float:
    if geometry is None or geometry.is_empty:
        return math.nan
    return float(geometry.area / 10_000.0)


def mean_width_area_perimeter(geometry: BaseGeometry) -> float:
    """Return 2A/P, a conservative compactness-sensitive width proxy."""
    if geometry is None or geometry.is_empty or geometry.length <= 0:
        return math.nan
    return float(2.0 * geometry.area / geometry.length)


def has_width_core(geometry: BaseGeometry, minimum_width_m: float) -> bool:
    """Return whether a negative half-width buffer leaves an interior core."""
    if geometry is None or geometry.is_empty:
        return False
    return not geometry.buffer(-minimum_width_m / 2.0).is_empty

