"""M2: explicit, assumption-driven half-hour solar production shape."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd


def _declination(day_of_year: np.ndarray) -> np.ndarray:
    return np.deg2rad(23.45 * np.sin(np.deg2rad(360.0 * (284 + day_of_year) / 365.0)))


def half_hour_shape(
    year: int,
    latitude_deg: float = -43.55,
    target_capacity_factor: float = 0.175,
    timestep_minutes: int = 30,
    timezone: str = "Pacific/Auckland",
    shaping_exponent: float = 1.15,
) -> pd.DataFrame:
    """Create a normalized fixed-tilt proxy on unique UTC market instants."""
    if shaping_exponent <= 0:
        raise ValueError("shaping_exponent must be positive")
    start = pd.Timestamp(year, 1, 1, tz=timezone).tz_convert("UTC")
    stop = pd.Timestamp(year + 1, 1, 1, tz=timezone).tz_convert("UTC")
    index_utc = pd.date_range(start, stop, freq=f"{timestep_minutes}min", inclusive="left")
    local = index_utc.tz_convert(timezone)
    day = local.dayofyear.to_numpy()
    clock_hour = local.hour.to_numpy() + local.minute.to_numpy() / 60.0
    lat = math.radians(latitude_deg)
    dec = _declination(day)
    hour_angle = np.deg2rad(15.0 * (clock_hour - 12.0))
    sine_elevation = np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(hour_angle)
    raw = np.clip(sine_elevation, 0.0, None) ** shaping_exponent
    output = raw * (target_capacity_factor / raw.mean())
    return pd.DataFrame({"timestamp_utc": index_utc, "output_pu": output})
