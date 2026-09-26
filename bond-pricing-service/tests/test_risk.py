"""久期与凸性的口径基准：零息债久期、平价债闭式解、频率加密后的自洽性。"""

from __future__ import annotations

import pytest

from app.pricing import price_bond
from app.risk import compute_risk_metrics
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


def risk_of(spec):
    return compute_risk_metrics(price_bond(spec))


class TestZeroCouponDuration:
    """零息债只有一次现金流，麦考利久期必须恰好等于剩余到期年数。"""

    @pytest.mark.parametrize(
        "years,frequency", [(5.0, 2), (3.0, 1), (7.5, 2), (1.0, 12), (10.0, 4)]
    )
    def test_macaulay_duration_equals_maturity(self, years, frequency):
        spec = make_spec(
            coupon_rate=0.0, years_to_maturity=years, frequency=frequency
        )
        metrics = risk_of(spec)
        assert metrics.macaulay_duration == pytest.approx(years, abs=1e-9)

    def test_zero_coupon_convexity_closed_form(self):
        # 单笔现金流：凸性 = n(n+1) / (m²(1+r)²)
        spec = make_spec(coupon_rate=0.0, years_to_maturity=5.0, frequency=2, ytm=0.06)
        metrics = risk_of(spec)
        n, m, r = 10, 2, 0.06 / 2
        expected = n * (n + 1) / (m * m) / (1.0 + r) ** 2
        assert metrics.convexity == pytest.approx(expected, rel=1e-9)


class TestParBondClosedForm:
    """用独立于引擎实现的闭式解锁定示范债券的久期数值。"""

    def test_macaulay_duration_matches_closed_form(self):
        # 平价债麦考利久期（年）= (1/m) × (1+r)/r × [1 − (1+r)^(−n)]
        m, r, n = 2, 0.025, 10
        expected = (1.0 / m) * (1.0 + r) / r * (1.0 - (1.0 + r) ** (-n))
        metrics = risk_of(make_spec())
        assert metrics.macaulay_duration == pytest.approx(expected, rel=1e-9)

    def test_modified_duration_is_macaulay_over_one_plus_periodic_rate(self):
        metrics = risk_of(make_spec())
        assert metrics.modified_duration == pytest.approx(
            metrics.macaulay_duration / 1.025, rel=1e-12
        )

    def test_convexity_is_positive(self):
        assert risk_of(make_spec()).convexity > 0.0


class TestFrequencyDensification:
    """付息频率成倍加密、年化票息与年化收益率不变时，口径必须自洽。"""

    @pytest.mark.parametrize("frequency", [1, 2, 4, 12])
    def test_internal_consistency_at_every_frequency(self, frequency):
        spec = make_spec(frequency=frequency, coupon_rate=0.06, ytm=0.05)
        pricing = price_bond(spec)
        metrics = compute_risk_metrics(pricing)
        r = spec.ytm / frequency

        # 全价 = 逐期现值之和
        assert metrics.dirty_price == pytest.approx(
            sum(f.present_value for f in pricing.flows), abs=1e-9
        )
        # 修正久期 = 麦考利久期 / (1 + 每期折现率)
        assert metrics.modified_duration == pytest.approx(
            metrics.macaulay_duration / (1.0 + r), rel=1e-12
        )
        # 二阶泰勒估计在小幅度平移下必须贴近精确重定价，
        # 这把全价、久期、凸性锁进同一套口径
        shift = 0.001
        exact = price_bond(
            make_spec(frequency=frequency, coupon_rate=0.06, ytm=0.05 + shift)
        ).dirty_price
        second_order = metrics.dirty_price * (
            1.0 - metrics.modified_duration * shift + 0.5 * metrics.convexity * shift**2
        )
        assert second_order == pytest.approx(exact, abs=1e-4)

    def test_par_bond_stays_at_face_across_frequencies(self):
        for frequency in (1, 2, 4, 12):
            spec = make_spec(frequency=frequency, coupon_rate=0.05, ytm=0.05)
            assert price_bond(spec).dirty_price == pytest.approx(100.0, abs=1e-9)

    def test_prices_converge_as_frequency_doubles(self):
        # 非平价债：频率加密时全价应收敛，相邻档差距逐步缩小
        prices = [
            price_bond(make_spec(frequency=f, coupon_rate=0.06, ytm=0.05)).dirty_price
            for f in (1, 2, 4, 12)
        ]
        gaps = [abs(b - a) for a, b in zip(prices, prices[1:])]
        assert gaps[0] > gaps[1] > gaps[2]
