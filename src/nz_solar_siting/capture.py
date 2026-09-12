"""M3: market-value capture-rate calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .solar_shape import half_hour_shape


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
    timestamp_col: str = "timestamp",
    price_col: str = "price_nzd_mwh",
    latitude_deg: float = -43.55,
    capacity_factor: float = 0.175,
) -> pd.DataFrame:
    data = prices.copy()
    raw_time = data[timestamp_col].astype(str)
    parts = raw_time.str.extract(r"(?P<date>\d{4}-\d{2}-\d{2})T(?P<hour>\d{2}):(?P<minute>\d{2})")
    if parts.notna().all(axis=None):
        data[timestamp_col] = (
            pd.to_datetime(parts["date"])
            + pd.to_timedelta(parts["hour"].astype(int), unit="h")
            + pd.to_timedelta(parts["minute"].astype(int), unit="m")
        )
    else:
        data[timestamp_col] = pd.to_datetime(data[timestamp_col], format="mixed")
    records: list[dict[str, float | int]] = []
    for year, group in data.groupby(data[timestamp_col].dt.year):
        shape = half_hour_shape(int(year), latitude_deg, capacity_factor)
        group = group.sort_values(timestamp_col).copy()
        group["key"] = group[timestamp_col].dt.strftime("%m-%d %H:%M")
        shape["key"] = shape["timestamp"].dt.strftime("%m-%d %H:%M")
        merged = group.merge(shape[["key", "output_pu"]], on="key", how="inner")
        records.append(
            {
                "year": int(year),
                "observations": int(len(merged)),
                "mean_price_nzd_mwh": float(merged[price_col].mean()),
                "solar_capture_rate": capture_rate(merged[price_col], merged["output_pu"]),
                "flat_capture_rate": capture_rate(merged[price_col], pd.Series(1.0, index=merged.index)),
            }
        )
    return pd.DataFrame(records)


def read_ea_price_csv(path: str, node: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    lookup = {str(c).strip().lower().replace(" ", "_"): c for c in raw.columns}
    node_col = next((lookup[k] for k in ("node", "poc", "point_of_connection", "pointofconnection") if k in lookup), None)
    price_col = next((lookup[k] for k in ("price", "final_price", "price_nzd_mwh", "dollarspermegawatthour") if k in lookup), None)
    date_col = next((lookup[k] for k in ("date", "trading_date", "tradingdate") if k in lookup), None)
    period_col = next((lookup[k] for k in ("trading_period", "period", "tp", "tradingperiod") if k in lookup), None)
    if not all((node_col, price_col, date_col, period_col)):
        raise ValueError(f"unrecognised EA schema: {list(raw.columns)}")
    out = raw.loc[raw[node_col].astype(str).str.upper() == node.upper()].copy()
    period = pd.to_numeric(out[period_col], errors="raise").astype(int)
    base = pd.to_datetime(out[date_col], dayfirst=True)
    out["timestamp"] = base + pd.to_timedelta((period - 1) * 30, unit="min")
    out["price_nzd_mwh"] = pd.to_numeric(out[price_col], errors="coerce")
    return out[["timestamp", "price_nzd_mwh"]].dropna()
