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
) -> pd.DataFrame:
    """Create a normalized fixed-tilt proxy; timestamps are NZ standard-time labels.

    This is not irradiance simulation. It uses positive solar elevation, then scales
    the annual mean to the named capacity-factor assumption.
    """
    periods = int((pd.Timestamp(year + 1, 1, 1) - pd.Timestamp(year, 1, 1)).days * 1440 / timestep_minutes)
    index = pd.date_range(f"{year}-01-01", periods=periods, freq=f"{timestep_minutes}min")
    day = index.dayofyear.to_numpy()
    clock_hour = index.hour.to_numpy() + index.minute.to_numpy() / 60.0
    lat = math.radians(latitude_deg)
    dec = _declination(day)
    hour_angle = np.deg2rad(15.0 * (clock_hour - 12.0))
    sine_elevation = np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(hour_angle)
    raw = np.clip(sine_elevation, 0.0, None) ** 1.15
    output = raw * (target_capacity_factor / raw.mean())
    return pd.DataFrame({"timestamp": index, "output_pu": output})


def capacity_factor_sensitivity(year: int, factors: list[float], latitude_deg: float) -> pd.DataFrame:
    records = []
    for factor in factors:
        shape = half_hour_shape(year, latitude_deg, factor)
        records.append({"capacity_factor": factor, "realised_mean": shape["output_pu"].mean()})
    return pd.DataFrame(records)

