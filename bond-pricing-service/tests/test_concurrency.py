"""并发安全：多个请求的中间计算互不干扰、互不覆盖。

引擎核心是无共享状态的纯计算，这里用线程池并发驱动不同参数的请求，
断言每个并发结果与各自独立顺序计算的结果完全一致。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.pricing import price_bond
from app.risk import compute_risk_metrics
from app.sensitivity import analyze_sensitivity
from app.validation import validate_bond_inputs


def _workload() -> list[dict]:
    """构造一组互不相同的债券参数与收益率平移。"""
    return [
        dict(
            face_value=100.0 + 10.0 * i,
            coupon_rate=0.02 + 0.005 * (i % 7),
            frequency=(1, 2, 4, 12)[i % 4],
            years_to_maturity=float(1 + (i % 10)),
            ytm=0.01 + 0.004 * (i % 9),
            yield_shift=-0.005 + 0.0005 * i,
        )
        for i in range(40)
    ]


def _compute(params: dict) -> tuple:
    spec = validate_bond_inputs(
        face_value=params["face_value"],
        coupon_rate=params["coupon_rate"],
        frequency=params["frequency"],
        years_to_maturity=params["years_to_maturity"],
        ytm=params["ytm"],
    )
    pricing = price_bond(spec)
    risk = compute_risk_metrics(pricing)
    report = analyze_sensitivity(spec, params["yield_shift"])
    return (
        pricing.dirty_price,
        risk.macaulay_duration,
        risk.modified_duration,
        risk.convexity,
        report.first_order_price,
        report.second_order_price,
        report.exact_price,
    )


def test_concurrent_requests_do_not_interfere():
    workload = _workload()
    expected = [_compute(params) for params in workload]

    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(_compute, workload))

    assert actual == expected
