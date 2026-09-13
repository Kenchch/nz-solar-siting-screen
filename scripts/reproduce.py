"""Reproduce the deterministic demonstration and market-value outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from nz_solar_siting.capture import yearly_capture_rates
from nz_solar_siting.config import load_project_config, verify_data_checksums
from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.screen import run_screening
from nz_solar_siting.site_cards import write_site_cards
from nz_solar_siting.solar_shape import half_hour_shape


def plot_grid_comparison(candidates: gpd.GeoDataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    ax.scatter(candidates["grid_line_m"], candidates["road_proxy_m"], s=65, c=candidates["rank_shift"], cmap="viridis", edgecolor="#101820")
    maximum = max(candidates["grid_line_m"].max(), candidates["road_proxy_m"].max()) * 1.06
    ax.plot([0, maximum], [0, maximum], linestyle="--", color="#7d8990", linewidth=1)
    for _, row in candidates.nlargest(3, "rank_shift").iterrows():
        ax.annotate(row.site_id, (row.grid_line_m, row.road_proxy_m), xytext=(5, 5), textcoords="offset points")
    ax.set(xlabel="Distance to public powerline layer (m)", ylabel="Distance to road proxy (m)", title="Grid proximity changes with the proxy")
    ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(path, dpi=170, facecolor="white", metadata={"Software": "nz-solar-siting-screen"})
    plt.close(fig)


def plot_capture(rates: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(rates["year"], rates["solar_capture_rate"] * 100, marker="o", color="#e5a300", linewidth=2.5, label="Modelled solar shape")
    partial = rates.loc[~rates["complete_year"]]
    if not partial.empty:
        ax.scatter(partial["year"], partial["solar_capture_rate"] * 100, marker="x", s=90, color="#b33a3a", linewidth=2.5, label="Partial year")
    ax.plot(rates["year"], rates["load_capture_rate"] * 100, marker="s", color="#b5179e", linewidth=2, label="ISL0661 metered load control")
    ax.plot(rates["year"], rates["flat_capture_rate"] * 100, linestyle="--", color="#24545d", label="Flat output invariant")
    ax.axhline(100, color="#89969c", linewidth=1)
    ax.set(xlabel="Year", ylabel="Capture rate (%)", title="ISL0661 wholesale market-value signal")
    ax.grid(alpha=.2)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=170, facecolor="white", metadata={"Software": "nz-solar-siting-screen"})
    plt.close(fig)


def plot_capture_decomposition(rates: pd.DataFrame, path: Path) -> None:
    """Show that the capture-rate discount is seasonal, not midday shape."""
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    seasonal = (rates["seasonal_capture_rate"] - 1.0) * 100
    intraday = rates["intraday_capture_points"] * 100
    ax.bar(rates["year"] - 0.18, seasonal, width=0.34, color="#2d6a9f", label="Seasonal term (daily energy vs daily price)")
    ax.bar(rates["year"] + 0.18, intraday, width=0.34, color="#e5a300", label="Intraday term (shape within the day)")
    ax.axhline(0, color="#101820", linewidth=1)
    ax.set(
        xlabel="NZ market year",
        ylabel="Contribution to capture rate (percentage points)",
        title="Where the capture-rate gap comes from",
    )
    ax.set_xticks(rates["year"].tolist())
    ax.grid(alpha=.2, axis="y")
    ax.legend(frameon=False, loc="lower left", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=170, facecolor="white", metadata={"Software": "nz-solar-siting-screen"})
    plt.close(fig)


def plot_seasonal_mismatch(monthly: pd.DataFrame, year: int, path: Path) -> None:
    """Plot monthly mean price against the modelled monthly output share."""
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar(monthly["month"], monthly["mean_price_nzd_mwh"], color="#2d6a9f", label="Mean nodal price")
    ax.set(xlabel=f"Month of {year}", ylabel="Mean price (NZD/MWh)")
    ax.set_xticks(range(1, 13))
    twin = ax.twinx()
    twin.plot(monthly["month"], monthly["output_share_pct"], marker="o", color="#e5a300", linewidth=2.5, label="Share of annual output")
    twin.set_ylabel("Modelled output (% of year)")
    ax.grid(alpha=.2, axis="y")
    handles = ax.get_legend_handles_labels()[0] + twin.get_legend_handles_labels()[0]
    labels = ax.get_legend_handles_labels()[1] + twin.get_legend_handles_labels()[1]
    ax.legend(handles, labels, frameon=False, loc="upper right", fontsize=9)
    ax.set_title(f"Seasonal mismatch at ISL0661, {year}")
    fig.tight_layout()
    fig.savefig(path, dpi=170, facecolor="white", metadata={"Software": "nz-solar-siting-screen"})
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Use committed deterministic demo inputs")
    parser.add_argument("--output", default="outputs/demo")
    parser.add_argument("--prices", help="Override the committed UTC price input")
    parser.add_argument("--config", default="config/assumptions.yml")
    args = parser.parse_args()
    if not args.demo:
        parser.error("pass --demo for the reproducible committed workflow")

    project_config = load_project_config(ROOT / args.config)
    assumptions = project_config.assumptions
    solar = assumptions["solar"]
    market = assumptions["market"]
    output = (ROOT / args.output).resolve()
    if output == ROOT or not output.is_relative_to(ROOT):
        raise ValueError("--output must be a directory inside the repository")
    if output.exists():
        shutil.rmtree(output)
    figures = output / "figures"
    cards = output / "site_cards"
    figures.mkdir(parents=True, exist_ok=True)

    sites, conservation, powerlines, roads = build_demo_layers()
    manifest = run_screening(
        sites, conservation, powerlines, roads, output,
        config=project_config.siting,
        top_n_comparison=project_config.demo_top_n_comparison,
        scope="screening only; demo geometries are not real parcels",
    )
    candidates = gpd.read_file(output / "candidates.gpkg")
    plot_grid_comparison(candidates, figures / "grid_distance_comparison.png")
    write_site_cards(candidates, powerlines, roads, cards, 3)

    price_path = ROOT / (args.prices or "data/derived/ISL0661_2019_2025.csv.gz")
    if not price_path.exists():
        raise FileNotFoundError(f"reproducible price input not found: {price_path}")
    if not args.prices:
        verify_data_checksums(ROOT / "data", ("derived/ISL0661_2019_2025.csv.gz",))
    prices = pd.read_csv(price_path)
    load_path = ROOT / str(market["load_control_path"])
    if not load_path.exists():
        raise FileNotFoundError(f"load control input not found: {load_path}")
    verify_data_checksums(ROOT / "data", ("derived/ISL0661_load_2019_2025.csv.gz",))
    load_shape = pd.read_csv(load_path)
    rate_options = {
        "latitude_deg": float(solar["latitude_deg"]),
        "capacity_factor": float(solar["target_capacity_factor"]),
        "timezone": str(market["timezone"]),
        "timestep_minutes": int(solar["timestep_minutes"]),
        "longitude_deg": float(solar["longitude_deg"]),
        "tilt_deg": float(solar["tilt_deg"]),
    }
    rates = yearly_capture_rates(
        prices, shaping_exponent=float(solar["shaping_exponent"]),
        solar_time_basis=str(solar["solar_time_basis"]),
        load_shape=load_shape, **rate_options,
    )
    rates.round(10).to_csv(output / "capture_rates.csv", index=False)
    plot_capture(rates, figures / "capture_rate_by_year.png")
    plot_capture_decomposition(rates, figures / "capture_rate_decomposition.png")

    mismatch_year = int(rates.loc[rates["solar_capture_rate"].idxmin(), "year"])
    baseline_shape = half_hour_shape(
        mismatch_year, latitude_deg=float(solar["latitude_deg"]),
        target_capacity_factor=float(solar["target_capacity_factor"]),
        timestep_minutes=int(solar["timestep_minutes"]),
        timezone=str(market["timezone"]),
        shaping_exponent=float(solar["shaping_exponent"]),
        longitude_deg=float(solar["longitude_deg"]),
        solar_time_basis=str(solar["solar_time_basis"]),
        tilt_deg=float(solar["tilt_deg"]),
    )
    shape_month = baseline_shape["midpoint_utc"].dt.tz_convert(str(market["timezone"])).dt.month
    price_local = pd.to_datetime(prices["timestamp_utc"], utc=True).dt.tz_convert(str(market["timezone"]))
    year_prices = prices.loc[price_local.dt.year == mismatch_year]
    monthly = pd.DataFrame({
        "month": range(1, 13),
        "mean_price_nzd_mwh": year_prices.groupby(
            price_local.loc[year_prices.index].dt.month
        )["price_nzd_mwh"].mean().reindex(range(1, 13)).to_numpy(),
        "output_share_pct": (
            100.0
            * baseline_shape.groupby(shape_month)["output_pu"].sum()
            / baseline_shape["output_pu"].sum()
        ).reindex(range(1, 13)).to_numpy(),
    })
    monthly["year"] = mismatch_year
    monthly.round(10).to_csv(output / "seasonal_mismatch.csv", index=False)
    plot_seasonal_mismatch(monthly, mismatch_year, figures / "seasonal_mismatch.png")

    clock_rates = yearly_capture_rates(
        prices, shaping_exponent=float(solar["shaping_exponent"]),
        solar_time_basis="civil_clock", **rate_options,
    )
    time_basis_comparison = clock_rates[["year", "solar_capture_rate"]].rename(
        columns={"solar_capture_rate": "civil_clock_capture_rate"}
    ).merge(
        rates[["year", "solar_capture_rate"]].rename(
            columns={"solar_capture_rate": "apparent_solar_capture_rate"}
        ),
        on="year", validate="one_to_one",
    )
    time_basis_comparison["change_percentage_points"] = 100.0 * (
        time_basis_comparison["apparent_solar_capture_rate"]
        - time_basis_comparison["civil_clock_capture_rate"]
    )
    time_basis_comparison = time_basis_comparison.round(10)
    time_basis_comparison.to_csv(output / "solar_time_basis_comparison.csv", index=False)

    timestamp_utc = pd.to_datetime(prices["timestamp_utc"], utc=True)
    utc_counts = prices.groupby(timestamp_utc.dt.year).size().rename("utc_year_rows")
    market_counts = prices.groupby(
        timestamp_utc.dt.tz_convert(str(market["timezone"])).dt.year
    ).size().rename("nz_market_year_rows")
    accounting = pd.concat([utc_counts, market_counts], axis=1).fillna(0).astype(int)
    accounting.index.name = "year"
    accounting = accounting.reset_index()
    if int(accounting["nz_market_year_rows"].sum()) != len(prices):
        raise RuntimeError("NZ market-year accounting does not reconcile to price input")
    accounting.to_csv(output / "market_year_accounting.csv", index=False)
    quality = pd.DataFrame([{
        "input_rows": len(prices),
        "aligned_rows": int(rates["observations"].sum()),
        "valid_price_rows": int(rates["observations"].sum()),
        "duplicate_utc_rows": int(prices["timestamp_utc"].duplicated().sum()),
        "complete_market_years": int(rates["complete_year"].sum()),
        "partial_market_years": int((~rates["complete_year"]).sum()),
    }])
    if not (
        quality.loc[0, "input_rows"]
        == quality.loc[0, "aligned_rows"]
        == quality.loc[0, "valid_price_rows"]
    ):
        raise RuntimeError("price quality counts do not reconcile")
    quality.to_csv(output / "price_quality.csv", index=False)

    def summarise(result: pd.DataFrame) -> dict[str, float]:
        return {
            "mean_capture_rate": float(result["solar_capture_rate"].mean()),
            "minimum_capture_rate": float(result["solar_capture_rate"].min()),
            "maximum_capture_rate": float(result["solar_capture_rate"].max()),
            "mean_seasonal_capture_rate": float(result["seasonal_capture_rate"].mean()),
            "mean_intraday_capture_points": float(result["intraday_capture_points"].mean()),
        }

    sensitivity_rows = []
    for exponent in solar["shaping_exponent_sensitivity"]:
        result = yearly_capture_rates(
            prices, shaping_exponent=float(exponent),
            solar_time_basis=str(solar["solar_time_basis"]), **rate_options,
        )
        sensitivity_rows.append({
            "shaping_exponent": float(exponent),
            "tilt_deg": float(solar["tilt_deg"]),
            **summarise(result),
        })
    sensitivity = pd.DataFrame(sensitivity_rows).round(10)
    sensitivity.to_csv(output / "shape_exponent_sensitivity.csv", index=False)
    sensitivity_rows = sensitivity.to_dict(orient="records")

    tilt_options = {key: value for key, value in rate_options.items() if key != "tilt_deg"}
    tilt_rows = []
    for tilt in solar["tilt_sensitivity_deg"]:
        result = yearly_capture_rates(
            prices, shaping_exponent=float(solar["shaping_exponent"]),
            solar_time_basis=str(solar["solar_time_basis"]),
            tilt_deg=float(tilt), **tilt_options,
        )
        shape = half_hour_shape(
            2024, latitude_deg=float(solar["latitude_deg"]),
            target_capacity_factor=float(solar["target_capacity_factor"]),
            timestep_minutes=int(solar["timestep_minutes"]),
            timezone=str(market["timezone"]),
            shaping_exponent=float(solar["shaping_exponent"]),
            longitude_deg=float(solar["longitude_deg"]),
            solar_time_basis=str(solar["solar_time_basis"]),
            tilt_deg=float(tilt),
        )
        month = shape["midpoint_utc"].dt.tz_convert(str(market["timezone"])).dt.month
        monthly_output = shape.groupby(month)["output_pu"].sum()
        tilt_rows.append({
            "tilt_deg": float(tilt),
            "december_over_june_output": float(monthly_output.loc[12] / monthly_output.loc[6]),
            **summarise(result),
        })
    tilt_sensitivity = pd.DataFrame(tilt_rows).round(10)
    tilt_sensitivity.to_csv(output / "tilt_sensitivity.csv", index=False)
    tilt_rows = tilt_sensitivity.to_dict(orient="records")

    osm_study_path = ROOT / "outputs" / "osm" / "osm_grid_study.json"
    osm_study = (
        json.loads(osm_study_path.read_text(encoding="utf-8")) if osm_study_path.exists() else None
    )
    payload = {
        **manifest,
        "osm_grid_study": osm_study,
        "price_status": "official EA final prices, ISL0661; 2025 is partial (17,472 / 17,520 periods)",
        "capture_rates": rates.round(4).to_dict(orient="records"),
        "shape_exponent_sensitivity": sensitivity_rows,
        "tilt_sensitivity": tilt_rows,
        "seasonal_mismatch_year": mismatch_year,
        "seasonal_mismatch": monthly.round(4).to_dict(orient="records"),
        "solar_time_basis_comparison": time_basis_comparison.to_dict(orient="records"),
        "market_year_accounting": accounting.to_dict(orient="records"),
        "price_quality": quality.to_dict(orient="records")[0],
        "top_sites": candidates.nlargest(6, "screen_score")[[
            "site_id", "area_ha", "width_core_pass", "width_2ap_m",
            "width_methods_disagree", "S05_hpl_flag", "grid_line_m",
            "road_proxy_m", "rank_shift", "solar_kwh_m2", "screen_score",
        ]].to_dict(orient="records"),
    }
    centroids = candidates.geometry.centroid
    centroid_lookup = dict(zip(candidates["site_id"], zip(centroids.x, centroids.y)))
    for site in payload["top_sites"]:
        site["centroid_easting"], site["centroid_northing"] = centroid_lookup[site["site_id"]]
    (output / "findings.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (ROOT / "docs" / "data.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
