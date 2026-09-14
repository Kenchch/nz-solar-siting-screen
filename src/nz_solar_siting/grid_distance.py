"""Network distance proxies, tiered by voltage.

"Distance to the grid" has no single meaning, so this module refuses to pretend
it does. Where the powerline layer carries a voltage attribute, distances are
computed per voltage tier and ``grid_line_m`` is the distance to the tier a
project could actually connect at. Where it does not, ``grid_line_m`` falls back
to the whole layer and ``grid_basis`` records that, because a screen should say
which question it answered.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd

from .load import assert_nztm


def max_voltage_v(label: object) -> float:
    """Highest voltage on a line, in volts.

    Publishers record shared structures as semicolon lists such as
    ``66000;11000``: one set of poles carrying a 66 kV circuit and an 11 kV
    circuit. The highest circuit present decides which part of the network the
    line belongs to. Returns NaN when untagged, which is reported rather than
    guessed at.
    """
    if isinstance(label, (int, float)) and not isinstance(label, bool):
        return float(label) if np.isfinite(label) else float("nan")
    if not isinstance(label, str):
        return float("nan")
    values = []
    for part in label.replace(",", ";").split(";"):
        try:
            values.append(float(part.strip()))
        except ValueError:
            continue
    return max(values) if values else float("nan")


def split_by_voltage(
    powerlines: gpd.GeoDataFrame,
    tiers: Sequence,
    excluded_voltage_v: float | None = None,
    voltage_column: str = "voltage",
) -> tuple[dict[str, gpd.GeoDataFrame], dict[str, int]]:
    """Split power lines into voltage tiers rather than into publisher tags.

    A publisher's own categories do not separate the network the way a
    connection decision does: the same 66 kV circuit appears under more than one
    tag, and a 220 kV circuit is not interchangeable with it for a project of
    tens of megawatts. Untagged lines are reported rather than silently
    assigned, and anything at or above ``excluded_voltage_v`` is dropped.
    """
    voltage = powerlines[voltage_column].map(max_voltage_v)
    tagged = voltage.notna()
    excluded = (
        tagged & (voltage >= excluded_voltage_v)
        if excluded_voltage_v is not None
        else pd.Series(False, index=powerlines.index)
    )
    split: dict[str, gpd.GeoDataFrame] = {}
    for tier in tiers:
        name = tier["name"] if isinstance(tier, Mapping) else tier.name
        low = float(tier["minimum_v"] if isinstance(tier, Mapping) else tier.minimum_v)
        high = float(tier["maximum_v"] if isinstance(tier, Mapping) else tier.maximum_v)
        selected = tagged & ~excluded & (voltage >= low) & (voltage <= high)
        split[name] = powerlines.loc[selected]
    counts = {
        "untagged_voltage": int((~tagged).sum()),
        "excluded_above_threshold": int(excluded.sum()),
        **{name: int(len(frame)) for name, frame in split.items()},
    }
    if sum(counts.values()) != len(powerlines):
        raise ValueError("voltage tiers must partition the network exactly once")
    return split, counts


def nearest_distance_m(sites: gpd.GeoDataFrame, network: gpd.GeoDataFrame) -> pd.Series:
    """Distance from each site to the nearest network feature, in metres.

    An empty network yields NaN, not infinity. The absence of a mapped line is
    an unknown distance, and treating unknown as "infinitely far" would rank a
    site last on the strength of missing data instead of flagging it for review.

    Rows are matched back by position, not by index label. The join emits one
    row per nearest neighbour and has to be collapsed per site; collapsing on
    the index label silently merges sites that happen to share one, and every
    site in that group then reports the nearest distance any of them had. A
    duplicated index is not exotic - ``GeoDataFrame.explode(index_parts=False)``,
    the very call the screen tells a caller to make on multipart input, leaves
    one behind.
    """
    assert_nztm(sites, "sites")
    assert_nztm(network, "network")
    if sites.empty:
        return pd.Series(index=sites.index, dtype=float)
    if network.empty:
        return pd.Series(np.nan, index=sites.index, dtype=float)
    positional = sites[["geometry"]].reset_index(drop=True)
    joined = gpd.sjoin_nearest(
        positional, network[["geometry"]], how="left", distance_col="_distance_m"
    )
    distances = joined.groupby(level=0)["_distance_m"].min().reindex(range(len(positional)))
    return pd.Series(distances.to_numpy(dtype=float), index=sites.index)


def add_grid_proxies(
    sites: gpd.GeoDataFrame,
    powerlines: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    config=None,
) -> gpd.GeoDataFrame:
    """Attach network distances, tiered by voltage where the data allows it."""
    out = sites.copy()
    tiers = tuple(getattr(config, "voltage_tiers", ()) or ())
    column = getattr(config, "voltage_column", "voltage")
    tiered = bool(tiers) and column in powerlines.columns and not powerlines.empty
    if tiered:
        split, _ = split_by_voltage(
            powerlines, tiers, getattr(config, "excluded_voltage_v", None), column
        )
        for name, network in split.items():
            out[f"{name}_m"] = nearest_distance_m(out, network).round(1)
        connection = getattr(config, "connection_tier", None)
        if connection not in split:
            raise ValueError(f"connection_tier {connection!r} is not one of {sorted(split)}")
        out["grid_line_m"] = out[f"{connection}_m"]
        out["grid_basis"] = connection
    else:
        out["grid_line_m"] = nearest_distance_m(out, powerlines).round(1)
        out["grid_basis"] = "all_mapped_powerlines"
    out["road_proxy_m"] = nearest_distance_m(out, roads).round(1)
    out["grid_rank"] = out["grid_line_m"].rank(method="min").astype("Int64")
    out["road_rank"] = out["road_proxy_m"].rank(method="min").astype("Int64")
    out["rank_shift"] = (out["grid_rank"] - out["road_rank"]).abs().astype("Int64")
    return out


def grid_review_distance_m(config, basis: str | None = None) -> float:
    """The review distance that applies to whatever ``grid_line_m`` measures.

    The threshold has to follow the basis, not the configuration's preference.
    Comparing an all-lines distance against the 33-66 kV threshold would answer
    a question the data did not ask.
    """
    tiers = tuple(getattr(config, "voltage_tiers", ()) or ())
    wanted = basis if basis is not None else getattr(config, "connection_tier", None)
    for tier in tiers:
        if tier.name == wanted:
            return float(tier.review_distance_m)
    return float(config.grid_distance_review_m)


def verify_grid_flag(frame: pd.DataFrame, config) -> pd.Series:
    """S-06: one implementation, used by the screen and by every study.

    The flag is distance to the tier a project could connect at, against that
    tier's own review distance. An unknown distance also flags, because unknown
    is exactly what a human should check. A rank-shift trigger is deliberately
    absent: a threshold expressed in ranks does not survive a change of sample
    size, and the same constant that discriminates across eight fixtures fires
    on every site in a population of thousands. ``rank_shift`` stays published.
    """
    distance = pd.to_numeric(frame["grid_line_m"], errors="coerce")
    basis = None
    if "grid_basis" in frame.columns and len(frame):
        values = set(frame["grid_basis"].dropna().unique())
        if len(values) == 1:
            basis = values.pop()
    review = grid_review_distance_m(config, basis)
    return (distance > review) | distance.isna()


def compare_top_n(frame: pd.DataFrame, n: int = 10) -> dict[str, object]:
    """Overlap between the nearest-N shortlists the two proxies produce.

    A site whose distance could not be measured is not a site that is far away;
    it is a site with no distance, and it cannot be in a nearest-N shortlist.
    ``nsmallest`` keeps NaN rows and orders them last rather than dropping them,
    so an unmeasured site used to fill a shortlist slot - and a run whose
    powerline layer mapped nothing at all published ``jaccard: 1.0``, "the road
    proxy reproduces the grid shortlist exactly", on no measurement at all.
    Unmeasured rows are kept out of both shortlists and counted instead, and an
    empty union reports ``None`` rather than perfect agreement.
    """
    grid_known = pd.to_numeric(frame["grid_line_m"], errors="coerce").notna()
    road_known = pd.to_numeric(frame["road_proxy_m"], errors="coerce").notna()
    n = min(n, len(frame))
    grid = set(frame.loc[grid_known].nsmallest(n, "grid_line_m")["site_id"].astype(str))
    road = set(frame.loc[road_known].nsmallest(n, "road_proxy_m")["site_id"].astype(str))
    overlap = grid & road
    union = grid | road
    return {
        "n": n,
        "grid_distance_unknown": int((~grid_known).sum()),
        "road_distance_unknown": int((~road_known).sum()),
        "overlap_count": len(overlap),
        "non_overlap_count": len(union) - len(overlap),
        "jaccard": round(len(overlap) / len(union), 3) if union else None,
        "grid_only": sorted(grid - road),
        "road_only": sorted(road - grid),
    }
