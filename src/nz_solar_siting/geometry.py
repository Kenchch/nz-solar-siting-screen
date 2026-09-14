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


def overlap_noise_band_m2(geometry: BaseGeometry, accuracy_m: float) -> float:
    """Overlap area that a positional error of ``accuracy_m`` can fabricate.

    Two layers drawn from different sources do not agree on where a boundary
    is. A boundary of length ``P`` misregistered by ``eps`` sweeps a band of up
    to ``eps * P`` across whatever lies on the other side of it, and that band
    shows up as an overlap between polygons that do not really overlap. So an
    intersection smaller than ``eps * P`` is indistinguishable from registration
    error, and an intersection larger than it is not.

    ``eps`` is a property of the pair of layers and comes from what the
    publishers say about them, never from the population being screened: see
    ``source_accuracy`` in config/assumptions.yml for the quoted statements.

    The band scales with the boundary, not with the area, which is what makes
    it usable on units that differ by two orders of magnitude in size: a long
    thin unit has more boundary to misregister than a compact one of the same
    area, and it gets a wider band.
    """
    if geometry is None or geometry.is_empty or accuracy_m < 0:
        return math.nan
    return float(accuracy_m * geometry.length)
