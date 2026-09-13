"""The rule register is a contract, not a description written alongside.

Every claim the register makes about a rule is checked against the library that
implements it. This file exists because the register once described S-06 as a
rank-shift rule for two releases after the library had stopped using one.
"""

import csv
from dataclasses import replace
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from nz_solar_siting.config import load_project_config
from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.grid_distance import grid_review_distance_m, verify_grid_flag
from nz_solar_siting.siting import SitingConfig, evaluate_sites

ROOT = Path(__file__).resolve().parents[1]
REGISTER = {
    row["rule_id"]: row
    for row in csv.DictReader(
        (ROOT / "rules" / "rule_register.csv").read_text(encoding="utf-8").splitlines()
    )
}
CONFIG = load_project_config(ROOT / "config" / "assumptions.yml")


@pytest.fixture(scope="module")
def demo_results():
    """The demo layers, with terrain, water and coastline supplied.

    The register calls S-08 and S-09 exclusions, so they need inputs to be
    exercised at all. The fixtures are deliberately crude: one steep site and
    one wet site, because the point is that the rules run in evaluate_sites and
    not that the demo geometry is realistic.
    """
    sites, conservation, powerlines, roads = build_demo_layers()
    terrain = pd.DataFrame({
        "site_id": sites["site_id"],
        "mean_slope_deg": [0.5] * (len(sites) - 1) + [22.0],
    })
    first = sites.geometry.iloc[0]
    water = gpd.GeoDataFrame(
        {"kind": ["lake"]},
        geometry=[first.buffer(-50.0)], crs="EPSG:2193",
    )
    minx, miny, maxx, maxy = sites.total_bounds
    coastline = gpd.GeoDataFrame(
        {"kind": ["coast"]},
        geometry=[LineString([(minx - 5000, miny - 400), (maxx + 5000, miny - 400)])],
        crs="EPSG:2193",
    )
    results, audit = evaluate_sites(
        sites, conservation, powerlines, roads, CONFIG.siting,
        terrain=terrain, water=water, coastline=coastline,
    )
    return results, audit


def test_an_omitted_rule_input_is_declared_not_silently_passed():
    """Leaving out terrain must not look like every site passed S-08."""
    results, audit = evaluate_sites(*build_demo_layers(), CONFIG.siting)
    assert set(str(results["rules_not_applied"].iloc[0]).split(";")) == {"S-08", "S-09", "S-10"}
    assert results["S08_verify_slope"].all(), "unknown slope must flag for verification"
    assert not results["failed_rule_ids"].str.contains("S-08").any()
    assert "rules_not_applied" in audit.columns


def test_slope_excludes_and_a_missing_value_flags(demo_results):
    results, _ = demo_results
    steep = results[results["mean_slope_deg"] > CONFIG.siting.maximum_mean_slope_deg]
    assert len(steep) == 1
    assert steep["failed_rule_ids"].str.contains("S-08").all()
    assert not results["S08_verify_slope"].any(), "every site had a slope value here"


def test_mapped_water_excludes(demo_results):
    results, _ = demo_results
    wet = results[results["water_m"] <= 0.0]
    assert not wet.empty
    assert wet["failed_rule_ids"].str.contains("S-09").all()


def test_coastal_proximity_flags_but_never_excludes(demo_results):
    results, _ = demo_results
    flagged = results[results["S10_coastal_flag"]]
    assert not flagged.empty
    assert not flagged["failed_rule_ids"].str.contains("S-10").any()


def test_every_registered_rule_id_is_unique_and_ordered():
    ids = list(REGISTER)
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("rule_id", ["S-01", "S-02", "S-03", "S-04", "S-08", "S-09"])
def test_exclusion_rules_quarantine_and_are_named_in_the_audit(rule_id, demo_results):
    """An 'exclude' row must be able to put its own id into failed_rule_ids."""
    assert REGISTER[rule_id]["rule_type"] == "exclude"
    assert REGISTER[rule_id]["failure_action"] == "quarantine"
    results, _ = demo_results
    column = f"{rule_id.replace('-', '')}_pass"
    assert column in results.columns, column
    failing = results.loc[~results[column].astype(bool), "failed_rule_ids"]
    assert failing.str.contains(rule_id).all()
    assert results.loc[~results[column].astype(bool), "status"].eq("quarantine").all()


def test_s05_is_a_flag_and_never_excludes(demo_results):
    assert REGISTER["S-05"]["rule_type"] == "flag"
    results, _ = demo_results
    flagged = results[results["S05_hpl_flag"]]
    assert not flagged.empty
    assert not flagged["failed_rule_ids"].str.contains("S-05").any()


def test_s06_is_the_distance_rule_the_register_describes():
    """The register says connection-tier distance; the library must agree."""
    threshold = REGISTER["S-06"]["threshold"]
    assert "connection-tier" in threshold
    assert "rank_shift_review" not in threshold.split("OSM study")[-1]

    config = CONFIG.siting
    assert grid_review_distance_m(config, config.connection_tier) == 5000.0
    # Distance decides it; a huge rank shift on a near site does not.
    frame = pd.DataFrame({
        "grid_line_m": [10.0, 10.0, 9_999_999.0],
        "rank_shift": [0, 10_000, 0],
        "grid_basis": [config.connection_tier] * 3,
    })
    assert verify_grid_flag(frame, config).tolist() == [False, False, True]


def test_s06_is_excluded_from_the_score_as_the_register_says(demo_results):
    assert "excluded from screen_score" in REGISTER["S-06"]["threshold"]
    sites, conservation, powerlines, roads = build_demo_layers()
    baseline, _ = evaluate_sites(sites, conservation, powerlines, roads, CONFIG.siting)
    moved = powerlines.copy()
    moved["geometry"] = moved.geometry.translate(xoff=50_000.0)
    shifted, _ = evaluate_sites(sites, conservation, moved, roads, CONFIG.siting)
    assert not shifted["grid_line_m"].equals(baseline["grid_line_m"])
    assert shifted["screen_score"].equals(baseline["screen_score"])


def test_s07_ranks_and_carries_the_registered_weight(demo_results):
    assert REGISTER["S-07"]["rule_type"] == "rank"
    assert "screen_score_weights.solar_resource" in REGISTER["S-07"]["threshold"]
    results, _ = demo_results
    candidates = results[results["status"] == "candidate_review"]
    best = candidates.loc[candidates["screen_score"].idxmax()]
    assert best["solar_kwh_m2"] >= candidates["solar_kwh_m2"].median()


def test_rules_the_register_calls_testable_have_an_implementation(demo_results):
    """'testable_from_open_data = yes' means something runs, not something planned."""
    results, _ = demo_results
    columns = set(results.columns)
    implemented = {
        "S-01": "S01_pass", "S-02": "S02_pass", "S-03": "S03_pass", "S-04": "S04_pass",
        "S-05": "S05_hpl_flag", "S-06": "S06_verify_grid", "S-07": "solar_rank",
        "S-08": "S08_pass", "S-09": "S09_pass", "S-10": "S10_coastal_flag",
    }
    for rule_id, row in REGISTER.items():
        if row["testable_from_open_data"] != "yes":
            continue
        assert rule_id in implemented, f"{rule_id} is registered but has no column"
        assert implemented[rule_id] in columns, rule_id
