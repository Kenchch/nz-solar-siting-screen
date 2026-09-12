import pytest

from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.screen import RejectRateExceeded, run_screening


def test_reject_rate_gate_aborts_suspicious_batch(tmp_path):
    with pytest.raises(RejectRateExceeded):
        run_screening(*build_demo_layers(), tmp_path, reject_rate_threshold=0.01)

