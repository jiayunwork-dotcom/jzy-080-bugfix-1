"""敏感度估计：一阶 / 二阶 / 精确三者关系必须由重算印证，而非写死。"""

from __future__ import annotations

import pytest

from app.sensitivity import analyze_sensitivity
from app.validation import BondValidationError, validate_bond_inputs


def make_spec(**overrides):
    params = dict(
        face_value=100.0,
        coupon_rate=0.05,
        frequency=2,
        years_to_maturity=5.0,
        ytm=0.05,
    )
    params.update(overrides)
    return validate_bond_inputs(**params)


class TestSecondOrderBeatsFirstOrder:
    """凸性为正：收益率上行时一阶高估跌幅，二阶应更贴近精确价。"""

    @pytest.mark.parametrize("shift", [0.0005, 0.001, 0.005, 0.01, 0.02])
    def test_upward_shift(self, shift):
        report = analyze_sensitivity(make_spec(), shift)
        # 价格确实下跌，且一阶估计跌得比真实更多
        assert report.exact_price < report.base_price
        assert report.first_order_price < report.exact_price
        # 二阶估计的误差必须小于一阶
        assert abs(report.second_order_error) < abs(report.first_order_error)

    @pytest.mark.parametrize("shift", [-0.0005, -0.001, -0.005, -0.01])
    def test_downward_shift(self, shift):
        report = analyze_sensitivity(make_spec(), shift)
        # 收益率下行价格上涨；凸性为正 ⇒ 真实曲线在切线上方，
        # 一阶估计同样低估精确价，二阶依旧更贴近
        assert report.exact_price > report.base_price
        assert report.first_order_price < report.exact_price
        assert abs(report.second_order_error) < abs(report.first_order_error)

    def test_errors_are_reported_against_exact_price(self):
        report = analyze_sensitivity(make_spec(), 0.01)
        assert report.first_order_error == pytest.approx(
            report.first_order_price - report.exact_price
        )
        assert report.second_order_error == pytest.approx(
            report.second_order_price - report.exact_price
        )


class TestEdgeCases:
    def test_zero_shift_reproduces_base_price(self):
        report = analyze_sensitivity(make_spec(), 0.0)
        assert report.exact_price == pytest.approx(report.base_price, abs=1e-12)
        assert report.first_order_price == pytest.approx(report.base_price, abs=1e-12)
        assert report.second_order_price == pytest.approx(report.base_price, abs=1e-12)

    def test_shifted_yield_is_reported(self):
        report = analyze_sensitivity(make_spec(ytm=0.05), 0.0075)
        assert report.shifted_ytm == pytest.approx(0.0575)

    def test_shift_making_discount_factor_non_positive_is_rejected(self):
        with pytest.raises(BondValidationError):
            analyze_sensitivity(make_spec(ytm=0.01), -3.0)

    def test_non_finite_shift_is_rejected(self):
        with pytest.raises(BondValidationError):
            analyze_sensitivity(make_spec(), float("nan"))
