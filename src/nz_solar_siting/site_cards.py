"""Create compact review cards for top-ranked sites."""

from __future__ import annotations

from pathlib import Path
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def write_site_cards(
    candidates: gpd.GeoDataFrame,
    powerlines: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    output_dir: str | Path,
    count: int = 3,
) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for _, row in candidates.nlargest(count, "screen_score").iterrows():
        fig, (ax, info) = plt.subplots(1, 2, figsize=(10, 5), gridspec_kw={"width_ratios": [1.55, 1]})
        gpd.GeoSeries([row.geometry], crs=candidates.crs).plot(ax=ax, color="#f7c948", edgecolor="#101820", linewidth=2)
        powerlines.plot(ax=ax, color="#19a974", linewidth=2, label="Public powerline data")
        roads.plot(ax=ax, color="#6d7f8b", linewidth=1, alpha=.8, label="Road proxy")
        minx, miny, maxx, maxy = row.geometry.buffer(1800).bounds
        ax.set(xlim=(minx, maxx), ylim=(miny, maxy), title=f"{row.site_id} — DEMO geometry")
        ax.legend(loc="lower left", fontsize=8)
        ax.set_axis_off()
        info.axis("off")
        lines = [
            f"SCREEN SCORE  {row.screen_score:.2f}",
            f"Area          {row.area_ha:.1f} ha",
            f"Mean width    {row.mean_width_m:.0f} m",
            f"LUC flag      {'YES — review' if row.S05_hpl_flag else 'No'}",
            f"Powerline     {row.grid_line_m:,.0f} m",
            f"Road proxy    {row.road_proxy_m:,.0f} m",
            f"Rank shift    {row.rank_shift}",
            f"Solar         {row.solar_kwh_m2:,.0f} kWh/m²/yr",
            "",
            "Screening only. Verify grid hosting capacity,",
            "land status, planning, hazards, access and ecology.",
        ]
        info.text(0.02, .96, "\n".join(lines), va="top", family="monospace", fontsize=11, linespacing=1.55)
        fig.tight_layout()
        path = output / f"{row.site_id.lower()}_card.png"
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="#f5f7f2")
        plt.close(fig)
        paths.append(path)
    return paths
