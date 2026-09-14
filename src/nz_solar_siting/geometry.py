"""Transparent geometry proxies used by screening rules."""

from __future__ import annotations

import hashlib
import math

import shapely
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


def geometry_sha256(geometry: BaseGeometry, precision_m: float = 0.01) -> str:
    """A digest of a polygon's shape, for checking that two tables mean it.

    A derived table keyed on ``site_id`` says nothing about whether the geometry
    behind that id is still the geometry it was computed from. Re-running the
    assembly against a reissued parcel keeps the id stable where the boundary
    moved less than the identifier's own hash resolution, and a slope averaged
    over the old outline would then be attached to the new one without anything
    noticing. The digest travels with the derived value so the join can be
    checked rather than assumed.

    Coordinates are rounded to ``precision_m`` in the text form before hashing,
    so re-reading the same polygon through a different driver does not change
    the digest over floating-point noise. Rounding the text cannot alter the
    topology on the way, which a precision model can.

    This is deliberately not the short hash inside a ``site_id``: that one is an
    identifier and wants to stay readable, this one is an integrity check and
    wants the full digest.

    Known edge: rounding has edges. A coordinate sitting within floating-point
    noise of a rounding boundary - x.xx5 - can round either way between two
    reads of the same file through different drivers, and the digest then
    changes for a polygon that did not move. The failure is a mismatch that
    asks for the terrain table to be rebuilt, never a stale slope accepted as
    current, so the direction is the safe one; a check that cries wolf costs a
    re-run, a check that sleeps costs a wrong exclusion. It also means the
    "sub-millimetre movement is invisible" property holds at a general position
    and not at a rounding boundary.
    """
    if geometry is None or geometry.is_empty:
        return ""
    decimals = max(0, round(-math.log10(precision_m))) if precision_m > 0 else 0
    return hashlib.sha256(
        shapely.to_wkt(geometry, rounding_precision=decimals, trim=True).encode("utf-8")
    ).hexdigest()
