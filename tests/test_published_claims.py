"""Published prose must not contradict the corrections printed beside it.

A correction is worse than useless if the superseded sentence still stands a few
paragraphs below it: the reader cannot tell which one the author believes. This
happened once - a correction table saying the connection-tier figure was 14% sat
directly above the original "explains about 1% of the variance ... real but
negligible" paragraph and the interview line built on it.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CADASTRAL = json.loads(
    (ROOT / "outputs" / "cadastral_grid_basis_comparison.json").read_text(encoding="utf-8")
)
OSM_BASIS = json.loads(
    (ROOT / "outputs" / "osm" / "grid_basis_comparison.json").read_text(encoding="utf-8")
)
# Phrasings that described the superseded OpenStreetMap-population magnitude.
SUPERSEDED = ("practically negligible", "close to useless", "real but negligible",
              "explains about 1% of the variance", "1.2% of the variance")


def _correction_block() -> str:
    """The section that exists to quote the old claim, where it is allowed."""
    start = README.index("### Correction:")
    end = README.index("###", start + 3)
    return README[start:end]


@pytest.mark.parametrize("phrase", SUPERSEDED)
def test_superseded_phrasing_survives_only_inside_the_correction(phrase: str):
    outside = README.replace(_correction_block(), "")
    assert phrase not in outside, (
        f"{phrase!r} still stands outside the correction that supersedes it"
    )


@pytest.mark.parametrize("path", [
    "docs/index.html", "docs/app.js",
    "notebooks/01_grid_distance_comparison.ipynb",
    "notebooks/02_capture_rate.ipynb",
    "scripts/osm_grid_study.py",
    "scripts/grid_basis_comparison.py",
])
@pytest.mark.parametrize("phrase", SUPERSEDED)
def test_superseded_phrasing_is_gone_from_every_other_surface(path: str, phrase: str):
    """The dashboard and the notebooks are published text too."""
    assert phrase not in (ROOT / path).read_text(encoding="utf-8"), f"{phrase!r} in {path}"


def test_the_headline_figures_match_the_published_statistics():
    """The README's quoted numbers have to come from the committed JSON."""
    connection = CADASTRAL["correlation_with_road_distance"]["osm_33_66kv"]
    assert f"{connection['spearman_rho']:.3f}" in README
    assert f"{connection['variance_explained'] * 100:.1f}%" in README
    assert f"{CADASTRAL['sites']:,}" in README
    low = CADASTRAL["correlation_with_road_distance"]["osm_22kv_and_below"]["spearman_rho"]
    high = CADASTRAL["correlation_with_road_distance"]["osm_110kv_plus"]["spearman_rho"]
    assert f"{low:.3f}" in README and f"{high:.3f}" in README


def test_the_interview_sentence_quotes_the_cadastral_population():
    """One sentence gets repeated out loud, so it has to be the right one."""
    line = next(l for l in README.splitlines() if "take one sentence to an interview" in l)
    assert "cadastral" in line
    assert "14%" in line
    assert "monotonic" in line
    for phrase in SUPERSEDED:
        assert phrase not in line


def test_both_populations_stay_visible_and_labelled():
    """Neither population may quietly replace the other."""
    assert str(OSM_BASIS["sites"]) in README.replace(",", "")
    assert f"{CADASTRAL['sites']:,}" in README
    assert "ordering" in _correction_block()


def test_the_tilt_correction_size_matches_the_sensitivity_table():
    """A number quoted in prose has to come from the CSV it describes.

    This one did not: the worst-year effect of the horizontal-plane error was
    published as 7.1 points when the table says 10.7.
    """
    import pandas as pd

    tilt = pd.read_csv(ROOT / "outputs" / "demo" / "tilt_sensitivity.csv").set_index("tilt_deg")
    worst = (tilt.loc[25.0, "minimum_capture_rate"] - tilt.loc[0.0, "minimum_capture_rate"]) * 100
    mean = (tilt.loc[25.0, "mean_capture_rate"] - tilt.loc[0.0, "mean_capture_rate"]) * 100
    line = next(l for l in README.splitlines() if "on the worst year" in l)
    assert f"**{worst:.1f} percentage points**" in line, line
    assert f"{mean:.1f} points on the period mean" in line, line
    for tilt_deg in (0.0, 25.0):
        assert f"{tilt.loc[tilt_deg, 'minimum_capture_rate'] * 100:.1f}%" in line
