"""The seasonal/intraday split must be exact and must answer the 'why'."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nz_solar_siting.capture import decompose_capture_rate, yearly_capture_rates
from nz_solar_siting.solar_shape import half_hour_shape

ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "data" / "derived" / "ISL0661_2019_2025.csv.gz"
LOAD = ROOT / "data" / "derived" / "ISL0661_load_2019_2025.csv.gz"


def _shape_and_days(year: int = 2023, tilt_deg: float = 25.0) -> tuple[pd.DataFrame, pd.Series]:
    shape = half_hour_shape(year, tilt_deg=tilt_deg)
    local = shape.timestamp_utc.dt.tz_convert("Pacific/Auckland")
    return shape, local.dt.date


def test_terms_sum_exactly_to_the_capture_rate():
    prices = pd.read_csv(PRICES)
    rates = yearly_capture_rates(prices, tilt_deg=25.0)
    recombined = rates.seasonal_capture_rate + rates.intraday_capture_points
    assert np.allclose(recombined, rates.solar_capture_rate, atol=1e-12)


def test_flat_price_gives_a_unit_seasonal_term_and_no_intraday_term():
    shape, days = _shape_and_days()
    seasonal, intraday = decompose_capture_rate(
        pd.Series(70.0, index=shape.index), shape.output_pu, days
    )
    assert seasonal == pytest.approx(1.0)
    assert intraday == pytest.approx(0.0, abs=1e-12)


def test_a_purely_seasonal_price_signal_lands_in_the_seasonal_term():
    """Constant within each day, high in winter: intraday must stay at zero."""
    shape, days = _shape_and_days()
    month = shape.timestamp_utc.dt.tz_convert("Pacific/Auckland").dt.month
    prices = pd.Series(np.where(month.isin([6, 7, 8]), 300.0, 60.0), index=shape.index)
    seasonal, intraday = decompose_capture_rate(prices, shape.output_pu, days)
    assert seasonal < 0.9
    assert intraday == pytest.approx(0.0, abs=1e-12)


def test_a_midday_price_trough_lands_in_the_intraday_term():
    """A cannibalisation-shaped signal must show up as a negative intraday term."""
    shape, days = _shape_and_days()
    hour = shape.midpoint_utc.dt.tz_convert("Pacific/Auckland").dt.hour
    prices = pd.Series(np.where(hour.between(10, 15), 40.0, 120.0), index=shape.index)
    seasonal, intraday = decompose_capture_rate(prices, shape.output_pu, days)
    assert intraday < -0.2
    assert seasonal == pytest.approx(1.0, abs=0.05)


def test_committed_isl0661_discount_is_seasonal_not_intraday():
    """The published headline: the worst year is a seasonal mismatch."""
    rates = yearly_capture_rates(pd.read_csv(PRICES), tilt_deg=25.0).set_index("year")
    worst = rates.solar_capture_rate.idxmin()
    gap = 1.0 - rates.loc[worst, "solar_capture_rate"]
    seasonal_gap = 1.0 - rates.loc[worst, "seasonal_capture_rate"]
    assert gap > 0.1
    assert seasonal_gap / gap > 0.95
    assert abs(rates.loc[worst, "intraday_capture_points"]) < 0.02


def test_metered_load_control_beats_the_flat_profile_every_year():
    """M3 control group: an evening/winter-peaking shape must capture above 1."""
    rates = yearly_capture_rates(
        pd.read_csv(PRICES), tilt_deg=25.0, load_shape=pd.read_csv(LOAD)
    )
    assert (rates.load_capture_rate > rates.flat_capture_rate).all()
    assert (rates.load_intraday_capture_points > 0).all()
    # Solar beats load in the two years when summer was expensive, so the
    # comparison is made on the period average rather than year by year.
    assert rates.load_capture_rate.mean() > rates.solar_capture_rate.mean()


def test_load_control_must_cover_every_priced_period():
    prices = pd.read_csv(PRICES)
    load = pd.read_csv(LOAD).iloc[100:]
    with pytest.raises(Exception, match="load-control match"):
        yearly_capture_rates(prices, tilt_deg=25.0, load_shape=load)
