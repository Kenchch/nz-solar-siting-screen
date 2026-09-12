"""M2: explicit, assumption-driven half-hour solar production shape."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd


def _declination(day_of_year: np.ndarray) -> np.ndarray:
    return np.deg2rad(23.45 * np.sin(np.deg2rad(360.0 * (284 + day_of_year) / 365.0)))


def _equation_of_time_minutes(day_of_year: np.ndarray) -> np.ndarray:
    """Approximate apparent-solar-time correction for Earth's orbital geometry."""
    angle = np.deg2rad(360.0 * (day_of_year - 81.0) / 365.0)
    return 9.87 * np.sin(2.0 * angle) - 7.53 * np.cos(angle) - 1.5 * np.sin(angle)


def half_hour_shape(
    year: int,
    latitude_deg: float = -43.55,
    target_capacity_factor: float = 0.175,
    timestep_minutes: int = 30,
    timezone: str = "Pacific/Auckland",
    shaping_exponent: float = 1.15,
    longitude_deg: float = 172.45,
    solar_time_basis: str = "apparent_solar",
) -> pd.DataFrame:
    """Create a normalized fixed-tilt proxy on unique UTC market instants.

    The baseline hour angle uses apparent solar time: civil clock time is
    corrected for longitude, the active UTC offset and the equation of time.
    ``civil_clock`` remains available only to quantify the former model error.
    """
    if shaping_exponent <= 0:
        raise ValueError("shaping_exponent must be positive")
    if solar_time_basis not in {"apparent_solar", "civil_clock"}:
        raise ValueError("solar_time_basis must be 'apparent_solar' or 'civil_clock'")
    start = pd.Timestamp(year, 1, 1, tz=timezone).tz_convert("UTC")
    stop = pd.Timestamp(year + 1, 1, 1, tz=timezone).tz_convert("UTC")
    index_utc = pd.date_range(start, stop, freq=f"{timestep_minutes}min", inclusive="left")
    local = index_utc.tz_convert(timezone)
    day = local.dayofyear.to_numpy()
    clock_hour = local.hour.to_numpy() + local.minute.to_numpy() / 60.0
    if solar_time_basis == "apparent_solar":
        local_naive = local.tz_localize(None)
        utc_naive = index_utc.tz_localize(None)
        utc_offset_hours = (local_naive - utc_naive) / pd.Timedelta(hours=1)
        standard_meridian_deg = 15.0 * np.asarray(utc_offset_hours, dtype=float)
        correction_minutes = (
            4.0 * (longitude_deg - standard_meridian_deg)
            + _equation_of_time_minutes(day)
        )
        solar_hour = clock_hour + correction_minutes / 60.0
    else:
        solar_hour = clock_hour
    lat = math.radians(latitude_deg)
    dec = _declination(day)
    hour_angle = np.deg2rad(15.0 * (solar_hour - 12.0))
    sine_elevation = np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(hour_angle)
    raw = np.clip(sine_elevation, 0.0, None) ** shaping_exponent
    output = raw * (target_capacity_factor / raw.mean())
    return pd.DataFrame({"timestamp_utc": index_utc, "output_pu": output})
