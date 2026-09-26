"""输入校验：在任何计算发生之前，把非法参数挡在门外。

所有校验集中在 ``validate_bond_inputs`` / ``validate_yield_shift``，
通过校验的参数被冻结在不可变的 ``BondSpec`` 里。下游计算模块只接受
``BondSpec``，从而保证「未校验的数据不会进入定价流水线」。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 支持的每年付息次数（市场常见惯例）
SUPPORTED_FREQUENCIES: tuple[int, ...] = (1, 2, 4, 12)

#: 剩余到期年数上限，防止超长现金流梯子拖垮服务
MAX_YEARS_TO_MATURITY: float = 100.0

#: 「到期年数 × 频率」与最近整数的容差，超出即认为不对应整数个付息期
_PERIOD_ROUND_TOLERANCE = 1e-6


class BondValidationError(ValueError):
    """输入参数违反估值口径时抛出，携带全部错误说明（可能不止一条）。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class BondSpec:
    """已通过校验的债券参数，是所有计算模块的唯一输入。

    口径约定（全服务统一）：
    - 每期折现率 = 年化到期收益率 / 付息频率；
    - 每期票息   = 面值 × 年化票息率 / 付息频率；
    - 第 t 期对应的时间（年）= t / 付息频率。
    """

    face_value: float
    coupon_rate: float
    frequency: int
    years_to_maturity: float
    ytm: float

    @property
    def periods(self) -> int:
        """总付息期数（校验已保证其为正整数）。"""
        return int(round(self.years_to_maturity * self.frequency))

    @property
    def periodic_rate(self) -> float:
        """每期折现率 = 年化到期收益率 / 付息频率。"""
        return self.ytm / self.frequency

    @property
    def coupon_per_period(self) -> float:
        """每期票息 = 面值 × 年化票息率 / 付息频率。"""
        return self.face_value * self.coupon_rate / self.frequency


def _check_finite(name: str, value: float, errors: list[str]) -> bool:
    if not math.isfinite(value):
        errors.append(f"{name} 必须是有限数值，收到 {value!r}")
        return False
    return True


def validate_bond_inputs(
    *,
    face_value: float,
    coupon_rate: float,
    frequency: int,
    years_to_maturity: float,
    ytm: float,
) -> BondSpec:
    """校验债券参数；全部通过则返回冻结的 ``BondSpec``，否则一次性抛出全部错误。"""
    errors: list[str] = []

    # NaN / 无穷大会污染后续所有比较，先替换为 0 再继续收集其余错误
    if not _check_finite("面值 face_value", face_value, errors):
        face_value = 0.0
    if not _check_finite("票息率 coupon_rate", coupon_rate, errors):
        coupon_rate = 0.0
    if not _check_finite("剩余到期年数 years_to_maturity", years_to_maturity, errors):
        years_to_maturity = 0.0
    if not _check_finite("到期收益率 ytm", ytm, errors):
        ytm = 0.0

    if face_value <= 0.0:
        errors.append(f"面值必须为正数，收到 {face_value}")
    if coupon_rate < 0.0:
        errors.append(f"票息率不得为负，收到 {coupon_rate}")
    if not isinstance(frequency, int) or frequency not in SUPPORTED_FREQUENCIES:
        errors.append(
            f"付息频率只支持 {SUPPORTED_FREQUENCIES}（次/年），收到 {frequency!r}"
        )
    if years_to_maturity <= 0.0:
        errors.append(f"剩余到期年数必须为正数，收到 {years_to_maturity}")
    elif years_to_maturity > MAX_YEARS_TO_MATURITY:
        errors.append(
            f"剩余到期年数不得超过 {MAX_YEARS_TO_MATURITY} 年，收到 {years_to_maturity}"
        )

    # 以下两项依赖频率与年数本身合法，避免用垃圾中间值继续推导
    if isinstance(frequency, int) and frequency in SUPPORTED_FREQUENCIES:
        if years_to_maturity > 0.0:
            raw_periods = years_to_maturity * frequency
            nearest = int(round(raw_periods))
            if nearest < 1 or abs(raw_periods - nearest) > _PERIOD_ROUND_TOLERANCE:
                errors.append(
                    "剩余到期年数必须对应整数个付息期："
                    f"{years_to_maturity} 年 × 每年 {frequency} 期 = {raw_periods} 期"
                )
        if 1.0 + ytm / frequency <= 0.0:
            errors.append(
                "到期收益率过低导致折现因子非正："
                f"要求 1 + ytm/频率 > 0，当前 1 + ({ytm})/{frequency} = "
                f"{1.0 + ytm / frequency}"
            )

    if errors:
        raise BondValidationError(errors)

    return BondSpec(
        face_value=face_value,
        coupon_rate=coupon_rate,
        frequency=frequency,
        years_to_maturity=years_to_maturity,
        ytm=ytm,
    )


def validate_yield_shift(spec: BondSpec, yield_shift: float) -> float:
    """校验收益率变动量，返回平移后的新到期收益率。

    平移后的收益率同样必须满足折现因子为正，否则无法精确重定价。
    """
    if not math.isfinite(yield_shift):
        raise BondValidationError(
            [f"收益率变动量必须是有限数值，收到 {yield_shift!r}"]
        )
    shifted_ytm = spec.ytm + yield_shift
    if 1.0 + shifted_ytm / spec.frequency <= 0.0:
        raise BondValidationError(
            [
                "收益率平移后折现因子非正，无法重新定价："
                f"新收益率 {shifted_ytm}（= {spec.ytm} + {yield_shift}），"
                f"要求 1 + 新收益率/频率 > 0，当前 "
                f"{1.0 + shifted_ytm / spec.frequency}"
            ]
        )
    return shifted_ytm
