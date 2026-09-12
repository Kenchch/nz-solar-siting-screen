"""Reproduce the deterministic demonstration and market-value outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml

from nz_solar_siting.capture import yearly_capture_rates
from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.screen import run_screening
from nz_solar_siting.site_cards import write_site_cards
from nz_solar_siting.siting import SitingConfig


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
    ax.plot(rates["year"], rates["flat_capture_rate"] * 100, linestyle="--", color="#24545d", label="Flat output invariant")
    ax.axhline(100, color="#89969c", linewidth=1)
    ax.set(xlabel="Year", ylabel="Capture rate (%)", title="ISL0661 wholesale market-value signal")
    ax.grid(alpha=.2)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=170, facecolor="white", metadata={"Software": "nz-solar-siting-screen"})
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Use committed deterministic demo inputs")
    parser.add_argument("--output", default="outputs/demo")
    parser.add_argument("--prices", help="Override the committed UTC price input")
    args = parser.parse_args()
    if not args.demo:
        parser.error("pass --demo for the reproducible committed workflow")

    assumptions = yaml.safe_load((ROOT / "config" / "assumptions.yml").read_text(encoding="utf-8"))
    siting = assumptions["siting"]
    solar = assumptions["solar"]
    market = assumptions["market"]
    siting_config = SitingConfig(
        minimum_area_ha=float(siting["minimum_area_ha"]),
        minimum_average_width_m=float(siting["minimum_average_width_m"]),
        usable_lcdb_classes=tuple(siting["usable_lcdb_classes"]),
        grid_distance_review_m=float(siting["grid_distance_review_m"]),
    )
    output = ROOT / args.output
    figures = output / "figures"
    cards = output / "site_cards"
    figures.mkdir(parents=True, exist_ok=True)

    sites, conservation, powerlines, roads = build_demo_layers()
    manifest = run_screening(
        sites, conservation, powerlines, roads, output,
        reject_rate_threshold=float(siting["maximum_reject_rate"]),
        config=siting_config,
        top_n_comparison=int(siting["top_n_comparison"]),
    )
    candidates = gpd.read_file(output / "candidates.gpkg")
    plot_grid_comparison(candidates, figures / "grid_distance_comparison.png")
    write_site_cards(candidates, powerlines, roads, cards, 3)

    price_path = ROOT / (args.prices or "data/derived/ISL0661_2019_2025.csv.gz")
    if not price_path.exists():
        raise FileNotFoundError(f"reproducible price input not found: {price_path}")
    prices = pd.read_csv(price_path)
    rate_options = {
        "latitude_deg": float(solar["latitude_deg"]),
        "capacity_factor": float(solar["target_capacity_factor"]),
        "timezone": str(market["timezone"]),
        "timestep_minutes": int(solar["timestep_minutes"]),
    }
    rates = yearly_capture_rates(
        prices, shaping_exponent=float(solar["shaping_exponent"]), **rate_options
    )
    rates.to_csv(output / "capture_rates.csv", index=False)
    plot_capture(rates, figures / "capture_rate_by_year.png")

    sensitivity_rows = []
    for exponent in solar["shaping_exponent_sensitivity"]:
        result = yearly_capture_rates(prices, shaping_exponent=float(exponent), **rate_options)
        sensitivity_rows.append({
            "shaping_exponent": float(exponent),
            "mean_capture_rate": float(result["solar_capture_rate"].mean()),
            "minimum_capture_rate": float(result["solar_capture_rate"].min()),
            "maximum_capture_rate": float(result["solar_capture_rate"].max()),
        })
    pd.DataFrame(sensitivity_rows).to_csv(output / "shape_exponent_sensitivity.csv", index=False)

    payload = {
        **manifest,
        "price_status": "official Electricity Authority final prices, ISL0661; unique UTC trading-period keys",
        "capture_rates": rates.round(4).to_dict(orient="records"),
        "shape_exponent_sensitivity": sensitivity_rows,
        "top_sites": candidates.nlargest(6, "screen_score")[[
            "site_id", "area_ha", "width_core_pass", "width_2ap_m",
            "width_methods_disagree", "S05_hpl_flag", "grid_line_m",
            "road_proxy_m", "rank_shift", "solar_kwh_m2", "screen_score",
        ]].to_dict(orient="records"),
    }
    (output / "findings.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (ROOT / "docs" / "data.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
