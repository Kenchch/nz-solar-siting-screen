"""Compare every reproduced output with the committed artifact at HEAD."""

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
OUTPUT_ROOTS = (Path("outputs/demo"), Path("outputs/osm"))


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
    print(f"visual PNG match: {path} (RMSE={rmse:.3f}, material pixels={material_fraction:.2%})")


def tracked_output_paths() -> set[Path]:
    paths: set[Path] = set()
    for root in OUTPUT_ROOTS:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", root.as_posix()],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        paths.update(Path(line) for line in result.stdout.splitlines() if line)
    return paths


def actual_output_paths() -> set[Path]:
    return {
        path.relative_to(ROOT)
        for root in OUTPUT_ROOTS
        for path in (ROOT / root).rglob("*")
        if path.is_file()
    }


def compare_file_manifest() -> list[Path]:
    expected = tracked_output_paths()
    actual = actual_output_paths()
    if expected != actual:
        missing = sorted(path.as_posix() for path in expected - actual)
        unexpected = sorted(path.as_posix() for path in actual - expected)
        raise AssertionError(f"output file set changed; missing={missing}, unexpected={unexpected}")
    print(f"output file manifest match: {len(actual)} files")
    return sorted(actual)


def main() -> None:
    for path in compare_file_manifest():
        if path.suffix == ".gpkg":
            compare_geopackage(path)
        elif path.suffix == ".png":
            compare_png(path)
        elif path.suffix not in {".csv", ".json"}:
            if (ROOT / path).read_bytes() != committed_bytes(path):
                raise AssertionError(f"binary output changed: {path}")


if __name__ == "__main__":
    main()
