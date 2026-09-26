"""现金流梯子的构建：只负责「哪一期、距现在几年、付多少钱」，不做贴现。"""

from __future__ import annotations

from dataclasses import dataclass

from .validation import BondSpec


@dataclass(frozen=True)
class CashFlow:
    """一期合同现金流。"""

    period: int  #: 期序号，从 1 开始
    time_years: float  #: 距估值日的时间（年）= period / frequency
    amount: float  #: 当期现金流金额（末期 = 票息 + 面值）


#: 梯子与收益率无关，同一组面值 / 每期票息 / 期数可直接复用（元素不可变，线程间共享安全）
_LADDER_CACHE: dict[tuple[float, float, int], tuple[CashFlow, ...]] = {}


def build_cashflow_ladder(spec: BondSpec) -> tuple[CashFlow, ...]:
    """构建标准固定利率附息债的现金流梯子。

    每期支付票息 = 面值 × 年化票息率 / 频率；末期在票息之外同时偿还面值。
    """
    periods = spec.periods
    coupon = spec.coupon_per_period
    key = (spec.face_value, coupon, periods)
    cached = _LADDER_CACHE.get(key)
    if cached is not None:
        return cached
    ladder = []
    for period in range(1, periods + 1):
        amount = coupon
        if period == periods:
            amount += spec.face_value
        ladder.append(
            CashFlow(
                period=period,
                time_years=period / spec.frequency,
                amount=amount,
            )
        )
    result = tuple(ladder)
    _LADDER_CACHE[key] = result
    return result
