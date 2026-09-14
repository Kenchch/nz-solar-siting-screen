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
    accuracy = values["source_accuracy"]
    for name in ("conservation_overlay_m", "luc_overlay_m"):
        if float(accuracy[name]) < 0:
            raise ValueError(f"siting.source_accuracy.{name} must not be negative")
        # A number with no stated source is a number someone tuned. The basis
        # string is what stops that, so it is required, not decorative.
        basis = str(accuracy.get(name.replace("_m", "_basis"), "")).strip()
        if len(basis) < 40:
            raise ValueError(
                f"siting.source_accuracy.{name} needs a {name.replace('_m', '_basis')} "
                "quoting what the publisher says about the layer"
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
        maximum_mean_slope_deg=float(values["maximum_mean_slope_deg"]),
        minimum_slope_sample_coverage=float(values["minimum_slope_sample_coverage"]),
        coastal_review_distance_m=float(values["coastal_review_distance_m"]),
        conservation_overlay_accuracy_m=float(accuracy["conservation_overlay_m"]),
        luc_overlay_accuracy_m=float(accuracy["luc_overlay_m"]),
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

def resolve_output_directory(candidate: str | Path, root: str | Path) -> Path:
    """Resolve an output directory that is safe to delete and recreate.

    Callers delete this directory before writing it. The earlier guard only
    required the path to be inside the repository and not its root, so
    ``--output src`` reached the delete branch. A directory that gets removed on
    every run has to be one the project owns, which means under ``outputs/``.
    """
    root_path = Path(root).resolve()
    output = (root_path / candidate).resolve()
    outputs_root = (root_path / "outputs").resolve()
    if output == outputs_root or not output.is_relative_to(outputs_root):
        raise ValueError(
            f"output directory must be inside outputs/, not {str(candidate)!r}: "
            "this path is deleted and rewritten on every run"
        )
    return output
