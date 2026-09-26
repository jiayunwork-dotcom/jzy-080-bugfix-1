"""对外 HTTP 接口：只做债券估值与利率风险计算，纯 JSON、无页面、无状态。

并发模型：所有端点都是无状态的纯计算——请求体在入口被校验并冻结为
不可变的 ``BondSpec``，随后每条请求在自己的调用栈里完成现金流构建、
贴现与风险核算，进程内没有任何共享可变状态，因此并发请求互不干扰。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .pricing import price_bond
from .risk import compute_risk_metrics
from .sample import SAMPLE_BOND, SAMPLE_DESCRIPTION
from .schemas import (
    BondRequest,
    CashFlowDetail,
    ErrorResponse,
    PriceResponse,
    RiskResponse,
    SensitivityRequest,
    SensitivityResponse,
)
from .sensitivity import analyze_sensitivity
from .validation import BondSpec, BondValidationError, validate_bond_inputs

app = FastAPI(
    title="Bond Valuation & Interest-Rate Risk Engine",
    description=(
        "固定利率附息债估值与利率风险核算引擎："
        "全价与逐期现值、麦考利/修正久期、凸性、一阶与二阶价格敏感度。"
    ),
    version=__version__,
)

HTTP_422 = 422

_VALIDATION_RESPONSE = {HTTP_422: {"model": ErrorResponse}}


def _to_spec(payload: BondRequest) -> BondSpec:
    """把请求体校验并冻结为 BondSpec；非法输入在此抛出 BondValidationError。"""
    return validate_bond_inputs(
        face_value=payload.face_value,
        coupon_rate=payload.coupon_rate,
        frequency=payload.frequency,
        years_to_maturity=payload.years_to_maturity,
        ytm=payload.ytm,
    )


@app.exception_handler(BondValidationError)
async def bond_validation_handler(
    request: Request, exc: BondValidationError
) -> JSONResponse:
    """业务口径校验失败 → 结构化 422。"""
    return JSONResponse(
        status_code=HTTP_422,
        content={
            "error": {
                "code": "INVALID_BOND_INPUT",
                "message": "债券参数未通过估值口径校验",
                "details": exc.errors,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求体不符合接口契约（缺字段、类型错误等）→ 结构化 422。"""
    details = [
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=HTTP_422,
        content={
            "error": {
                "code": "MALFORMED_REQUEST",
                "message": "请求体不符合接口契约",
                "details": details,
            }
        },
    )


@app.get("/health", summary="存活探针")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/sample", summary="内置示范债券（五年期平价债）及其引擎核算结果")
async def sample() -> dict:
    spec = _to_spec(BondRequest(**SAMPLE_BOND))
    pricing = price_bond(spec)
    risk = compute_risk_metrics(pricing)
    return {
        "description": SAMPLE_DESCRIPTION,
        "bond": SAMPLE_BOND,
        "engine_result": {
            "dirty_price": pricing.dirty_price,
            "macaulay_duration": risk.macaulay_duration,
            "modified_duration": risk.modified_duration,
            "convexity": risk.convexity,
        },
    }


@app.post(
    "/price",
    response_model=PriceResponse,
    responses=_VALIDATION_RESPONSE,
    summary="定价：全价 + 逐期现金流现值明细",
)
def price(payload: BondRequest) -> PriceResponse:
    spec = _to_spec(payload)
    pricing = price_bond(spec)
    return PriceResponse(
        dirty_price=pricing.dirty_price,
        cashflows=[
            CashFlowDetail(
                period=flow.cashflow.period,
                time_years=flow.cashflow.time_years,
                cashflow=flow.cashflow.amount,
                discount_factor=flow.discount_factor,
                present_value=flow.present_value,
            )
            for flow in pricing.flows
        ],
    )


@app.post(
    "/risk",
    response_model=RiskResponse,
    responses=_VALIDATION_RESPONSE,
    summary="利率风险：麦考利久期、修正久期、凸性",
)
def risk(payload: BondRequest) -> RiskResponse:
    spec = _to_spec(payload)
    metrics = compute_risk_metrics(price_bond(spec))
    return RiskResponse(
        dirty_price=metrics.dirty_price,
        macaulay_duration=metrics.macaulay_duration,
        modified_duration=metrics.modified_duration,
        convexity=metrics.convexity,
    )


@app.post(
    "/sensitivity",
    response_model=SensitivityResponse,
    responses=_VALIDATION_RESPONSE,
    summary="敏感度：一阶近似、二阶近似与精确重定价对照",
)
def sensitivity(payload: SensitivityRequest) -> SensitivityResponse:
    spec = _to_spec(payload)
    report = analyze_sensitivity(spec, payload.yield_shift)
    return SensitivityResponse(**asdict(report))
