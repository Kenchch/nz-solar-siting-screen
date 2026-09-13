"""Load and validate the single project configuration used by entry points."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .siting import SitingConfig, VoltageTier


@dataclass(frozen=True)
class ProjectConfig:
    assumptions: dict[str, Any]
    siting: SitingConfig
    top_n_comparison: int
    demo_top_n_comparison: int


def load_project_config(path: str | Path) -> ProjectConfig:
    source = Path(path)
    assumptions = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(assumptions, dict):
        raise ValueError(f"configuration must be a mapping: {source}")
    if int(assumptions["project"]["crs_epsg"]) != 2193:
        raise ValueError("project.crs_epsg must be 2193")
    values = assumptions["siting"]
    weights = values["screen_score_weights"]
    top_n = int(values["top_n_comparison"])
    demo_top_n = int(assumptions["demo"]["top_n_comparison"])
    if min(top_n, demo_top_n) < 1:
        raise ValueError("top-N comparison values must be positive")
    tiers = tuple(
        VoltageTier(
            name=str(name),
            minimum_v=float(band["minimum_v"]),
            maximum_v=float(band["maximum_v"]),
            review_distance_m=float(band["review_distance_m"]),
        )
        for name, band in values["voltage_tiers"].items()
    )
    connection_tier = str(values["connection_tier"])
    if connection_tier not in {tier.name for tier in tiers}:
        raise ValueError(f"siting.connection_tier {connection_tier!r} is not a configured tier")
    siting = SitingConfig(
        minimum_area_ha=float(values["minimum_area_ha"]),
        minimum_average_width_m=float(values["minimum_average_width_m"]),
        usable_lcdb_classes=tuple(values["usable_lcdb_classes"]),
        grid_distance_review_m=float(values["grid_distance_review_m"]),
        rank_shift_review=int(values["rank_shift_review"]),
        voltage_tiers=tiers,
        connection_tier=connection_tier,
        excluded_voltage_v=float(values["excluded_voltage_v"]),
        voltage_column=str(values["voltage_column"]),
        solar_score_weight=float(weights["solar_resource"]),
        area_score_weight=float(weights["area"]),
    )
    return ProjectConfig(assumptions, siting, top_n, demo_top_n)


def verify_data_checksums(data_root: str | Path, relative_paths: tuple[str, ...]) -> None:
    root = Path(data_root)
    expected = {
        line.split()[1]: line.split()[0]
        for line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    for relative in relative_paths:
        path = root / relative
        content = path.read_bytes()
        if path.suffix in {".csv", ".json"}:
            content = content.replace(b"\r\n", b"\n")
        actual = hashlib.sha256(content).hexdigest()
        if expected.get(relative) != actual:
            raise RuntimeError(f"committed input checksum mismatch: data/{relative}")
