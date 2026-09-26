"""定价层的正确性基准：平价关系、现值求和、单调性、现金流梯子形状。"""

from __future__ import annotations

import pytest

from app.cashflows import build_cashflow_ladder
from app.pricing import price_bond
from app.validation import validate_bond_inputs


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


class TestParBond:
    """票息率等于到期收益率时，全价必须等于面值——且与付息频率无关。"""

    @pytest.mark.parametrize("frequency", [1, 2, 4, 12])
    def test_par_bond_prices_at_face_value(self, frequency):
        spec = make_spec(frequency=frequency, coupon_rate=0.06, ytm=0.06)
        assert price_bond(spec).dirty_price == pytest.approx(100.0, abs=1e-9)

    def test_sample_bond_is_par(self):
        assert price_bond(make_spec()).dirty_price == pytest.approx(100.0, abs=1e-9)


class TestCashFlowLadder:
    def test_ladder_shape_and_amounts(self):
        spec = make_spec()
        ladder = build_cashflow_ladder(spec)
        assert len(ladder) == 10
        assert [cf.period for cf in ladder] == list(range(1, 11))
        # 每期票息 = 100 × 5% / 2 = 2.5，末期加面值
        assert all(cf.amount == pytest.approx(2.5) for cf in ladder[:-1])
        assert ladder[-1].amount == pytest.approx(102.5)
        # 时间以年计：第 t 期对应 t/2 年
        assert ladder[3].time_years == pytest.approx(2.0)
        assert ladder[-1].time_years == pytest.approx(5.0)

    def test_zero_coupon_ladder_has_single_payment(self):
        ladder = build_cashflow_ladder(make_spec(coupon_rate=0.0))
        assert all(cf.amount == 0.0 for cf in ladder[:-1])
        assert ladder[-1].amount == pytest.approx(100.0)


class TestDiscounting:
    def test_dirty_price_equals_sum_of_present_values(self):
        pricing = price_bond(make_spec(coupon_rate=0.06, ytm=0.04))
        total = sum(flow.present_value for flow in pricing.flows)
        assert pricing.dirty_price == pytest.approx(total, abs=1e-9)

    def test_discount_factors_match_periodic_rate_convention(self):
        spec = make_spec(ytm=0.05)
        pricing = price_bond(spec)
        for flow in pricing.flows:
            expected = (1.0 + 0.05 / 2) ** (-flow.cashflow.period)
            assert flow.discount_factor == pytest.approx(expected, rel=1e-12)

    def test_zero_coupon_price_is_closed_form(self):
        spec = make_spec(coupon_rate=0.0, ytm=0.06)
        expected = 100.0 / (1.0 + 0.06 / 2) ** 10
        assert price_bond(spec).dirty_price == pytest.approx(expected, rel=1e-12)


class TestYieldMonotonicity:
    """其它条件不变、仅抬高到期收益率时，全价必须严格下降。"""

    def test_price_decreases_as_yield_rises(self):
        spec_at = lambda y: make_spec(ytm=y, coupon_rate=0.05)
        yields = [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.20]
        prices = [price_bond(spec_at(y)).dirty_price for y in yields]
        for lower, higher in zip(prices, prices[1:]):
            assert higher < lower

    def test_premium_and_discount_straddle_par(self):
        assert price_bond(make_spec(ytm=0.03)).dirty_price > 100.0
        assert price_bond(make_spec(ytm=0.07)).dirty_price < 100.0
