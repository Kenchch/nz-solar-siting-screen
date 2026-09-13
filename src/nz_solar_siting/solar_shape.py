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


def clear_sky_transmittance(sine_elevation: np.ndarray) -> np.ndarray:
    """Clear-sky beam transmittance from the Kasten-Young relative air mass.

    Low winter sun travels a longer atmospheric path than high summer sun, so
    a purely geometric term cannot carry the seasonal amplitude on its own.
    Relative air mass uses Kasten and Young (1989) and transmittance uses the
    Meinel form ``0.7 ** (air_mass ** 0.678)``. It is a clear-sky proxy: no
    cloud, aerosol, humidity, snow or albedo model is implied.
    """
    elevation_deg = np.degrees(np.arcsin(np.clip(sine_elevation, -1.0, 1.0)))
    lit = sine_elevation > 0.0
    air_mass = np.where(
        lit,
        1.0
        / (
            np.clip(sine_elevation, 1e-6, None)
            + 0.50572 * np.clip(elevation_deg + 6.07995, 1e-6, None) ** -1.6364
        ),
        np.inf,
    )
    return np.where(lit, 0.7 ** (np.clip(air_mass, 0.0, 50.0) ** 0.678), 0.0)


def cosine_incidence(
    sine_elevation: np.ndarray,
    declination: np.ndarray,
    latitude_rad: float,
    tilt_deg: float,
) -> np.ndarray:
    """Cosine of the incidence angle on an equator-facing fixed-tilt plane.

    The array is the beam geometry of a plane tilted ``tilt_deg`` from
    horizontal and facing the equator (due north in the southern hemisphere).
    Substituting the solar azimuth identity
    ``cos(azimuth) = (sin(dec) - sin(elevation) sin(lat)) / (cos(elevation) cos(lat))``
    into ``cos(theta) = cos(tilt) sin(elevation) + sin(tilt) cos(elevation) cos(azimuth)``
    removes the ``cos(elevation)`` division, so the expression stays finite at
    the zenith. ``tilt_deg = 0`` reduces exactly to ``sin(elevation)``, the
    horizontal-plane proxy used before this model carried a tilt assumption.
    """
    tilt = math.radians(tilt_deg)
    return math.cos(tilt) * sine_elevation + math.sin(tilt) * (
        np.sin(declination) - sine_elevation * math.sin(latitude_rad)
    ) / math.cos(latitude_rad)


def half_hour_shape(
    year: int,
    latitude_deg: float = -43.55,
    target_capacity_factor: float = 0.175,
    timestep_minutes: int = 30,
    timezone: str = "Pacific/Auckland",
    shaping_exponent: float = 1.15,
    longitude_deg: float = 172.45,
    solar_time_basis: str = "apparent_solar",
    tilt_deg: float = 25.0,
) -> pd.DataFrame:
    """Create a normalized fixed-tilt proxy on unique UTC market instants.

    Half-hour output is ``cos(incidence on the tilted plane)`` multiplied by a
    clear-sky beam transmittance raised to ``shaping_exponent``. The tilt term
    carries array geometry; the transmittance term carries the atmospheric path
    length that makes winter output weaker than geometry alone would predict.
    ``shaping_exponent`` above 1 concentrates output into high-sun periods and
    stands in for haze and cloud that correlate with low sun; it is the
    documented sensitivity knob, not a fitted parameter.

    Geometry is evaluated at the **midpoint** of each trading period, not at
    its opening instant, so a 30-minute period is not shifted 15 minutes early.
    ``timestamp_utc`` remains the period-opening key used to join prices;
    ``midpoint_utc`` is published beside it so the basis is auditable.

    The baseline hour angle uses apparent solar time: civil clock time is
    corrected for longitude, the active UTC offset and the equation of time.
    ``civil_clock`` remains available only to quantify the former model error.
    """
    if shaping_exponent <= 0:
        raise ValueError("shaping_exponent must be positive")
    if not 0.0 <= tilt_deg < 90.0:
        raise ValueError("tilt_deg must be at least 0 and less than 90 degrees")
    if solar_time_basis not in {"apparent_solar", "civil_clock"}:
        raise ValueError("solar_time_basis must be 'apparent_solar' or 'civil_clock'")
    start = pd.Timestamp(year, 1, 1, tz=timezone).tz_convert("UTC")
    stop = pd.Timestamp(year + 1, 1, 1, tz=timezone).tz_convert("UTC")
    index_utc = pd.date_range(start, stop, freq=f"{timestep_minutes}min", inclusive="left")
    midpoint_utc = index_utc + pd.Timedelta(minutes=timestep_minutes / 2.0)
    local = midpoint_utc.tz_convert(timezone)
    day = local.dayofyear.to_numpy()
    clock_hour = local.hour.to_numpy() + local.minute.to_numpy() / 60.0
    if solar_time_basis == "apparent_solar":
        local_naive = local.tz_localize(None)
        utc_naive = midpoint_utc.tz_localize(None)
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
    geometry = np.clip(
        np.where(sine_elevation > 0.0, cosine_incidence(sine_elevation, dec, lat, tilt_deg), 0.0),
        0.0,
        None,
    )
    raw = geometry * clear_sky_transmittance(sine_elevation) ** shaping_exponent
    output = raw * (target_capacity_factor / raw.mean())
    return pd.DataFrame(
        {"timestamp_utc": index_utc, "midpoint_utc": midpoint_utc, "output_pu": output}
    )
