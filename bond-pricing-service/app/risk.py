"""久期与凸性：与定价共用同一套「每期折现率」口径，时间一律以年计。

全服务统一的口径约定（r = 每期折现率 = ytm / 频率，m = 频率，t = 期序号）：

- 麦考利久期 = Σ (t/m) × PV_t / 全价                        —— 单位：年
- 修正久期   = 麦考利久期 / (1 + r)                          —— 单位：年
- 凸性       = Σ [t(t+1)/m²] × PV_t / [全价 × (1 + r)²]      —— 单位：年²

凸性的二阶权重 t(t+1)/m² 是把「期数」折算成「年」后的形式，保证它与
修正久期、年化收益率变动量 Δy 在同一个量纲下进入泰勒展开：

    ΔP/P ≈ -修正久期 × Δy + ½ × 凸性 × Δy²
"""

from __future__ import annotations

from dataclasses import dataclass

from .pricing import PricingResult


@dataclass(frozen=True)
class RiskMetrics:
    """利率风险指标，全部以年（或年²）为单位。"""

    dirty_price: float
    macaulay_duration: float  #: 麦考利久期（年）
    modified_duration: float  #: 修正久期（年）
    convexity: float  #: 凸性（年²）


def compute_risk_metrics(pricing: PricingResult) -> RiskMetrics:
    """在一次定价结果之上计算久期与凸性，保证与全价严格同源。"""
    spec = pricing.spec
    frequency = spec.frequency
    periodic_rate = spec.periodic_rate
    price = pricing.dirty_price

    macaulay = (
        sum(flow.cashflow.time_years * flow.present_value for flow in pricing.flows)
        / price
    )
    modified = macaulay / (1.0 + periodic_rate)
    convexity = sum(
        flow.cashflow.period
        * (flow.cashflow.period + 1)
        / (frequency * frequency)
        * flow.present_value
        for flow in pricing.flows
    ) / (price * (1.0 + periodic_rate) ** 2)

    return RiskMetrics(
        dirty_price=price,
        macaulay_duration=macaulay,
        modified_duration=modified,
        convexity=convexity,
    )
