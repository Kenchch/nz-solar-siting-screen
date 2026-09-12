"""M3: market-value capture-rate calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .solar_shape import half_hour_shape


class CaptureAlignmentError(ValueError):
    """Raised when prices and the production shape cannot align one-to-one."""


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
    periods = pd.to_numeric(trading_periods, errors="raise").astype(int)
    if (periods < 1).any() or (periods > 50).any():
        raise ValueError("trading periods must be integers from 1 to 50")
    local_midnight = dates.dt.tz_localize(timezone)
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
    valid = np.isfinite(price) & np.isfinite(generation)
    price, generation = price[valid], generation[valid]
    if len(price) == 0 or generation.sum() <= 0 or abs(price.mean()) < 1e-12:
        raise ValueError("capture rate requires finite prices, positive output and non-zero mean price")
    return float(np.sum(price * generation) / (np.sum(generation) * np.mean(price)))


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
) -> pd.DataFrame:
    data = prices.copy()
    data[timestamp_col] = _as_utc(data[timestamp_col])
    if data[timestamp_col].duplicated().any():
        duplicate = data.loc[data[timestamp_col].duplicated(False), timestamp_col].iloc[0]
        raise CaptureAlignmentError(f"duplicate price timestamp: {duplicate}")
    data[price_col] = pd.to_numeric(data[price_col], errors="coerce")
    local_year = data[timestamp_col].dt.tz_convert(timezone).dt.year
    records: list[dict[str, float | int]] = []
    for year, group in data.groupby(local_year):
        shape = half_hour_shape(
            int(year), latitude_deg=latitude_deg,
            target_capacity_factor=capacity_factor,
            timestep_minutes=timestep_minutes, timezone=timezone,
            shaping_exponent=shaping_exponent,
            longitude_deg=longitude_deg, solar_time_basis=solar_time_basis,
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
        records.append({
            "year": int(year), "observations": int(len(merged)),
            "mean_price_nzd_mwh": float(merged[price_col].mean()),
            "solar_capture_rate": capture_rate(merged[price_col], merged["output_pu"]),
            "flat_capture_rate": capture_rate(merged[price_col], pd.Series(1.0, index=merged.index)),
        })
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
    if not all((node_col, price_col, date_col, period_col)):
        raise ValueError(f"unrecognised EA schema: {list(raw.columns)}")
    out = raw.loc[raw[node_col].astype(str).str.upper() == node.upper()].copy()
    out["timestamp_utc"] = trading_period_timestamps(out[date_col], out[period_col], timezone)
    out["price_nzd_mwh"] = pd.to_numeric(out[price_col], errors="coerce")
    return out[["timestamp_utc", "price_nzd_mwh"]].dropna()
