import numpy as np
import pandas as pd
import pytest

from nz_solar_siting.capture import yearly_capture_rates
from nz_solar_siting.solar_shape import half_hour_shape


def test_capacity_factor_scaling_remains_an_invariant():
    shape = half_hour_shape(2023, target_capacity_factor=0.21)
    assert shape.output_pu.mean() == pytest.approx(0.21)


def test_shaping_exponent_changes_intraday_profile():
    broad = half_hour_shape(2023, shaping_exponent=1.0)
    sharp = half_hour_shape(2023, shaping_exponent=1.3)
    assert not np.allclose(broad.output_pu, sharp.output_pu)
    assert sharp.output_pu.max() > broad.output_pu.max()


def test_non_positive_shaping_exponent_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        half_hour_shape(2023, shaping_exponent=0)


def test_capture_rate_is_sensitive_to_shaping_exponent():
    broad = half_hour_shape(2023, shaping_exponent=1.0)
    prices = pd.DataFrame({
        "timestamp_utc": broad.timestamp_utc,
        "price_nzd_mwh": 40.0 + 100.0 * broad.output_pu,
    })
    broad_rate = yearly_capture_rates(prices, shaping_exponent=1.0).solar_capture_rate.iloc[0]
    sharp_rate = yearly_capture_rates(prices, shaping_exponent=1.3).solar_capture_rate.iloc[0]
    assert sharp_rate > broad_rate
    assert sharp_rate - broad_rate > 0.01
