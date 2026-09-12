import pandas as pd
import pytest

from nz_solar_siting.capture import capture_rate


def test_flat_output_capture_rate_is_one():
    prices = pd.Series([12.0, 95.0, -2.0, 41.0, 64.0])
    output = pd.Series([1.0] * len(prices))
    assert capture_rate(prices, output) == pytest.approx(1.0)


def test_capture_rate_rejects_zero_output():
    with pytest.raises(ValueError):
        capture_rate(pd.Series([1.0, 2.0]), pd.Series([0.0, 0.0]))

