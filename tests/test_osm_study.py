"""The OSM study is the part of the grid finding that runs on real geometry."""

import json
from pathlib import Path

import pandas as pd
import pytest

from nz_solar_siting.load import InputValidationError
from nz_solar_siting.osm_layers import LAYER_NAMES, read_osm_layer, read_osm_layers

ROOT = Path(__file__).resolve().parents[1]
OSM_DIR = ROOT / "data" / "derived" / "osm"
STUDY = ROOT / "outputs" / "osm" / "osm_grid_study.json"


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


def test_study_sample_is_large_enough_to_mean_something():
    """The whole point of the OSM run is that n is no longer four."""
    summary = json.loads(STUDY.read_text(encoding="utf-8"))
    assert summary["sites_passing_area_and_width"] > 1000
    assert summary["network_features"]["transmission"] > 100


def test_road_distance_does_not_predict_transmission_distance():
    """The published claim: the two proxies rank sites almost independently."""
    summary = json.loads(STUDY.read_text(encoding="utf-8"))
    assert abs(summary["rank_correlation"]["transmission_m|road_m"]) < 0.25
    sweep = summary["top_n_sweep"]["transmission_m|road_m"]
    top = next(row for row in sweep if row["n"] == 50)
    assert top["jaccard"] < 0.25


def test_every_queued_aerial_site_has_coordinates_and_a_link():
    queue = pd.read_csv(ROOT / "outputs" / "osm" / "aerial_review_queue.csv")
    assert len(queue) == 20
    assert queue["latitude"].between(-45, -42).all()
    assert queue["longitude"].between(170, 175).all()
    assert queue["basemaps_url"].str.startswith("https://basemaps.linz.govt.nz/").all()
    # Reviewed rows must carry a date and imagery reference, not a bare opinion.
    reviewed = queue[queue["finding"].notna()]
    assert len(reviewed) >= 3
    assert reviewed["reviewed_on"].notna().all()
    assert reviewed["imagery"].notna().all()


def test_layers_load_together_in_the_documented_order():
    farmland, powerlines, roads = read_osm_layers(OSM_DIR)
    assert set(powerlines["power"].unique()) <= {"line", "minor_line"}
    assert farmland.geometry.geom_type.eq("Polygon").all()
    assert roads.geometry.geom_type.eq("LineString").all()
