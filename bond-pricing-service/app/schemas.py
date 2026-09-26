"""HTTP 层的请求 / 响应模型（Pydantic），只描述线格式，不含计算逻辑。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BondRequest(BaseModel):
    """标准固定利率附息债的估值输入（年化利率一律用小数，如 5% = 0.05）。"""

    face_value: float = Field(..., description="面值，必须为正", examples=[100.0])
    coupon_rate: float = Field(
        ..., description="年化票息率（小数），不得为负", examples=[0.05]
    )
    frequency: int = Field(
        ..., description="每年付息次数，支持 1 / 2 / 4 / 12", examples=[2]
    )
    years_to_maturity: float = Field(
        ..., description="剩余到期年数，需对应整数个付息期", examples=[5.0]
    )
    ytm: float = Field(
        ..., description="年化到期收益率（小数）", examples=[0.05]
    )


class CashFlowDetail(BaseModel):
    """逐期现金流现值明细。"""

    period: int = Field(..., description="期序号，从 1 开始")
    time_years: float = Field(..., description="距估值日的时间（年）")
    cashflow: float = Field(..., description="当期现金流金额（末期含面值）")
    discount_factor: float = Field(..., description="折现因子 (1+r)^(-期数)")
    present_value: float = Field(..., description="当期现值")


class PriceResponse(BaseModel):
    dirty_price: float = Field(..., description="全价 = 各期现值之和")
    cashflows: list[CashFlowDetail] = Field(..., description="逐期现值明细")


class RiskResponse(BaseModel):
    dirty_price: float = Field(..., description="全价")
    macaulay_duration: float = Field(..., description="麦考利久期（年）")
    modified_duration: float = Field(..., description="修正久期（年）")
    convexity: float = Field(..., description="凸性（年²）")


class SensitivityRequest(BondRequest):
    yield_shift: float = Field(
        ...,
        description="收益率变动量（小数），如 0.01 表示上行 100bp",
        examples=[0.01],
    )


class SensitivityResponse(BaseModel):
    base_price: float = Field(..., description="平移前的全价")
    yield_shift: float = Field(..., description="收益率变动量")
    shifted_ytm: float = Field(..., description="平移后的到期收益率")
    modified_duration: float = Field(..., description="修正久期（年）")
    convexity: float = Field(..., description="凸性（年²）")
    first_order_price: float = Field(..., description="一阶近似价格（仅修正久期）")
    second_order_price: float = Field(..., description="二阶近似价格（久期 + 凸性）")
    exact_price: float = Field(..., description="用新收益率精确重定价的全价")
    first_order_error: float = Field(..., description="一阶近似 − 精确价")
    second_order_error: float = Field(..., description="二阶近似 − 精确价")


class ErrorBody(BaseModel):
    code: str = Field(..., description="机器可读的错误码")
    message: str = Field(..., description="错误概述")
    details: list[str] = Field(..., description="逐条错误说明")


class ErrorResponse(BaseModel):
    """统一的结构化错误响应。"""

    error: ErrorBody
