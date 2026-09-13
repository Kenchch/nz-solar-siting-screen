"""M3: market-value capture-rate calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .solar_shape import half_hour_shape


class CaptureAlignmentError(ValueError):
    """Raised when prices and the production shape cannot align one-to-one."""


class PriceDataQualityError(ValueError):
    """Raised when market rows would otherwise be silently excluded."""


def trading_period_timestamps(
    trading_dates: pd.Series,
    trading_periods: pd.Series,
    timezone: str = "Pacific/Auckland",
) -> pd.Series:
    """Map sequential EA trading periods to unique UTC instants."""
    labels = trading_dates.astype(str).str.strip()
    iso = labels.str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    dates = pd.Series(pd.NaT, index=trading_dates.index, dtype="datetime64[ns]")
    dates.loc[iso] = pd.to_datetime(labels.loc[iso], format="%Y-%m-%d", errors="raise")
    dates.loc[~iso] = pd.to_datetime(
        labels.loc[~iso], format="mixed", dayfirst=True, errors="raise"
    )
    dates = dates.dt.normalize()
    numeric = pd.to_numeric(trading_periods, errors="raise")
    # astype(int) truncates, so 1.9 would silently become period 1.
    if not np.isclose(numeric, numeric.round()).all():
        offending = numeric[~np.isclose(numeric, numeric.round())].iloc[0]
        raise ValueError(f"trading periods must be whole numbers; found {offending!r}")
    periods = numeric.round().astype(int)
    if (periods < 1).any():
        raise ValueError("trading periods must be 1 or greater")

    local_midnight = dates.dt.tz_localize(timezone)
    # How many half hours that local day actually has: 48 normally, 46 when
    # daylight saving starts and 50 when it ends. A period beyond the day's own
    # length is not a real trading period, and converting it anyway lands on the
    # next day - where it collides with that day's first period, or silently
    # invents an instant when the next day is not in the file.
    next_midnight = (dates + pd.Timedelta(days=1)).dt.tz_localize(timezone)
    periods_in_day = (
        (next_midnight - local_midnight) // pd.Timedelta(minutes=30)
    ).astype(int)
    too_long = periods > periods_in_day
    if too_long.any():
        index = too_long.idxmax()
        raise ValueError(
            f"trading period {periods[index]} does not exist on {labels[index]}, "
            f"which has {periods_in_day[index]} half-hour periods"
        )
    return local_midnight.dt.tz_convert("UTC") + pd.to_timedelta((periods - 1) * 30, unit="min")


def _as_utc(values: pd.Series) -> pd.Series:
    """Parse timestamps while refusing timezone-naive labels."""
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        return values.dt.tz_convert("UTC")
    if pd.api.types.is_datetime64_dtype(values.dtype):
        raise CaptureAlignmentError("price timestamps must be timezone-aware UTC instants")
    labels = values.astype(str).str.strip()
    aware = labels.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True)
    if not aware.all():
        raise CaptureAlignmentError("price timestamps must include a UTC offset or Z suffix")
    return pd.to_datetime(labels, format="mixed", utc=True, errors="raise")


def capture_rate(prices: pd.Series, output: pd.Series) -> float:
    price = pd.to_numeric(prices, errors="coerce").to_numpy(dtype=float)
    generation = pd.to_numeric(output, errors="coerce").to_numpy(dtype=float)
    if len(price) != len(generation):
        raise PriceDataQualityError("price and output lengths differ")
    invalid = ~(np.isfinite(price) & np.isfinite(generation))
    if invalid.any():
        raise PriceDataQualityError(f"capture rate contains {int(invalid.sum())} non-finite rows")
    if len(price) == 0 or generation.sum() <= 0 or abs(price.mean()) < 1e-12:
        raise ValueError("capture rate requires finite prices, positive output and non-zero mean price")
    return float(np.sum(price * generation) / (np.sum(generation) * np.mean(price)))


def decompose_capture_rate(
    prices: pd.Series, output: pd.Series, day: pd.Series
) -> tuple[float, float]:
    """Split a capture rate into an exact seasonal term and an intraday term.

    Writing each period's price as a daily mean plus a within-day residual,
    ``sum(p*g)`` separates into ``sum_d n_d * P_d * G_d`` and
    ``sum_d n_d * cov_d``, where ``P_d``/``G_d`` are that day's mean price and
    mean output and ``cov_d`` is the within-day price/output covariance. Both
    terms share the capture-rate denominator, so

        capture_rate == seasonal_term + intraday_term

    holds exactly. The seasonal term is what a plant with the same *daily*
    energy but a flat within-day profile would capture: it answers "is output
    in the expensive months?". The intraday term is what the shape of the day
    adds or subtracts: it answers "is output in the expensive hours?". Only the
    second is midday price cannibalisation.
    """
    frame = pd.DataFrame(
        {
            "price": pd.to_numeric(prices, errors="coerce").astype(float).to_numpy(),
            "output": pd.to_numeric(output, errors="coerce").astype(float).to_numpy(),
            "day": np.asarray(day),
        }
    )
    invalid = ~(np.isfinite(frame["price"]) & np.isfinite(frame["output"]))
    if invalid.any():
        raise PriceDataQualityError(f"decomposition contains {int(invalid.sum())} non-finite rows")
    if frame.empty or frame["output"].sum() <= 0 or abs(frame["price"].mean()) < 1e-12:
        raise ValueError("decomposition requires finite prices, positive output and non-zero mean price")
    daily = frame.groupby("day", sort=False).agg(
        periods=("price", "size"), mean_price=("price", "mean"), mean_output=("output", "mean")
    )
    denominator = float(frame["output"].sum() * frame["price"].mean())
    seasonal = float((daily["periods"] * daily["mean_price"] * daily["mean_output"]).sum() / denominator)
    total = float((frame["price"] * frame["output"]).sum() / denominator)
    return seasonal, total - seasonal


def yearly_capture_rates(
    prices: pd.DataFrame,
    timestamp_col: str = "timestamp_utc",
    price_col: str = "price_nzd_mwh",
    latitude_deg: float = -43.55,
    capacity_factor: float = 0.175,
    timezone: str = "Pacific/Auckland",
    shaping_exponent: float = 1.15,
    timestep_minutes: int = 30,
    longitude_deg: float = 172.45,
    solar_time_basis: str = "apparent_solar",
    tilt_deg: float = 25.0,
    load_shape: pd.DataFrame | None = None,
    load_timestamp_col: str = "timestamp_utc",
    load_col: str = "load_kwh",
) -> pd.DataFrame:
    data = prices.copy()
    data[timestamp_col] = _as_utc(data[timestamp_col])
    if data[timestamp_col].duplicated().any():
        duplicate = data.loc[data[timestamp_col].duplicated(False), timestamp_col].iloc[0]
        raise CaptureAlignmentError(f"duplicate price timestamp: {duplicate}")
    data[price_col] = pd.to_numeric(data[price_col], errors="coerce")
    invalid_price = ~np.isfinite(data[price_col].to_numpy(dtype=float))
    if invalid_price.any():
        raise PriceDataQualityError(
            f"price input contains {int(invalid_price.sum())} missing or non-finite values"
        )
    local = data[timestamp_col].dt.tz_convert(timezone)
    local_year = local.dt.year
    data["_local_date"] = local.dt.date
    load = None
    if load_shape is not None:
        load = load_shape[[load_timestamp_col, load_col]].copy()
        load[load_timestamp_col] = _as_utc(load[load_timestamp_col])
        load[load_col] = pd.to_numeric(load[load_col], errors="coerce")
        invalid_load = ~np.isfinite(load[load_col].to_numpy(dtype=float))
        if invalid_load.any():
            raise PriceDataQualityError(
                f"load control contains {int(invalid_load.sum())} missing or non-finite values"
            )
        if load[load_timestamp_col].duplicated().any():
            raise CaptureAlignmentError("duplicate load timestamp in the control shape")
        load = load.rename(columns={load_timestamp_col: "timestamp_utc", load_col: "load_control"})
    records: list[dict[str, float | int]] = []
    for year, group in data.groupby(local_year):
        shape = half_hour_shape(
            int(year), latitude_deg=latitude_deg,
            target_capacity_factor=capacity_factor,
            timestep_minutes=timestep_minutes, timezone=timezone,
            shaping_exponent=shaping_exponent,
            longitude_deg=longitude_deg, solar_time_basis=solar_time_basis,
            tilt_deg=tilt_deg,
        )
        group = group.sort_values(timestamp_col).copy()
        try:
            merged = group.merge(
                shape[["timestamp_utc", "output_pu"]], left_on=timestamp_col,
                right_on="timestamp_utc", how="left", validate="one_to_one",
            )
        except pd.errors.MergeError as exc:
            raise CaptureAlignmentError(f"{year}: price/shape keys are not one-to-one") from exc
        if len(merged) != len(group):
            raise CaptureAlignmentError(f"{year}: merge lost/duplicated rows {len(group)} -> {len(merged)}")
        unmatched = int(merged["output_pu"].isna().sum())
        if unmatched:
            raise CaptureAlignmentError(f"{year}: {unmatched} price rows have no production-shape match")
        seasonal, intraday = decompose_capture_rate(
            merged[price_col], merged["output_pu"], merged["_local_date"]
        )
        record: dict[str, float | int] = {
            "year": int(year), "observations": int(len(merged)),
            "expected_observations": int(len(shape)),
            "complete_year": bool(len(merged) == len(shape)),
            "mean_price_nzd_mwh": float(merged[price_col].mean()),
            "solar_capture_rate": capture_rate(merged[price_col], merged["output_pu"]),
            "seasonal_capture_rate": seasonal,
            "intraday_capture_points": intraday,
            "flat_capture_rate": capture_rate(merged[price_col], pd.Series(1.0, index=merged.index)),
        }
        if load is not None:
            with_load = merged.merge(load, on="timestamp_utc", how="left", validate="one_to_one")
            missing_load = int(with_load["load_control"].isna().sum())
            if missing_load:
                raise CaptureAlignmentError(
                    f"{year}: {missing_load} price rows have no load-control match"
                )
            load_seasonal, load_intraday = decompose_capture_rate(
                with_load[price_col], with_load["load_control"], with_load["_local_date"]
            )
            record["load_capture_rate"] = capture_rate(
                with_load[price_col], with_load["load_control"]
            )
            record["load_seasonal_capture_rate"] = load_seasonal
            record["load_intraday_capture_points"] = load_intraday
        records.append(record)
    result = pd.DataFrame(records)
    accounted_rows = int(result["observations"].sum()) if not result.empty else 0
    if accounted_rows != len(data):
        raise CaptureAlignmentError(
            f"market-year accounting mismatch: {len(data)} input rows -> {accounted_rows} observations"
        )
    return result


def read_ea_price_csv(path: str, node: str, timezone: str = "Pacific/Auckland") -> pd.DataFrame:
    raw = pd.read_csv(path)
    lookup = {str(c).strip().lower().replace(" ", "_"): c for c in raw.columns}
    node_col = next((lookup[k] for k in ("node", "poc", "point_of_connection", "pointofconnection") if k in lookup), None)
    price_col = next((lookup[k] for k in ("price", "final_price", "price_nzd_mwh", "dollarspermegawatthour") if k in lookup), None)
    date_col = next((lookup[k] for k in ("date", "trading_date", "tradingdate") if k in lookup), None)
    period_col = next((lookup[k] for k in ("trading_period", "period", "tp", "tradingperiod") if k in lookup), None)
    resolved = {
        "node": node_col, "price": price_col, "trading date": date_col,
        "trading period": period_col,
    }
    missing = sorted(name for name, column in resolved.items() if column is None)
    if missing:
        raise ValueError(
            f"unrecognised EA schema: no column for {', '.join(missing)}. "
            f"Columns present: {list(raw.columns)}"
        )
    # Two source columns resolving to the same target means the guess was wrong,
    # and silently using one for both would corrupt every downstream number.
    chosen = [column for column in resolved.values()]
    if len(set(chosen)) != len(chosen):
        raise ValueError(
            f"ambiguous EA schema: {resolved} maps more than one field to the same column"
        )
    out = raw.loc[raw[node_col].astype(str).str.upper() == node.upper()].copy()
    if out.empty:
        raise PriceDataQualityError(f"no price rows found for node {node}")
    out["timestamp_utc"] = trading_period_timestamps(out[date_col], out[period_col], timezone)
    out["price_nzd_mwh"] = pd.to_numeric(out[price_col], errors="coerce")
    invalid = ~np.isfinite(out["price_nzd_mwh"].to_numpy(dtype=float))
    if invalid.any():
        raise PriceDataQualityError(
            f"{node}: {int(invalid.sum())} price rows are missing or non-numeric"
        )
    return out[["timestamp_utc", "price_nzd_mwh"]]
