"""The real-data assembly path, exercised on fixtures instead of credentials.

LRIS and LINZ both need an account only the account holder can create, so the
live run cannot be part of this suite. What can be tested is everything between
the download and the screen: attribute resolution across publisher spellings,
multipart splitting, the point lookups, deterministic identifiers, and the
refusal to run without a key. The fixtures are shaped like the real layers, not
like the demo geometry.
"""

import importlib.util
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import MultiPolygon, Polygon, box

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "config" / "assumptions.yml").read_text(encoding="utf-8"))
REAL = CONFIG["real_data"]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "build_real_sites", ROOT / "scripts" / "build_real_sites.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_script()

X, Y = 1_500_000.0, 5_150_000.0


def _landcover() -> gpd.GeoDataFrame:
    """LCDB-shaped input: publisher column name, a multipart feature, small parts."""
    big = box(X, Y, X + 900, Y + 900)                     # 81 ha, usable class
    multi = MultiPolygon([
        box(X + 2000, Y, X + 2900, Y + 900),              # 81 ha
        box(X + 4000, Y, X + 4100, Y + 100),              # 1 ha, below the rule
    ])
    excluded = box(X, Y + 2000, X + 900, Y + 2900)        # usable size, wrong class
    return gpd.GeoDataFrame(
        {"Name_2018": [
            "High Producing Exotic Grassland",
            "Short-rotation Cropland",
            "Built-up Area (settlement)",
        ]},
        geometry=[big, multi, excluded], crs="EPSG:2193",
    )


def _luc() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"lucl": [2, 6]},
        geometry=[box(X - 500, Y - 500, X + 1500, Y + 1500),
                  box(X + 1500, Y - 500, X + 3500, Y + 1500)],
        crs="EPSG:2193",
    )


def _solar() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"solrad": [1440, 1425]},
        geometry=[box(X - 500, Y - 500, X + 1500, Y + 1500),
                  box(X + 1500, Y - 500, X + 3500, Y + 1500)],
        crs="EPSG:2193",
    )


@pytest.fixture
def assembled() -> gpd.GeoDataFrame:
    return build.build_sites(
        _landcover(), _luc(), _solar(),
        usable_classes=tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        minimum_area_ha=float(CONFIG["siting"]["minimum_area_ha"]),
        config=REAL,
    )


def test_missing_credentials_stop_before_any_request(monkeypatch):
    monkeypatch.delenv("LRIS_API_KEY", raising=False)
    with pytest.raises(build.MissingCredential, match="LRIS_API_KEY"):
        build.api_key("LRIS_API_KEY")
    monkeypatch.setenv("LRIS_API_KEY", "   ")
    with pytest.raises(build.MissingCredential, match="Register a free account"):
        build.api_key("LRIS_API_KEY")


def test_attribute_names_resolve_across_publisher_spellings():
    frame = gpd.GeoDataFrame({"Name_2012": ["x"]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:2193")
    assert build.first_present(frame, ("Name_2018", "Name_2012"), "landcover") == "Name_2012"


def test_an_unknown_schema_reports_what_was_actually_there():
    frame = gpd.GeoDataFrame({"surprise": [1]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:2193")
    with pytest.raises(KeyError, match="surprise"):
        build.first_present(frame, ("Name_2018",), "landcover")


def test_only_usable_classes_survive(assembled):
    assert set(assembled["lcdb_class"]) <= set(CONFIG["siting"]["usable_lcdb_classes"])
    assert not assembled["lcdb_class"].str.contains("Built-up").any()


def test_multipart_features_are_split_and_small_parts_dropped(assembled):
    """A 1 ha sliver attached to an 81 ha block must not ride in on its parent."""
    assert (assembled.geometry.geom_type == "Polygon").all()
    assert len(assembled) == 2
    assert (assembled.geometry.area / 10_000.0 >= 20.0).all()


def test_luc_and_solar_are_attached_from_the_containing_polygon(assembled):
    values = assembled.set_index("lcdb_class")
    assert values.loc["High Producing Exotic Grassland", "luc_class"] == 2
    assert values.loc["High Producing Exotic Grassland", "solar_kwh_m2"] == 1440
    assert values.loc["Short-rotation Cropland", "luc_class"] == 6
    assert values.loc["Short-rotation Cropland", "solar_kwh_m2"] == 1425


def test_a_site_outside_every_source_polygon_is_reported_not_guessed():
    far = gpd.GeoDataFrame(
        {"Name_2018": ["Low Producing Grassland"]},
        geometry=[box(X + 50_000, Y, X + 50_900, Y + 900)], crs="EPSG:2193",
    )
    sites = build.build_sites(
        far, _luc(), _solar(),
        tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        float(CONFIG["siting"]["minimum_area_ha"]), REAL,
    )
    assert sites["luc_class"].isna().all()
    assert sites["solar_kwh_m2"].isna().all()


def test_site_ids_follow_the_geometry_not_the_download_order():
    """Re-downloading in a different order must not renumber the sites."""
    landcover = _landcover()
    forward = build.build_sites(
        landcover, _luc(), _solar(),
        tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        float(CONFIG["siting"]["minimum_area_ha"]), REAL,
    )
    reversed_order = build.build_sites(
        landcover.iloc[::-1].reset_index(drop=True), _luc(), _solar(),
        tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        float(CONFIG["siting"]["minimum_area_ha"]), REAL,
    )
    assert forward["site_id"].tolist() == reversed_order["site_id"].tolist()
    assert forward["lcdb_class"].tolist() == reversed_order["lcdb_class"].tolist()


def test_the_assembled_layer_satisfies_the_screen_contract(assembled):
    """The four columns solar-screen --sites requires, in EPSG:2193."""
    from nz_solar_siting.load import assert_nztm
    from nz_solar_siting.siting import evaluate_sites

    assert {"site_id", "lcdb_class", "luc_class", "solar_kwh_m2", "geometry"} <= set(
        assembled.columns
    )
    # S-05 is a coverage rule now, so the overlay result travels with the layer.
    assert {"hpl_fraction", "luc_mapped_fraction"} <= set(assembled.columns)
    assert assembled["hpl_fraction"].between(0.0, 1.0).all()
    assert_nztm(assembled, "sites")
    empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:2193")
    network = gpd.GeoDataFrame(
        {"n": [1]},
        geometry=gpd.GeoSeries.from_wkt([f"LINESTRING({X} {Y - 200}, {X + 5000} {Y - 200})"]),
        crs="EPSG:2193",
    )
    results, _ = evaluate_sites(assembled, empty, network, network)
    assert len(results) == len(assembled)
    assert results["status"].isin({"candidate_review", "quarantine"}).all()


def test_every_configured_layer_declares_a_portal_and_an_id():
    for name, spec in REAL["layers"].items():
        assert spec["portal"] in {"lris", "linz"}, name
        assert int(spec["layer_id"]) > 0, name
    assert len(REAL["bbox_nztm"]) == 4
    minx, miny, maxx, maxy = (float(v) for v in REAL["bbox_nztm"])
    assert minx < maxx and miny < maxy


def test_a_placeholder_key_is_refused_before_any_request(monkeypatch):
    """Pasting the documented example verbatim must fail with a readable reason.

    Without this the run reaches the service and comes back HTTP 400, which
    reads like a broken query rather than an unset credential.
    """
    monkeypatch.setenv("LRIS_API_KEY", "your-lris-key")
    with pytest.raises(build.MissingCredential, match="example placeholder"):
        build.api_key("LRIS_API_KEY")


def test_an_implausibly_short_key_is_refused(monkeypatch):
    monkeypatch.setenv("LINZ_API_KEY", "abc123")
    with pytest.raises(build.MissingCredential, match="shorter than any key"):
        build.api_key("LINZ_API_KEY")


def test_a_plausible_key_is_accepted(monkeypatch):
    monkeypatch.setenv("LINZ_API_KEY", "c01m2c6bk70gfrm3t81gag2xje6")
    assert build.api_key("LINZ_API_KEY") == "c01m2c6bk70gfrm3t81gag2xje6"


def test_the_credential_error_names_the_page_to_get_a_key_from(monkeypatch):
    monkeypatch.delenv("LINZ_API_KEY", raising=False)
    with pytest.raises(build.MissingCredential, match=r"data\.linz\.govt\.nz/my/api/"):
        build.api_key("LINZ_API_KEY")


def test_service_errors_explain_the_status_and_never_echo_the_url():
    """The request URL carries the key, so it must not reach a message."""
    import urllib.error

    def raising(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.test/services;key=SECRET/wfs?x=1", 403, "Forbidden", {}, None
        )

    original = build.urlopen
    build.urlopen = raising
    try:
        with pytest.raises(build.ServiceError) as caught:
            build._request("https://example.test/services;key=SECRET/wfs?x=1", 5, "layer-104400")
    finally:
        build.urlopen = original
    message = str(caught.value)
    assert "403" in message
    assert "accept the licence" in message
    assert "layer-104400" in message
    assert "SECRET" not in message


def test_the_assembled_layer_has_a_usable_index():
    """The screen refuses a non-unique index, so the assembly must not ship one.

    Distances are joined per row and then collapsed per site, so two rows
    sharing an index label would be given each other's distances. ``explode``
    leaves exactly such an index behind, and the sort onto the geometry's own
    south-west corner then permutes whatever survives. ``build_sites`` resets
    after both; nothing else in this file notices if it stops.

    The input is fed in reverse so the sort has to reorder it - on an input that
    is already sorted, the index comes out as 0..n-1 whether it was reset or
    not, and the assertion passes without testing anything.
    """
    landcover = _landcover().iloc[::-1].reset_index(drop=True)
    assembled = build.build_sites(
        landcover, _luc(), _solar(),
        tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        float(CONFIG["siting"]["minimum_area_ha"]), REAL,
    )
    assert len(assembled) > 1, "a one-row frame cannot show a permuted index"
    assert assembled.index.is_unique
    assert list(assembled.index) == list(range(len(assembled)))


def test_identifiers_describe_the_unit_rather_than_its_position_in_the_queue():
    """A sequential number renumbered every unit when one parcel was inserted.

    The id is the parcel, the cover class and a hash of the geometry, so a unit
    keeps its identity across a re-download and anything keyed on it - a terrain
    table, an aerial verdict - survives.
    """
    parcels = gpd.GeoDataFrame(
        {"id": [7666945], "appellation": ["Lot 1 DP 1"], "parcel_intent": ["Fee Simple Title"],
         "titles": ["CB1/1"], "calc_area": [810000]},
        geometry=[box(X - 100, Y - 100, X + 1000, Y + 1000)], crs="EPSG:2193",
    )
    built = build.build_sites(
        _landcover(), _luc(), _solar(),
        tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        float(CONFIG["siting"]["minimum_area_ha"]), REAL, parcels=parcels,
    )
    assert len(built) == 1
    site_id = built["site_id"].iloc[0]
    assert site_id.startswith("PARCEL-7666945-HPEG-"), site_id
    assert built["parcel_id"].iloc[0] == 7666945, "S-04 joins on this"

    # An unrelated parcel inserted ahead of it must not rename it.
    extra = gpd.GeoDataFrame(
        {"id": [1], "appellation": ["Lot 9 DP 9"], "parcel_intent": ["Fee Simple Title"],
         "titles": ["CB9/9"], "calc_area": [810000]},
        geometry=[box(X - 9000, Y - 9000, X - 8000, Y - 8000)], crs="EPSG:2193",
    )
    with_extra = build.build_sites(
        _landcover(), _luc(), _solar(),
        tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        float(CONFIG["siting"]["minimum_area_ha"]), REAL,
        parcels=pd.concat([extra, parcels], ignore_index=True),
    )
    assert site_id in set(with_extra["site_id"])


def test_luc_comes_from_coverage_not_from_the_middle_of_the_unit():
    """A parcel that is mostly LUC 2 with a LUC 6 hollow used to answer 6."""
    unit = box(X, Y, X + 900, Y + 900)
    landcover = gpd.GeoDataFrame(
        {"Name_2018": ["High Producing Exotic Grassland"]}, geometry=[unit], crs="EPSG:2193"
    )
    # LUC 2 everywhere except a hollow over the representative point.
    hollow = box(X + 400, Y + 400, X + 500, Y + 500)
    luc = gpd.GeoDataFrame(
        {"lucl": [6, 2]},
        geometry=[hollow, unit.difference(hollow)], crs="EPSG:2193",
    )
    built = build.build_sites(
        landcover, luc, _solar(),
        tuple(CONFIG["siting"]["usable_lcdb_classes"]),
        float(CONFIG["siting"]["minimum_area_ha"]), REAL,
    )
    assert built["luc_class"].iloc[0] == 2, "the dominant class by area"
    assert built["hpl_fraction"].iloc[0] > 0.95
    assert built["luc_mapped_fraction"].iloc[0] == pytest.approx(1.0, abs=1e-3)
