"""价格敏感度：一阶（修正久期）与二阶（叠加凸性）近似，对照精确重定价。

泰勒展开（口径与 risk 模块完全一致）：

    P(y + Δy) ≈ P(y) × [1 - 修正久期 × Δy]                      （一阶）
    P(y + Δy) ≈ P(y) × [1 - 修正久期 × Δy + ½ × 凸性 × Δy²]     （二阶）

由于凸性为正，收益率上行时一阶估计会高估跌幅；叠加凸性项后的二阶估计
应当更贴近用新收益率精确重定价的结果——这一关系由 ``analyze_sensitivity``
现场重算给出，而不是写死的结论。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .pricing import price_bond
from .risk import compute_risk_metrics
from .validation import BondSpec, validate_yield_shift


@dataclass(frozen=True)
class SensitivityReport:
    """一次收益率平移下，一阶 / 二阶 / 精确三种价格的对照。"""

    base_price: float  #: 平移前的全价
    yield_shift: float  #: 收益率变动量 Δy（小数）
    shifted_ytm: float  #: 平移后的到期收益率
    modified_duration: float  #: 用于一阶近似的修正久期
    convexity: float  #: 用于二阶近似的凸性
    first_order_price: float  #: 一阶近似价格
    second_order_price: float  #: 二阶近似价格
    exact_price: float  #: 用新收益率精确重定价的全价
    first_order_error: float  #: 一阶近似 − 精确价
    second_order_error: float  #: 二阶近似 − 精确价


def first_order_price(
    dirty_price: float, modified_duration: float, yield_shift: float
) -> float:
    """一阶近似：ΔP/P ≈ -修正久期 × Δy。"""
    return dirty_price * (1.0 - modified_duration * yield_shift)


def second_order_price(
    dirty_price: float,
    modified_duration: float,
    convexity: float,
    yield_shift: float,
) -> float:
    """二阶近似：ΔP/P ≈ -修正久期 × Δy + ½ × 凸性 × Δy²。"""
    return dirty_price * (
        1.0 - modified_duration * yield_shift + 0.5 * convexity * yield_shift**2
    )


def analyze_sensitivity(spec: BondSpec, yield_shift: float) -> SensitivityReport:
    """对同一只债，用三种口径各算一次价格并对照。

    精确价通过 ``price_bond`` 在平移后的收益率上重新贴现得到，
    与一阶 / 二阶近似共用同一套现金流与折现口径。
    """
    shifted_ytm = validate_yield_shift(spec, yield_shift)

    base = price_bond(spec)
    risk = compute_risk_metrics(base)
    exact = price_bond(replace(spec, ytm=shifted_ytm)).dirty_price

    first = first_order_price(base.dirty_price, risk.modified_duration, yield_shift)
    second = second_order_price(
        base.dirty_price, risk.modified_duration, risk.convexity, yield_shift
    )

    return SensitivityReport(
        base_price=base.dirty_price,
        yield_shift=yield_shift,
        shifted_ytm=shifted_ytm,
        modified_duration=risk.modified_duration,
        convexity=risk.convexity,
        first_order_price=first,
        second_order_price=second,
        exact_price=exact,
        first_order_error=first - exact,
        second_order_error=second - exact,
    )
