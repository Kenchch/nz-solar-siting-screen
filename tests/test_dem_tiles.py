"""Every DEM tile a polygon touches has to be fetched, not just two corners.

The slope table is the input to S-08, an exclusion rule. A tile that is never
downloaded is a piece of the polygon that is never sampled, and the mean slope
is then the mean of whatever part happened to be covered - which is the same
class of error as reading one tile for a polygon that straddles two, fixed
earlier by pooling. This is the other half of it: pooling cannot pool a tile
nobody asked for.
"""

import importlib.util
import math
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "compute_site_terrain", ROOT / "scripts" / "compute_site_terrain.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


terrain = _load()


def _bounds(*boxes) -> pd.DataFrame:
    return pd.DataFrame(
        [{"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}
         for minx, miny, maxx, maxy in boxes]
    )


def _diagonal_only(bounds: pd.DataFrame) -> list[tuple[int, int]]:
    """What the previous implementation enumerated: the SW and NE corners."""
    return sorted(
        {(int(math.floor(lat)), int(math.floor(lon)))
         for lat, lon in zip(bounds["miny"], bounds["minx"])}
        | {(int(math.floor(lat)), int(math.floor(lon)))
           for lat, lon in zip(bounds["maxy"], bounds["maxx"])}
    )


def test_a_polygon_inside_one_tile_needs_one_tile():
    assert terrain.required_tiles(_bounds((172.2, -43.6, 172.4, -43.4))) == [(-44, 172)]


def test_crossing_one_tile_line_was_already_right():
    """Only one axis crosses, so the diagonal happened to name both tiles."""
    bounds = _bounds((171.8, -43.6, 172.2, -43.4))
    assert terrain.required_tiles(bounds) == [(-44, 171), (-44, 172)]
    assert terrain.required_tiles(bounds) == _diagonal_only(bounds)


def test_crossing_both_tile_lines_needs_four_tiles_not_two():
    """The bug: a corner in each of four tiles, and only two were named."""
    bounds = _bounds((171.8, -44.2, 172.2, -43.8))
    assert terrain.required_tiles(bounds) == [
        (-45, 171), (-45, 172), (-44, 171), (-44, 172)
    ]
    missed = set(terrain.required_tiles(bounds)) - set(_diagonal_only(bounds))
    assert missed == {(-45, 172), (-44, 171)}, "two tiles were never downloaded"


def test_a_span_wider_than_a_tile_does_not_skip_the_middle():
    bounds = _bounds((170.5, -43.5, 173.5, -43.4))
    assert terrain.required_tiles(bounds) == [
        (-44, 170), (-44, 171), (-44, 172), (-44, 173)
    ]


def test_tiles_from_many_polygons_are_unioned_and_sorted():
    bounds = _bounds(
        (172.2, -43.6, 172.4, -43.4),
        (171.2, -44.6, 171.4, -44.4),
        (172.2, -43.6, 172.4, -43.4),
    )
    assert terrain.required_tiles(bounds) == [(-45, 171), (-44, 172)]


def test_a_polygon_with_no_bounds_is_skipped_rather_than_crashing():
    bounds = _bounds((float("nan"), float("nan"), float("nan"), float("nan")))
    assert terrain.required_tiles(bounds) == []


def test_the_committed_study_area_is_unaffected():
    """The fix is correctness, not a change of result: same tiles, same table."""
    import geopandas as gpd

    from nz_solar_siting.osm_layers import read_osm_layer

    farmland = read_osm_layer("farmland", ROOT / "data" / "derived" / "osm")
    bounds = farmland.to_crs("EPSG:4326").geometry.bounds
    assert terrain.required_tiles(bounds) == _diagonal_only(bounds), (
        "Canterbury parcels against 1 degree tiles never cross both lines, which "
        "is why the committed slope table does not move"
    )
