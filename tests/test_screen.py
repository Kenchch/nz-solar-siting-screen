from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.screen import run_screening


def test_selection_rate_is_reported_as_an_outcome(tmp_path):
    result = run_screening(*build_demo_layers(), tmp_path)
    assert result["selection_rate"] + result["reject_rate"] == 1.0

