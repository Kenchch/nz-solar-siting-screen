"""The OSM study is the part of the grid finding that runs on real geometry."""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import LineString

from nz_solar_siting.load import InputValidationError
from nz_solar_siting.osm_layers import (
    LAYER_NAMES,
    max_voltage_v,
    read_osm_layer,
    read_osm_layers,
    split_by_voltage,
)

ROOT = Path(__file__).resolve().parents[1]
OSM_DIR = ROOT / "data" / "derived" / "osm"
STUDY = ROOT / "outputs" / "osm" / "osm_grid_study.json"
STUDY_CONFIG = yaml.safe_load(
    (ROOT / "config" / "assumptions.yml").read_text(encoding="utf-8")
)["osm_study"]
CONNECTION = STUDY_CONFIG["connection_tier"]


@pytest.fixture(scope="module")
def summary() -> dict:
    return json.loads(STUDY.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", LAYER_NAMES)
def test_committed_layer_is_nztm_and_non_empty(name: str):
    frame = read_osm_layer(name, OSM_DIR)
    assert frame.crs.to_epsg() == 2193
    assert len(frame) > 100


def test_missing_layer_names_the_rebuild_script():
    with pytest.raises(FileNotFoundError, match="download_osm_networks"):
        read_osm_layer("farmland", ROOT / "does-not-exist")


def test_a_non_nztm_layer_is_refused(tmp_path):
    import gzip

    farmland = read_osm_layer("farmland", OSM_DIR).head(200).to_crs("EPSG:4326")
    with gzip.open(tmp_path / "farmland.geojson.gz", "wb") as handle:
        handle.write(farmland.to_json().encode("utf-8"))
    with pytest.raises(InputValidationError, match="osm:farmland"):
        read_osm_layer("farmland", tmp_path)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("66000", 66000.0),
        # A shared structure carrying two circuits belongs to its highest one.
        ("66000;11000", 66000.0),
        ("33000;400", 33000.0),
        ("  220000 ", 220000.0),
    ],
)
def test_max_voltage_reads_the_highest_circuit(label: str, expected: float):
    assert max_voltage_v(label) == expected


def test_untagged_voltage_is_not_guessed():
    assert max_voltage_v(None) != max_voltage_v(None)  # NaN
    assert max_voltage_v("") != max_voltage_v("")


def test_tiers_partition_every_line_exactly_once():
    powerlines = read_osm_layer("powerlines", OSM_DIR)
    _, counts = split_by_voltage(
        powerlines, STUDY_CONFIG["voltage_tiers"], float(STUDY_CONFIG["excluded_voltage_v"])
    )
    assert sum(counts.values()) == len(powerlines)
    assert counts["excluded_above_threshold"] > 0, "the HVDC ways must be excluded, not tiered"
    assert counts["untagged_voltage"] > 0, "untagged ways must be reported, not silently assigned"


def test_a_66kv_way_is_tiered_by_voltage_not_by_its_power_tag():
    """power=line and power=minor_line both carry 66 kV in the real extract."""
    geometry = [LineString([(1_550_000, 5_180_000), (1_551_000, 5_180_000)])] * 2
    lines = gpd.GeoDataFrame(
        {"power": ["line", "minor_line"], "voltage": ["66000", "66000"]},
        geometry=geometry, crs="EPSG:2193",
    )
    split, _ = split_by_voltage(lines, STUDY_CONFIG["voltage_tiers"], 350000)
    assert len(split[CONNECTION]) == 2
    assert len(split["transmission_110kv_plus"]) == 0


def test_study_sample_is_large_enough_to_mean_something(summary):
    """The whole point of the OSM run is that n is no longer four."""
    assert summary["sites_passing_area_and_width"] > 1000
    assert summary["voltage_tier_features"][CONNECTION] > 100


def test_road_distance_predicts_distribution_but_not_the_connection_tier(summary):
    """The published claim, stated as an ordering rather than one number."""
    correlation = summary["rank_correlation"]
    transmission = correlation[f"transmission_110kv_plus_m|road_m"]
    connection = correlation[f"{CONNECTION}_m|road_m"]
    distribution = correlation["distribution_22kv_m|road_m"]
    assert transmission < connection < distribution
    assert connection < 0.25, "a road proxy must not be sold as a connection-tier proxy"
    assert distribution > 0.35, "roads do track the low-voltage network"
    top50 = next(
        row for row in summary["top_n_sweep"][f"{CONNECTION}_m|road_m"] if row["n"] == 50
    )
    assert top50["jaccard"] < 0.25


def test_the_verify_flag_discriminates(summary):
    """A flag that fires on everything is not a flag.

    The previous version took the maximum across every proxy and fired on
    2,347 of 2,356 sites. It is now distance to the connection tier only.
    """
    flagged = summary["verify_grid_flagged"]
    total = summary["sites_passing_area_and_width"]
    assert 0.02 < flagged / total < 0.5
    assert flagged == summary["beyond_tier_review_distance"][CONNECTION]


def test_every_queued_aerial_site_has_coordinates_and_a_link():
    queue = pd.read_csv(ROOT / "outputs" / "osm" / "aerial_review_queue.csv")
    assert len(queue) == 20
    assert queue["latitude"].between(-45, -42).all()
    assert queue["longitude"].between(170, 175).all()
    assert queue["basemaps_url"].str.startswith("https://basemaps.linz.govt.nz/").all()


def test_the_aerial_sample_is_complete_and_carries_its_provenance(summary):
    queue = pd.read_csv(ROOT / "outputs" / "osm" / "aerial_review_queue.csv")
    assert summary["aerial_review"]["reviewed"] == len(queue) == 20
    assert queue["finding"].notna().all()
    assert queue["reviewed_on"].notna().all()
    assert queue["imagery"].notna().all()
    assert set(queue["developable"]) <= {"yes", "no"}
    assert summary["aerial_review"]["false_positive_rate"] == pytest.approx(
        summary["aerial_review"]["not_developable"] / 20
    )


def test_layers_load_together_in_the_documented_order():
    farmland, powerlines, roads, wetland, coastline = read_osm_layers(OSM_DIR)
    assert set(powerlines["power"].unique()) <= {"line", "minor_line"}
    assert farmland.geometry.geom_type.eq("Polygon").all()
    assert roads.geometry.geom_type.eq("LineString").all()
    assert wetland.geometry.geom_type.eq("Polygon").all()
    assert coastline.geometry.geom_type.eq("LineString").all()


def test_terrain_layers_are_committed_and_nztm():
    for name in ("wetland", "coastline"):
        frame = read_osm_layer(name, OSM_DIR)
        assert frame.crs.to_epsg() == 2193
        assert len(frame) > 10


def test_every_site_has_a_slope_sample():
    terrain = pd.read_csv(OSM_DIR / "site_terrain.csv")
    sites = pd.read_csv(ROOT / "outputs" / "osm" / "osm_grid_distance.csv")
    assert set(sites["site_id"]) == set(terrain["site_id"])
    assert (terrain["slope_samples"] > 0).all()
    assert terrain["mean_slope_deg"].between(0, 90).all()


def test_the_plains_are_flat_and_the_peninsula_is_not(summary):
    """A sanity check on the DEM join: if it were misaligned this would fail."""
    assert summary["terrain_water"]["median_mean_slope_deg"] < 2.0
    sites = pd.read_csv(ROOT / "outputs" / "osm" / "osm_grid_distance.csv")
    assert sites["mean_slope_deg"].max() > 15.0


def test_terrain_and_water_rules_exclude_a_minority(summary):
    terrain = summary["terrain_water"]
    total = summary["sites_passing_area_and_width"]
    assert 0 < terrain["excluded_by_either"] / total < 0.2
    assert terrain["surviving_sites"] + terrain["excluded_by_either"] == total


def test_the_new_rules_catch_the_labelled_failures(summary):
    """In-sample by construction: the thresholds were set with these labels in view.

    The test records what the rules do on the labelled twenty so a later change
    cannot silently undo it, not that the rules generalise.
    """
    check = summary["aerial_review"]["in_sample_rule_check"]
    assert check["excluded_total"] >= 8
    assert check["developable_sites_wrongly_excluded"] == 0
    assert len(check["neither_excluded_nor_flagged"]) <= 1


def test_exclusion_and_flagging_are_reported_separately(summary):
    """A flag is not an exclusion; conflating them would overstate the rules.

    S-10 leaves a site in the candidate set for a human to assess, so a site it
    only flags has not been caught in the sense S-08 and S-09 catch one.
    """
    check = summary["aerial_review"]["in_sample_rule_check"]
    not_developable = summary["aerial_review"]["not_developable"]
    assert "excluded_total" in check and "flagged_only_by_coast" in check
    assert "caught_by_any" not in check
    accounted = (
        check["excluded_total"]
        + check["flagged_only_by_coast"]
        + len(check["neither_excluded_nor_flagged"])
    )
    assert accounted == not_developable
    assert check["excluded_by_slope"] + check["excluded_by_water"] == check["excluded_total"]


def test_the_review_passes_are_recorded_separately(summary):
    """Three passes, distinguishable: two AI passes and the author's confirmation."""
    review = summary["aerial_review"]
    second = review["second_pass"]
    assert second["confirmed"] + second["corrected"] == review["reviewed"]
    assert second["corrected"] >= 1, "the second pass found and fixed a real error"
    assert second["author_confirmed"] == review["reviewed"]


def test_the_aerial_sample_selection_is_declared(summary):
    """The 55% is the road proxy's worst cases, not a population rate."""
    selection = summary["aerial_review"]["selection"]
    assert "disagreement" in selection
    assert "not the candidate population" in selection


def test_every_logged_verdict_cites_an_image_that_exists():
    log = pd.read_csv(ROOT / "data" / "aerial_review_log.csv")
    assert len(log) == 20
    assert log["zoom_level"].eq(14).all()
    for image in log["evidence_image"]:
        assert (ROOT / image).exists(), image
    assert log["observed_detail"].str.len().min() > 80
    # The reviewer field must say who actually made the call.
    assert log["reviewer"].str.contains("AI agent").all()
    assert log["second_pass_result"].isin({"confirmed", "corrected"}).all()
    # The author's confirmation is its own column, never folded into `reviewer`.
    assert log["author_confirmed_on"].notna().all()
    assert not log["reviewer"].str.contains("author", case=False).any()


def test_the_scope_field_lists_the_rules_actually_applied(summary):
    for rule in ("S-01", "S-02", "S-08", "S-09", "S-10"):
        assert rule in summary["scope"], rule
