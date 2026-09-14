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


@pytest.mark.parametrize("path", ["README.md", "docs/index.html"])
def test_variance_explained_is_always_qualified_as_rank_variance(path: str):
    """Spearman's rho squared explains rank variance, not variance in metres.

    The correction reached the README and not the dashboard, which left the two
    published surfaces disagreeing about what the same number means.
    """
    text = (ROOT / path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if "14%" not in line and "14.3%" not in line:
            continue
        assert "rank" in line, f"{path}: variance not qualified as rank variance: {line[:120]}"


def test_the_dashboard_reads_the_aerial_verdict_count_instead_of_asserting_one():
    """Two samples are reviewed now; the page still said "all twenty".

    The count moved when the held-out sample B was added, and a number typed
    into prose cannot move with it. The sentence reads it from the study JSON,
    which is where every other published figure on the page comes from.
    """
    study = json.loads(
        (ROOT / "outputs" / "osm" / "osm_grid_study.json").read_text(encoding="utf-8")
    )
    review = study["aerial_review"]
    assert review["reviewed"] == sum(
        card["reviewed"] for card in review["by_sample"].values()
    ), "the headline count and the per-sample counts describe the same review"
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")
    assert 'id="aerial-reviewed"' in html
    assert "reviewedHost.textContent = review.reviewed" in javascript
    sentence = next(line for line in html.splitlines() if "aerial-reviewed" in line)
    assert "twenty" not in sentence.lower(), sentence


def test_the_dashboard_findings_are_numbered_once_each():
    """A numbered sequence with two 02s is not a sequence."""
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    indices = re.findall(r'class="finding-index">(\d+)<', html)
    assert indices, "the findings carry visible numbers"
    assert len(set(indices)) == len(indices), indices
    assert indices == sorted(indices), indices


def test_the_median_slope_in_prose_matches_the_study_it_describes():
    """A number quoted in prose has to come from the run it describes.

    This one did not: pooling DEM samples across tiles moved the median and the
    sentence kept the pre-pooling figure, so the README and the study JSON
    disagreed about the same statistic.
    """
    study = json.loads(
        (ROOT / "outputs" / "osm" / "osm_grid_study.json").read_text(encoding="utf-8")
    )
    terrain = study["terrain_water"]
    line = next(l for l in README.splitlines() if "Median mean slope across the study" in l)
    assert f"{terrain['median_mean_slope_deg']:.2f}°" in line, line
    assert str(terrain["excluded_by_either"]) in line, line


def test_the_rule_table_and_the_register_agree_on_s04():
    """Three surfaces state S-04; a shared boundary is not an overlap in any."""
    register = (ROOT / "rules" / "rule_register.csv").read_text(encoding="utf-8")
    assert "material intersection" in next(
        line for line in register.splitlines() if line.startswith("S-04,")
    )
    row = next(l for l in README.splitlines() if l.startswith("| S-04 public conservation land"))
    assert "material intersection" in row, row


def test_the_price_status_line_is_derived_from_the_rows_it_describes():
    """"2025 is partial" was typed, so it could not follow the next data drop."""
    import pandas as pd

    rates = pd.read_csv(ROOT / "outputs" / "demo" / "capture_rates.csv")
    status = json.loads(
        (ROOT / "outputs" / "demo" / "findings.json").read_text(encoding="utf-8")
    )["price_status"]
    complete = rates["complete_year"].astype(bool)
    for row in rates.loc[~complete].itertuples():
        assert (
            f"{int(row.year)} is partial ({int(row.observations):,} / "
            f"{int(row.expected_observations):,} periods)"
        ) in status, status
    for row in rates.loc[complete].itertuples():
        assert f"{int(row.year)} is partial" not in status, status
