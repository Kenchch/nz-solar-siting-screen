import geopandas as gpd
from shapely.geometry import box

from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.geometry import has_width_core, mean_width_area_perimeter
from nz_solar_siting.screen import run_screening
from nz_solar_siting.siting import evaluate_sites


def test_200_m_square_passes_core_but_fails_2ap():
    geometry = box(0, 0, 200, 200)
    assert mean_width_area_perimeter(geometry) == 100.0
    assert has_width_core(geometry, 180.0)


def test_400_m_square_passes_both_width_methods():
    geometry = box(0, 0, 400, 400)
    assert mean_width_area_perimeter(geometry) == 200.0
    assert has_width_core(geometry, 180.0)


def test_100_m_strip_fails_both_width_methods():
    geometry = box(0, 0, 100, 5000)
    assert mean_width_area_perimeter(geometry) < 180.0
    assert not has_width_core(geometry, 180.0)


def test_s02_uses_core_and_retains_2ap_comparator():
    sites, conservation, powerlines, roads = build_demo_layers()
    sites = sites.iloc[[0]].copy()
    sites.geometry = gpd.GeoSeries([box(1_500_000, 5_200_000, 1_500_200, 5_200_200)], crs=sites.crs)
    results, audit = evaluate_sites(sites, conservation.iloc[0:0], powerlines, roads)
    assert results.iloc[0].S02_pass
    assert results.iloc[0].width_methods_disagree
    assert {"width_2ap_m", "width_core_pass", "width_methods_disagree"} <= set(audit.columns)


def test_manifest_reports_width_method_disagreements(tmp_path):
    manifest = run_screening(*build_demo_layers(), tmp_path)
    assert manifest["width_method_disagreements"] >= 0
