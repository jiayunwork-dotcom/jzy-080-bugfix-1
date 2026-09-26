"""贴现与全价：把现金流梯子按「每期折现率」逐期折成现值并求和。"""

from __future__ import annotations

from dataclasses import dataclass

from .cashflows import CashFlow, build_cashflow_ladder
from .validation import BondSpec


@dataclass(frozen=True)
class DiscountedCashFlow:
    """一期现金流及其贴现结果。"""

    cashflow: CashFlow
    discount_factor: float  #: (1 + 每期折现率) ^ (-期数)
    present_value: float  #: 现金流金额 × 折现因子


@dataclass(frozen=True)
class PricingResult:
    """一次定价的完整结果：逐期明细 + 全价。"""

    spec: BondSpec
    flows: tuple[DiscountedCashFlow, ...]
    dirty_price: float


def discount_cashflows(
    ladder: tuple[CashFlow, ...], periodic_rate: float
) -> tuple[DiscountedCashFlow, ...]:
    """逐期贴现：折现因子 = (1 + 每期折现率) ^ (-期数)。"""
    base = 1.0 + periodic_rate
    return tuple(
        DiscountedCashFlow(
            cashflow=cf,
            discount_factor=base ** (-cf.period),
            present_value=cf.amount * base ** (-cf.period),
        )
        for cf in ladder
    )


def price_bond(spec: BondSpec) -> PricingResult:
    """全价（脏价）= 各期现金流现值之和。"""
    ladder = build_cashflow_ladder(spec)
    flows = discount_cashflows(ladder, spec.periodic_rate)
    dirty_price = sum(flow.present_value for flow in flows)
    return PricingResult(spec=spec, flows=flows, dirty_price=dirty_price)
