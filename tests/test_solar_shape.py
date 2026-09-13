import math

import numpy as np
import pandas as pd
import pytest

from nz_solar_siting.capture import yearly_capture_rates
from nz_solar_siting.solar_shape import cosine_incidence, half_hour_shape


def _winter_priced_year() -> pd.DataFrame:
    """A year whose prices are high in winter, like a dry-year hydro market."""
    shape = half_hour_shape(2023, tilt_deg=0.0)
    month = shape.timestamp_utc.dt.tz_convert("Pacific/Auckland").dt.month
    return pd.DataFrame({
        "timestamp_utc": shape.timestamp_utc,
        "price_nzd_mwh": np.where(month.isin([6, 7, 8]), 400.0, 80.0),
    })


def test_capacity_factor_scaling_remains_an_invariant():
    shape = half_hour_shape(2023, target_capacity_factor=0.21)
    assert shape.output_pu.mean() == pytest.approx(0.21)


def test_shaping_exponent_changes_intraday_profile():
    broad = half_hour_shape(2023, shaping_exponent=1.0)
    sharp = half_hour_shape(2023, shaping_exponent=1.3)
    assert not np.allclose(broad.output_pu, sharp.output_pu)
    assert sharp.output_pu.max() > broad.output_pu.max()


def test_non_positive_shaping_exponent_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        half_hour_shape(2023, shaping_exponent=0)


def _january_peak_midpoint(**options) -> pd.Timestamp:
    shape = half_hour_shape(2023, **options)
    local = shape.midpoint_utc.dt.tz_convert("Pacific/Auckland")
    january = shape.loc[local.dt.month == 1]
    return january.loc[january.output_pu.idxmax(), "midpoint_utc"].tz_convert(
        "Pacific/Auckland"
    )


def test_january_peak_is_between_1300_and_1400_nzdt():
    peak_local = _january_peak_midpoint()
    peak_hour = peak_local.hour + peak_local.minute / 60.0
    assert 13.0 <= peak_hour <= 14.0


def test_civil_clock_comparator_peaks_within_a_half_hour_of_noon():
    peak_local = _january_peak_midpoint(solar_time_basis="civil_clock")
    peak_hour = peak_local.hour + peak_local.minute / 60.0
    assert abs(peak_hour - 12.0) <= 0.25


def test_periods_are_evaluated_at_their_midpoint_not_their_opening():
    shape = half_hour_shape(2023, timestep_minutes=30)
    offsets = shape.midpoint_utc - shape.timestamp_utc
    assert (offsets == pd.Timedelta(minutes=15)).all()


def test_zero_tilt_reproduces_the_horizontal_plane_geometry():
    latitude = math.radians(-43.55)
    declination = np.deg2rad(np.array([-23.0, 0.0, 23.0]))
    sine_elevation = np.array([0.2, 0.6, 0.9])
    horizontal = cosine_incidence(sine_elevation, declination, latitude, 0.0)
    assert np.allclose(horizontal, sine_elevation)


def test_tilt_flattens_the_summer_to_winter_output_ratio():
    def december_over_june(tilt_deg: float) -> float:
        shape = half_hour_shape(2023, tilt_deg=tilt_deg)
        month = shape.midpoint_utc.dt.tz_convert("Pacific/Auckland").dt.month
        monthly = shape.groupby(month).output_pu.sum()
        return monthly.loc[12] / monthly.loc[6]

    horizontal = december_over_june(0.0)
    tilted = december_over_june(25.0)
    steeper = december_over_june(35.0)
    assert horizontal > tilted > steeper
    # A north-facing 25 degree array in Canterbury is roughly 2.5-3x summer to
    # winter; the horizontal proxy overstates that seasonal swing badly.
    assert 2.5 <= tilted <= 3.0
    assert horizontal > 4.0


def test_tilt_outside_the_supported_range_is_rejected():
    with pytest.raises(ValueError, match="tilt_deg"):
        half_hour_shape(2023, tilt_deg=90.0)
    with pytest.raises(ValueError, match="tilt_deg"):
        half_hour_shape(2023, tilt_deg=-1.0)


def test_tilt_raises_the_capture_rate_at_a_winter_priced_node():
    prices = _winter_priced_year()
    horizontal = yearly_capture_rates(prices, tilt_deg=0.0).solar_capture_rate.iloc[0]
    tilted = yearly_capture_rates(prices, tilt_deg=25.0).solar_capture_rate.iloc[0]
    assert tilted > horizontal


def test_capture_rate_is_sensitive_to_shaping_exponent():
    broad = half_hour_shape(2023, shaping_exponent=1.0)
    prices = pd.DataFrame({
        "timestamp_utc": broad.timestamp_utc,
        "price_nzd_mwh": 40.0 + 100.0 * broad.output_pu,
    })
    broad_rate = yearly_capture_rates(prices, shaping_exponent=1.0).solar_capture_rate.iloc[0]
    sharp_rate = yearly_capture_rates(prices, shaping_exponent=1.3).solar_capture_rate.iloc[0]
    assert sharp_rate > broad_rate
    assert sharp_rate - broad_rate > 0.01
