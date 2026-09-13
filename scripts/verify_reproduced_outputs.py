"""Compare platform-neutral output content with the committed artifacts.

Each binary output is compared against the integration branch (``origin/main``
by default) whenever that revision agrees with ``HEAD``, so the check is an
independent comparison rather than a branch grading its own work. When a file
was intentionally changed on this branch there is no independent baseline to
compare against, so the script falls back to ``HEAD``, reports the comparison
as determinism-only, and says which files were in that weaker category.
"""

from __future__ import annotations

import argparse
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
    Path("outputs/demo/figures/capture_rate_decomposition.png"),
    Path("outputs/demo/figures/grid_distance_comparison.png"),
    Path("outputs/demo/figures/seasonal_mismatch.png"),
    Path("outputs/demo/site_cards/demo-05_card.png"),
    Path("outputs/demo/site_cards/demo-08_card.png"),
    Path("outputs/demo/site_cards/demo-10_card.png"),
    Path("outputs/osm/osm_grid_disagreement.png"),
]


DEFAULT_BASELINE = "origin/main"


def _git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True)


def _revision_exists(revision: str) -> bool:
    return _git("rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}").returncode == 0


def resolve_baseline(path: Path, baseline: str) -> tuple[str, bool]:
    """Return the revision to compare against and whether it is independent."""
    if baseline == "HEAD" or not _revision_exists(baseline):
        return "HEAD", False
    unchanged = _git(
        "diff", "--quiet", baseline, "HEAD", "--", path.as_posix()
    ).returncode == 0
    return (baseline, True) if unchanged else ("HEAD", False)


def committed_bytes(path: Path, revision: str) -> bytes:
    result = _git("show", f"{revision}:{path.as_posix()}")
    if result.returncode != 0:
        raise AssertionError(
            f"{path} is not committed at {revision}: {result.stderr.decode().strip()}"
        )
    return result.stdout


def compare_geopackage(path: Path, revision: str) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        expected_path = Path(temporary_directory) / path.name
        expected_path.write_bytes(committed_bytes(path, revision))
        expected = gpd.read_file(expected_path)
    actual = gpd.read_file(ROOT / path)
    sort_key = "site_id" if "site_id" in actual.columns else actual.columns[0]
    expected = expected.sort_values(sort_key).reset_index(drop=True)
    actual = actual.sort_values(sort_key).reset_index(drop=True)
    assert_geodataframe_equal(actual, expected, check_dtype=False, check_like=True)
    print(f"semantic GeoPackage match vs {revision}: {path}")


def compare_png(path: Path, revision: str) -> None:
    expected = np.asarray(
        Image.open(BytesIO(committed_bytes(path, revision))).convert("RGBA"), dtype=np.int16
    )
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
        f"visual PNG match vs {revision}: {path} "
        f"(RMSE={rmse:.3f}, material pixels={material_fraction:.2%})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help="Revision to compare against when it agrees with HEAD (default: origin/main)",
    )
    parser.add_argument(
        "--require-independent",
        action="store_true",
        help="Fail if any output has no baseline other than HEAD (use on the main branch)",
    )
    arguments = parser.parse_args()
    determinism_only: list[Path] = []
    for path in GPKG_PATHS + PNG_PATHS:
        revision, independent = resolve_baseline(path, arguments.baseline)
        if not independent:
            determinism_only.append(path)
        if path in GPKG_PATHS:
            compare_geopackage(path, revision)
        else:
            compare_png(path, revision)
    if determinism_only:
        listed = ", ".join(str(path) for path in determinism_only)
        message = (
            f"determinism-only comparison (no independent baseline at "
            f"{arguments.baseline}): {listed}"
        )
        if arguments.require_independent:
            raise AssertionError(message)
        print(message)


if __name__ == "__main__":
    main()
