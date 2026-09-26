"""估值顺序无关性：一只券的结果只取决于它自己的参数。

回归背景：现金流梯子缓存曾以「面值 / 每期票息 / 期数」为键、漏掉付息频率，
导致票息与期数相同、频率不同的两只券共用同一条梯子，后算的那只继承前者的
time_years，麦考利久期、逐期明细时间与敏感度估计随之跑偏。

这里的每个用例都先把缓存清空、单独估值得到基线（等价于在新起的服务里
单发这一只），再按指定顺序交替估值，断言每个结果与基线逐项一致。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app import cashflows
from app.pricing import price_bond
from app.risk import compute_risk_metrics
from app.sensitivity import analyze_sensitivity
from app.validation import validate_bond_inputs


@pytest.fixture(autouse=True)
def clean_ladder_cache():
    """每个用例都从空缓存开始（等价于新起的服务），结束后不留残渣。"""
    cashflows._LADDER_CACHE.clear()
    yield
    cashflows._LADDER_CACHE.clear()


def make_spec(**overrides):
    params = dict(
        face_value=100.0,
        coupon_rate=0.04,
        frequency=1,
        years_to_maturity=10.0,
        ytm=0.06,
    )
    params.update(overrides)
    return validate_bond_inputs(**params)


#: 风控标红的那对券：每期票息都是 4.0、都是 10 期，仅频率不同
ANNUAL_BOND = dict(coupon_rate=0.04, frequency=1, years_to_maturity=10.0, ytm=0.06)
SEMIANNUAL_BOND = dict(coupon_rate=0.08, frequency=2, years_to_maturity=5.0, ytm=0.06)

#: 零息那对：每期票息都是 0、都是 10 期，仅频率不同
ZERO_ANNUAL = dict(coupon_rate=0.0, frequency=1, years_to_maturity=10.0, ytm=0.04)
ZERO_SEMIANNUAL = dict(coupon_rate=0.0, frequency=2, years_to_maturity=5.0, ytm=0.04)


def full_results(params, yield_shift=0.01):
    """一只券的全部对外结果：逐期明细、全价、久期、凸性、敏感度。"""
    spec = make_spec(**params)
    pricing = price_bond(spec)
    risk = compute_risk_metrics(pricing)
    report = analyze_sensitivity(spec, yield_shift)
    return {
        "times": tuple(flow.cashflow.time_years for flow in pricing.flows),
        "dirty_price": pricing.dirty_price,
        "macaulay_duration": risk.macaulay_duration,
        "modified_duration": risk.modified_duration,
        "convexity": risk.convexity,
        "first_order_price": report.first_order_price,
        "second_order_price": report.second_order_price,
        "exact_price": report.exact_price,
    }


def standalone_results(*param_sets, yield_shift=0.01):
    """在干净缓存上逐只单独估值，作为「新起的服务单发」的基线。"""
    cashflows._LADDER_CACHE.clear()
    baselines = []
    for params in param_sets:
        cashflows._LADDER_CACHE.clear()
        baselines.append(full_results(params, yield_shift))
    cashflows._LADDER_CACHE.clear()
    return baselines


class TestCouponBondPairEitherOrder:
    """年付 4%×10 年与半年付 8%×5 年，两种先后顺序都必须各自正确。"""

    def test_semiannual_first_then_annual(self):
        (semi_base, annual_base) = standalone_results(SEMIANNUAL_BOND, ANNUAL_BOND)
        assert full_results(SEMIANNUAL_BOND) == semi_base
        assert full_results(ANNUAL_BOND) == annual_base

    def test_annual_first_then_semiannual(self):
        (annual_base, semi_base) = standalone_results(ANNUAL_BOND, SEMIANNUAL_BOND)
        assert full_results(ANNUAL_BOND) == annual_base
        assert full_results(SEMIANNUAL_BOND) == semi_base

    def test_reported_values_after_semiannual_first(self):
        """半年付先算：年付券仍是麦考利 8.2815 / 修正 7.8127，而非 4.1407 / 3.9064。"""
        full_results(SEMIANNUAL_BOND)
        annual = full_results(ANNUAL_BOND)
        assert annual["macaulay_duration"] == pytest.approx(8.2815, abs=1e-4)
        assert annual["modified_duration"] == pytest.approx(7.8127, abs=1e-4)

    def test_reported_values_after_annual_first(self):
        """年付先算：半年付券仍是麦考利 4.2543 / 修正 4.1304，而非 8.5087 / 8.2609。"""
        full_results(ANNUAL_BOND)
        semi = full_results(SEMIANNUAL_BOND)
        assert semi["macaulay_duration"] == pytest.approx(4.2543, abs=1e-4)
        assert semi["modified_duration"] == pytest.approx(4.1304, abs=1e-4)

    def test_semiannual_schedule_times_after_annual_first(self):
        """年付先算后，半年付券的逐期时间仍是 0.5、1.0、…、5.0 年。"""
        full_results(ANNUAL_BOND)
        semi = full_results(SEMIANNUAL_BOND)
        assert semi["times"] == pytest.approx([0.5 * i for i in range(1, 11)])

    def test_sensitivity_after_annual_first(self):
        """年付先算后，半年付券 ±100bp 的敏感度仍是干净服务里的数值。"""
        full_results(ANNUAL_BOND)
        up = full_results(SEMIANNUAL_BOND, yield_shift=0.01)
        assert up["first_order_price"] == pytest.approx(104.0474, abs=1e-3)
        assert up["second_order_price"] == pytest.approx(104.1604, abs=1e-3)
        assert up["exact_price"] == pytest.approx(104.1583, abs=1e-3)

        down = full_results(SEMIANNUAL_BOND, yield_shift=-0.01)
        # 二阶近似必须比一阶更贴近精确重定价
        first_err = abs(down["first_order_price"] - down["exact_price"])
        second_err = abs(down["second_order_price"] - down["exact_price"])
        assert second_err < first_err


class TestZeroCouponPair:
    """10 年年付零息与 5 年半年付零息：后者久期必须恰好是 5 年。"""

    def test_annual_zero_first_then_semiannual_zero(self):
        (ten_year_base, five_year_base) = standalone_results(
            ZERO_ANNUAL, ZERO_SEMIANNUAL
        )
        assert full_results(ZERO_ANNUAL) == ten_year_base
        assert full_results(ZERO_SEMIANNUAL) == five_year_base

    def test_semiannual_zero_duration_is_its_maturity(self):
        full_results(ZERO_ANNUAL)
        five_year = full_results(ZERO_SEMIANNUAL)
        assert five_year["macaulay_duration"] == pytest.approx(5.0, abs=1e-9)

    def test_both_zeros_keep_their_own_maturity_as_duration(self):
        """无论谁先谁后，零息债麦考利久期都等于各自剩余年限。"""
        first, second = standalone_results(ZERO_ANNUAL, ZERO_SEMIANNUAL)
        assert first["macaulay_duration"] == pytest.approx(10.0, abs=1e-9)
        assert second["macaulay_duration"] == pytest.approx(5.0, abs=1e-9)


class TestConcurrentInterleaving:
    """交替并发地估值这对撞键的券，每个结果仍等于各自的干净基线。"""

    def test_interleaved_concurrent_valuations_match_standalone(self):
        (annual_base, semi_base) = standalone_results(ANNUAL_BOND, SEMIANNUAL_BOND)
        baselines = {tuple(sorted(ANNUAL_BOND.items())): annual_base,
                     tuple(sorted(SEMIANNUAL_BOND.items())): semi_base}

        def work(params):
            return full_results(params)

        workload = [ANNUAL_BOND, SEMIANNUAL_BOND] * 10
        with ThreadPoolExecutor(max_workers=8) as pool:
            actual = list(pool.map(work, workload))

        for params, result in zip(workload, actual):
            assert result == baselines[tuple(sorted(params.items()))]
