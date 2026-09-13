"""The review-ordering score must be configurable and free of grid distance."""

from dataclasses import replace
import inspect
from pathlib import Path

import pytest
import yaml

from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.siting import SitingConfig, evaluate_sites
from nz_solar_siting.solar_shape import half_hour_shape

ROOT = Path(__file__).resolve().parents[1]


def _score(config: SitingConfig | None = None):
    sites, conservation, powerlines, roads = build_demo_layers()
    results, _ = evaluate_sites(sites, conservation, powerlines, roads, config)
    return results.set_index("site_id")


def test_score_ignores_grid_and_road_distance():
    """Moving every network far away must not reorder the review queue."""
    sites, conservation, powerlines, roads = build_demo_layers()
    baseline, _ = evaluate_sites(sites, conservation, powerlines, roads)
    moved_lines = powerlines.copy()
    moved_lines["geometry"] = moved_lines.geometry.translate(xoff=50_000.0)
    moved, _ = evaluate_sites(sites, conservation, moved_lines, roads)
    assert not moved.grid_line_m.equals(baseline.grid_line_m)
    assert moved.screen_score.equals(baseline.screen_score)


def test_weights_change_the_ordering():
    solar_led = _score(replace(SitingConfig(), solar_score_weight=1.0, area_score_weight=0.0))
    area_led = _score(replace(SitingConfig(), solar_score_weight=0.0, area_score_weight=1.0))
    assert solar_led.screen_score.idxmax() != area_led.screen_score.idxmax()
    assert solar_led.screen_score.idxmax() == solar_led.solar_kwh_m2.idxmax()
    assert area_led.screen_score.idxmax() == area_led.area_ha.idxmax()


def test_degenerate_weights_are_rejected():
    with pytest.raises(ValueError, match="positive"):
        _score(replace(SitingConfig(), solar_score_weight=0.0, area_score_weight=0.0))


def test_the_verify_flag_follows_the_review_distance():
    """S-06 is a distance rule, on the demo layer's fallback basis."""
    lenient = _score(replace(SitingConfig(), grid_distance_review_m=1e9))
    strict = _score(replace(SitingConfig(), grid_distance_review_m=1.0))
    assert not lenient.S06_verify_grid.any()
    assert strict.S06_verify_grid.any()


def test_rank_shift_cannot_raise_the_verify_flag():
    """The rule README calls uninformative must not come back through the library.

    rank_shift_review is a count of ranks: it discriminates across eight demo
    fixtures and fires on essentially every site at n = 2,356. It stays a
    published column and stays out of S-06.
    """
    generous = replace(SitingConfig(), grid_distance_review_m=1e9)
    for threshold in (1, 3, 99):
        results = _score(replace(generous, rank_shift_review=threshold))
        assert not results.S06_verify_grid.any()
    assert _score(generous).rank_shift.notna().any(), "rank_shift must still be published"


def test_published_assumptions_supply_every_siting_parameter():
    """config/assumptions.yml is the single source for weights and thresholds."""
    assumptions = yaml.safe_load((ROOT / "config" / "assumptions.yml").read_text(encoding="utf-8"))
    siting = assumptions["siting"]
    weights = siting["screen_score_weights"]
    assert set(weights) == {"solar_resource", "area"}
    assert "grid" not in " ".join(weights).lower()
    assert float(siting["rank_shift_review"]) > 0
    # The dataclass defaults and the published assumptions must not drift apart.
    assert SitingConfig() == SitingConfig(
        minimum_area_ha=float(siting["minimum_area_ha"]),
        minimum_average_width_m=float(siting["minimum_average_width_m"]),
        usable_lcdb_classes=tuple(siting["usable_lcdb_classes"]),
        grid_distance_review_m=float(siting["grid_distance_review_m"]),
        rank_shift_review=int(siting["rank_shift_review"]),
        solar_score_weight=float(weights["solar_resource"]),
        area_score_weight=float(weights["area"]),
    )


def test_published_solar_assumptions_match_the_model_defaults():
    solar = yaml.safe_load(
        (ROOT / "config" / "assumptions.yml").read_text(encoding="utf-8")
    )["solar"]
    defaults = inspect.signature(half_hour_shape).parameters
    assert defaults["tilt_deg"].default == float(solar["tilt_deg"])
    assert defaults["shaping_exponent"].default == float(solar["shaping_exponent"])
    assert defaults["latitude_deg"].default == float(solar["latitude_deg"])
    assert defaults["longitude_deg"].default == float(solar["longitude_deg"])
    assert float(solar["tilt_deg"]) in [float(t) for t in solar["tilt_sensitivity_deg"]]
