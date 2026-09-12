"""Grid-distance implementation A and road-proxy implementation B."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

from .load import assert_nztm


def nearest_distance_m(sites: gpd.GeoDataFrame, network: gpd.GeoDataFrame) -> pd.Series:
    assert_nztm(sites, "sites")
    assert_nztm(network, "network")
    if network.empty:
        return pd.Series(np.inf, index=sites.index, dtype=float)
    merged = unary_union(network.geometry.tolist())
    return sites.geometry.map(lambda geom: float(geom.distance(merged)))


def add_grid_proxies(
    sites: gpd.GeoDataFrame,
    powerlines: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    out = sites.copy()
    out["grid_line_m"] = nearest_distance_m(out, powerlines).round(1)
    out["road_proxy_m"] = nearest_distance_m(out, roads).round(1)
    out["grid_rank"] = out["grid_line_m"].rank(method="min").astype(int)
    out["road_rank"] = out["road_proxy_m"].rank(method="min").astype(int)
    out["rank_shift"] = (out["grid_rank"] - out["road_rank"]).abs()
    return out


def compare_top_n(frame: pd.DataFrame, n: int = 10) -> dict[str, object]:
    n = min(n, len(frame))
    grid = set(frame.nsmallest(n, "grid_line_m")["site_id"].astype(str))
    road = set(frame.nsmallest(n, "road_proxy_m")["site_id"].astype(str))
    overlap = grid & road
    return {
        "n": n,
        "overlap_count": len(overlap),
        "non_overlap_count": len(grid | road) - len(overlap),
        "jaccard": round(len(overlap) / len(grid | road), 3) if grid or road else 1.0,
        "grid_only": sorted(grid - road),
        "road_only": sorted(road - grid),
    }

