"""估值结果与历史无关：任意先后、任意穿插之后，每只券都必须和单独估值一致。

回归背景：现金流梯子曾按（面值、每期票息、期数）做进程内缓存，键里漏掉了
付息频率。下面两组券的（面值、每期票息、期数）完全相同、仅频率不同，因而
共用同一把缓存梯子——后算的一只继承先算一只的 time_years，麦考利/修正久期
被整体缩放（8.2815 ↔ 4.1407、4.2543 ↔ 8.5087），全价与凸性却不受影响。
这里把事故中的参数、两种先后顺序、零息组合与并发穿插全部钉死。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pricing import price_bond
from app.risk import compute_risk_metrics
from app.sensitivity import analyze_sensitivity
from app.validation import validate_bond_inputs

# 事故中的两只附息债：每期票息都是 100 × 票息率 / 频率 = 4.0，期数都是 10，
# 仅付息频率不同——正是这把「同钥匙、不同梯子」的组合触发了缓存串扰。
ANNUAL_BOND = dict(
    face_value=100.0, coupon_rate=0.04, frequency=1, years_to_maturity=10.0, ytm=0.06
)
SEMI_BOND = dict(
    face_value=100.0, coupon_rate=0.08, frequency=2, years_to_maturity=5.0, ytm=0.06
)

# 事故中的两只零息债：（面值、每期票息、期数）= (100, 0.0, 10)，同样仅频率不同。
ZERO_10Y_ANNUAL = dict(
    face_value=100.0, coupon_rate=0.0, frequency=1, years_to_maturity=10.0, ytm=0.04
)
ZERO_5Y_SEMI = dict(
    face_value=100.0, coupon_rate=0.0, frequency=2, years_to_maturity=5.0, ytm=0.04
)

#: 新起服务单独估值时的事故现场基准值（全价、麦考利久期、修正久期、凸性）
STANDALONE = {
    "annual": (85.2798, 8.2815, 7.8127, 75.8864),
    "semi": (108.5302, 4.2543, 4.1304, 20.8170),
}


def reference_metrics(params: dict) -> dict:
    """独立于引擎实现的口径基准：从合同现金流定义直接折现，不经过引擎的梯子。"""
    m = params["frequency"]
    r = params["ytm"] / m
    n = int(round(params["years_to_maturity"] * m))
    coupon = params["face_value"] * params["coupon_rate"] / m

    price = macaulay_num = convexity_num = 0.0
    for period in range(1, n + 1):
        amount = coupon + (params["face_value"] if period == n else 0.0)
        pv = amount / (1.0 + r) ** period
        price += pv
        macaulay_num += (period / m) * pv
        convexity_num += period * (period + 1) / (m * m) * pv
    macaulay = macaulay_num / price
    return {
        "dirty_price": price,
        "macaulay_duration": macaulay,
        "modified_duration": macaulay / (1.0 + r),
        "convexity": convexity_num / (price * (1.0 + r) ** 2),
    }


def full_valuation(params: dict, yield_shift: float = 0.01) -> dict:
    """走引擎完整流水线：定价 + 逐期明细 + 久期凸性 + 敏感度。"""
    spec = validate_bond_inputs(**params)
    pricing = price_bond(spec)
    risk = compute_risk_metrics(pricing)
    report = analyze_sensitivity(spec, yield_shift)
    return {
        "dirty_price": pricing.dirty_price,
        "time_years": [flow.cashflow.time_years for flow in pricing.flows],
        "macaulay_duration": risk.macaulay_duration,
        "modified_duration": risk.modified_duration,
        "convexity": risk.convexity,
        "report": report,
    }


def assert_matches_reference(result: dict, params: dict) -> None:
    """引擎结果必须与独立基准在数值精度内完全一致。"""
    ref = reference_metrics(params)
    for key in ("dirty_price", "macaulay_duration", "modified_duration", "convexity"):
        assert result[key] == pytest.approx(ref[key], rel=1e-12), key


class TestCouponBondPairBothOrders:
    """两种先后顺序下，两只券的全部结果都必须等于各自单独估值的值。"""

    @pytest.mark.parametrize(
        "first,second",
        [(ANNUAL_BOND, SEMI_BOND), (SEMI_BOND, ANNUAL_BOND)],
        ids=["年付在前", "半年付在前"],
    )
    def test_results_do_not_depend_on_order(self, first, second):
        for params in (first, second):
            result = full_valuation(params)
            assert_matches_reference(result, params)

            n = int(round(params["years_to_maturity"] * params["frequency"]))
            expected_times = [(t + 1) / params["frequency"] for t in range(n)]
            assert result["time_years"] == pytest.approx(expected_times)

    def test_interleaved_repeatedly_every_result_matches_standalone(self):
        for _ in range(5):
            for params in (ANNUAL_BOND, SEMI_BOND):
                assert_matches_reference(full_valuation(params), params)

    @pytest.mark.parametrize(
        "params,standalone",
        [(ANNUAL_BOND, STANDALONE["annual"]), (SEMI_BOND, STANDALONE["semi"])],
        ids=["年付券", "半年付券"],
    )
    def test_incident_standalone_numbers_after_other_bond_priced(self, params, standalone):
        other = SEMI_BOND if params is ANNUAL_BOND else ANNUAL_BOND
        full_valuation(other)  # 先算另一只，再算本只——事故现场的情形
        price, macaulay, modified, convexity = standalone
        result = full_valuation(params)
        assert result["dirty_price"] == pytest.approx(price, abs=1e-4)
        assert result["macaulay_duration"] == pytest.approx(macaulay, abs=1e-4)
        assert result["modified_duration"] == pytest.approx(modified, abs=1e-4)
        assert result["convexity"] == pytest.approx(convexity, abs=1e-4)


class TestZeroCouponPair:
    """零息债的麦考利久期必须恰好等于剩余年限，与先算过哪只零息债无关。"""

    @pytest.mark.parametrize(
        "first,second",
        [(ZERO_10Y_ANNUAL, ZERO_5Y_SEMI), (ZERO_5Y_SEMI, ZERO_10Y_ANNUAL)],
        ids=["10年在前", "5年在前"],
    )
    def test_macaulay_duration_equals_own_maturity(self, first, second):
        for params in (first, second):
            result = full_valuation(params)
            assert result["macaulay_duration"] == pytest.approx(
                params["years_to_maturity"], abs=1e-9
            )
            assert_matches_reference(result, params)


class TestSensitivityAfterOtherBonds:
    """穿插估值之后，敏感度近似与精确重定价的关系必须仍然成立。"""

    @pytest.mark.parametrize("shift", [0.01, -0.01], ids=["上移100bp", "下移100bp"])
    def test_second_order_stays_closer_than_first_order(self, shift):
        full_valuation(ANNUAL_BOND)  # 先算年付券，再对半年付券做敏感度——事故顺序
        report = full_valuation(SEMI_BOND, yield_shift=shift)["report"]

        exact_ref = reference_metrics({**SEMI_BOND, "ytm": SEMI_BOND["ytm"] + shift})
        assert report.exact_price == pytest.approx(exact_ref["dirty_price"], rel=1e-12)
        # 凸性为正 ⇒ 二阶近似必须比一阶更贴近精确重定价
        assert abs(report.second_order_error) < abs(report.first_order_error)

    def test_sensitivity_report_is_order_independent(self):
        before = full_valuation(SEMI_BOND, yield_shift=0.01)["report"]
        full_valuation(ANNUAL_BOND)
        after = full_valuation(SEMI_BOND, yield_shift=0.01)["report"]
        assert before == after


class TestConcurrentInterleaving:
    """两组「同钥匙、不同梯子」的券交替并发打入，每个结果都必须等于独立基准。"""

    @staticmethod
    def _risk_tuple(params: dict) -> tuple:
        spec = validate_bond_inputs(**params)
        risk = compute_risk_metrics(price_bond(spec))
        return (
            risk.dirty_price,
            risk.macaulay_duration,
            risk.modified_duration,
            risk.convexity,
        )

    def test_concurrent_alternating_bonds_match_standalone(self):
        workload = [ANNUAL_BOND, SEMI_BOND, ZERO_10Y_ANNUAL, ZERO_5Y_SEMI] * 10
        with ThreadPoolExecutor(max_workers=8) as pool:
            actual = list(pool.map(self._risk_tuple, workload))

        for params, got in zip(workload, actual):
            ref = reference_metrics(params)
            assert got == pytest.approx(
                (
                    ref["dirty_price"],
                    ref["macaulay_duration"],
                    ref["modified_duration"],
                    ref["convexity"],
                ),
                rel=1e-12,
            )
        # 纯函数对同一输入必须逐位一致：同一只券的 10 份结果完全相等
        for i in range(4):
            copies = [actual[j] for j in range(i, len(workload), 4)]
            assert all(copy == copies[0] for copy in copies)


class TestApiOrderIndependence:
    """经 HTTP 接口按事故顺序批量估值，响应必须与单独估值一致。"""

    client = TestClient(app)

    @pytest.mark.parametrize(
        "first,second",
        [(ANNUAL_BOND, SEMI_BOND), (SEMI_BOND, ANNUAL_BOND)],
        ids=["年付在前", "半年付在前"],
    )
    def test_risk_and_price_endpoints_are_order_independent(self, first, second):
        for params in (first, second):
            risk_body = self.client.post("/risk", json=params).json()
            ref = reference_metrics(params)
            assert risk_body["macaulay_duration"] == pytest.approx(
                ref["macaulay_duration"], rel=1e-12
            )
            assert risk_body["modified_duration"] == pytest.approx(
                ref["modified_duration"], rel=1e-12
            )
            assert risk_body["convexity"] == pytest.approx(ref["convexity"], rel=1e-12)

            price_body = self.client.post("/price", json=params).json()
            assert price_body["dirty_price"] == pytest.approx(
                ref["dirty_price"], rel=1e-12
            )
            times = [flow["time_years"] for flow in price_body["cashflows"]]
            n = int(round(params["years_to_maturity"] * params["frequency"]))
            assert times == pytest.approx(
                [(t + 1) / params["frequency"] for t in range(n)]
            )
