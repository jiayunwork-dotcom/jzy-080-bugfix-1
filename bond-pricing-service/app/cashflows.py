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


def build_cashflow_ladder(spec: BondSpec) -> tuple[CashFlow, ...]:
    """构建标准固定利率附息债的现金流梯子。

    每期支付票息 = 面值 × 年化票息率 / 频率；末期在票息之外同时偿还面值。

    纯函数：梯子只取决于 ``spec`` 自身，每次调用现场重建，不缓存、不共享——
    任何一只券的结果都与服务此前算过什么、以什么顺序算无关。
    """
    ladder = []
    for period in range(1, spec.periods + 1):
        amount = spec.coupon_per_period
        if period == spec.periods:
            amount += spec.face_value
        ladder.append(
            CashFlow(
                period=period,
                time_years=period / spec.frequency,
                amount=amount,
            )
        )
    return tuple(ladder)
