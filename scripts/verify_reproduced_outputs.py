"""Compare platform-neutral output content with the committed artifacts."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import subprocess
import tempfile

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GPKG_PATHS = [
    Path("outputs/demo/candidates.gpkg"),
    Path("outputs/demo/quarantine.gpkg"),
]
PNG_PATHS = [
    Path("outputs/demo/figures/capture_rate_by_year.png"),
    Path("outputs/demo/figures/grid_distance_comparison.png"),
    Path("outputs/demo/site_cards/demo-05_card.png"),
    Path("outputs/demo/site_cards/demo-09_card.png"),
    Path("outputs/demo/site_cards/demo-10_card.png"),
]


def committed_bytes(path: Path) -> bytes:
    result = subprocess.run(
        ["git", "show", f"HEAD:{path.as_posix()}"], cwd=ROOT,
        check=True, capture_output=True,
    )
    return result.stdout


def compare_geopackage(path: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        expected_path = Path(temporary_directory) / path.name
        expected_path.write_bytes(committed_bytes(path))
        expected = gpd.read_file(expected_path)
    actual = gpd.read_file(ROOT / path)
    sort_key = "site_id" if "site_id" in actual.columns else actual.columns[0]
    expected = expected.sort_values(sort_key).reset_index(drop=True)
    actual = actual.sort_values(sort_key).reset_index(drop=True)
    assert_geodataframe_equal(actual, expected, check_dtype=False, check_like=True)
    print(f"semantic GeoPackage match: {path}")


def compare_png(path: Path) -> None:
    expected = np.asarray(Image.open(BytesIO(committed_bytes(path))).convert("RGBA"), dtype=np.int16)
    actual = np.asarray(Image.open(ROOT / path).convert("RGBA"), dtype=np.int16)
    if actual.shape != expected.shape:
        raise AssertionError(f"PNG dimensions changed for {path}: {expected.shape} -> {actual.shape}")
    delta = np.abs(actual - expected)
    rmse = float(np.sqrt(np.mean(delta.astype(float) ** 2)))
    material_fraction = float((delta.max(axis=2) > 24).mean())
    if rmse > 8.0 or material_fraction > 0.15:
        raise AssertionError(
            f"PNG changed materially for {path}: RMSE={rmse:.3f}, "
            f"material pixels={material_fraction:.2%}"
        )
    print(
        f"visual PNG match: {path} "
        f"(RMSE={rmse:.3f}, material pixels={material_fraction:.2%})"
    )


def main() -> None:
    for path in GPKG_PATHS:
        compare_geopackage(path)
    for path in PNG_PATHS:
        compare_png(path)


if __name__ == "__main__":
    main()
