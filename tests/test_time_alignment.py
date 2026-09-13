from pathlib import Path

import pandas as pd
import pytest

from nz_solar_siting.capture import (
    CaptureAlignmentError,
    read_ea_price_csv,
    trading_period_timestamps,
    yearly_capture_rates,
)
from nz_solar_siting.solar_shape import half_hour_shape

ROOT = Path(__file__).resolve().parents[1]


def _market_day(date: str, count: int) -> pd.Series:
    return trading_period_timestamps(
        pd.Series([date] * count), pd.Series(range(1, count + 1))
    )


def test_standard_market_day_has_48_unique_instants():
    timestamps = _market_day("2023-07-12", 48)
    assert len(timestamps) == 48
    assert timestamps.is_unique


def test_spring_forward_day_has_46_periods_and_no_0200_hour():
    timestamps = _market_day("2023-09-24", 46)
    local = timestamps.dt.tz_convert("Pacific/Auckland")
    assert len(timestamps) == 46
    assert timestamps.is_unique
    assert not (local.dt.hour == 2).any()


def test_autumn_fallback_day_has_50_unique_instants():
    timestamps = _market_day("2023-04-02", 50)
    local = timestamps.dt.tz_convert("Pacific/Auckland")
    wall_clock = local.dt.strftime("%Y-%m-%d %H:%M")
    assert len(timestamps) == 50
    assert timestamps.is_unique
    assert wall_clock.duplicated(keep=False).sum() == 4


def test_trading_periods_are_consecutive_in_utc_across_dst():
    for date, count in (("2023-04-02", 50), ("2023-09-24", 46)):
        elapsed = _market_day(date, count).diff().dropna()
        assert (elapsed == pd.Timedelta(minutes=30)).all()


def test_a_period_beyond_the_day_is_rejected_against_that_day_length():
    """46, 48 or 50, depending on the day - not a blanket 1 to 50.

    A blanket range let period 49 through on an ordinary day, where it converts
    to the next day's midnight and collides with that day's period 1 - or, on
    the last day in a file, silently invents an instant that nothing catches.
    """
    with pytest.raises(ValueError, match="does not exist on 2023-01-01"):
        trading_period_timestamps(pd.Series(["2023-01-01"]), pd.Series([51]))
    with pytest.raises(ValueError, match="which has 48 half-hour periods"):
        trading_period_timestamps(pd.Series(["2023-07-12"]), pd.Series([49]))
    with pytest.raises(ValueError, match="which has 46 half-hour periods"):
        trading_period_timestamps(pd.Series(["2023-09-24"]), pd.Series([47]))
    # The long day really does have 50, and the short day really does have 46.
    assert len(trading_period_timestamps(pd.Series(["2023-04-02"]), pd.Series([50]))) == 1
    assert len(trading_period_timestamps(pd.Series(["2023-09-24"]), pd.Series([46]))) == 1


def test_a_fractional_trading_period_is_rejected_not_truncated():
    """astype(int) turned 1.9 into period 1 without a word."""
    with pytest.raises(ValueError, match="whole numbers"):
        trading_period_timestamps(pd.Series(["2023-07-12"]), pd.Series([1.9]))


def test_a_period_below_one_is_rejected():
    with pytest.raises(ValueError, match="1 or greater"):
        trading_period_timestamps(pd.Series(["2023-07-12"]), pd.Series([0]))


def test_solar_shape_uses_unique_utc_instants():
    shape = half_hour_shape(2023)
    assert len(shape) == 17_520
    assert shape.timestamp_utc.is_unique
    assert str(shape.timestamp_utc.dtype) == "datetime64[us, UTC]"


def test_yearly_merge_preserves_every_input_row():
    shape = half_hour_shape(2023)
    prices = pd.DataFrame({
        "timestamp_utc": shape.timestamp_utc.iloc[::7],
        "price_nzd_mwh": 50.0 + shape.output_pu.iloc[::7].to_numpy(),
    })
    result = yearly_capture_rates(prices)
    assert result.loc[0, "observations"] == len(prices)
    assert not bool(result.loc[0, "complete_year"])


def test_yearly_capture_rejects_nonfinite_prices():
    shape = half_hour_shape(2023).iloc[:2]
    prices = pd.DataFrame({
        "timestamp_utc": shape.timestamp_utc,
        "price_nzd_mwh": [50.0, float("nan")],
    })
    with pytest.raises(ValueError, match="non-finite"):
        yearly_capture_rates(prices)


def test_market_year_observation_totals_reconcile_to_all_input_rows():
    frames = []
    for year in (2019, 2020):
        shape = half_hour_shape(year).iloc[400:800]
        frames.append(pd.DataFrame({
            "timestamp_utc": shape.timestamp_utc,
            "price_nzd_mwh": 50.0 + shape.output_pu.to_numpy(),
        }))
    prices = pd.concat(frames, ignore_index=True)
    result = yearly_capture_rates(prices)
    assert result.observations.sum() == len(prices)


def test_committed_price_rows_reconcile_utc_and_nz_market_years():
    prices = pd.read_csv(ROOT / "data/derived/ISL0661_2019_2025.csv.gz")
    timestamp = pd.to_datetime(prices.timestamp_utc, utc=True)
    utc_counts = prices.groupby(timestamp.dt.year).size()
    market_counts = prices.groupby(
        timestamp.dt.tz_convert("Pacific/Auckland").dt.year
    ).size()
    assert utc_counts.loc[2018] == 26
    assert utc_counts.loc[2025] == 17_446
    assert market_counts.loc[2019] == 17_520
    assert market_counts.loc[2025] == 17_472
    assert market_counts.sum() == len(prices)


def test_duplicate_price_timestamp_is_rejected():
    shape = half_hour_shape(2023).iloc[1000:1010]
    prices = pd.DataFrame({"timestamp_utc": shape.timestamp_utc, "price_nzd_mwh": 50.0})
    prices = pd.concat([prices, prices.iloc[[0]]], ignore_index=True)
    with pytest.raises(CaptureAlignmentError, match="duplicate price timestamp"):
        yearly_capture_rates(prices)


def test_timezone_naive_price_timestamp_is_rejected():
    prices = pd.DataFrame({"timestamp_utc": ["2023-01-01T12:00:00"], "price_nzd_mwh": [50.0]})
    with pytest.raises(CaptureAlignmentError, match="UTC offset"):
        yearly_capture_rates(prices)


def test_unmatched_half_hour_is_rejected():
    prices = pd.DataFrame({"timestamp_utc": ["2023-01-01T00:00:15Z"], "price_nzd_mwh": [50.0]})
    with pytest.raises(CaptureAlignmentError, match="no production-shape match"):
        yearly_capture_rates(prices)


def test_ea_reader_builds_distinct_fallback_instants(tmp_path):
    source = tmp_path / "ea.csv"
    pd.DataFrame({
        "TradingDate": ["2023-04-02", "2023-04-02"],
        "TradingPeriod": [5, 7],
        "PointOfConnection": ["ISL0661", "ISL0661"],
        "DollarsPerMegawattHour": [149.0, 501.0],
    }).to_csv(source, index=False)
    result = read_ea_price_csv(str(source), "ISL0661")
    assert result.timestamp_utc.is_unique
    assert result.timestamp_utc.diff().iloc[1] == pd.Timedelta(hours=1)
    local = result.timestamp_utc.dt.tz_convert("Pacific/Auckland")
    assert local.dt.strftime("%H:%M").nunique() == 1
