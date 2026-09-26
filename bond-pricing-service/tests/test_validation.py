"""输入校验：非法组合必须在计算前被拒，并携带清晰的错误说明。"""

from __future__ import annotations

import pytest

from app.validation import (
    BondValidationError,
    validate_bond_inputs,
    validate_yield_shift,
)

VALID = dict(
    face_value=100.0,
    coupon_rate=0.05,
    frequency=2,
    years_to_maturity=5.0,
    ytm=0.05,
)


def validate(**overrides):
    params = {**VALID, **overrides}
    return validate_bond_inputs(**params)


class TestRejectsInvalidInputs:
    @pytest.mark.parametrize("face_value", [0.0, -100.0, -0.01])
    def test_non_positive_face_value(self, face_value):
        with pytest.raises(BondValidationError, match="面值"):
            validate(face_value=face_value)

    @pytest.mark.parametrize("years", [0.0, -1.0, -5.0])
    def test_non_positive_years_to_maturity(self, years):
        with pytest.raises(BondValidationError, match="到期年数"):
            validate(years_to_maturity=years)

    def test_negative_coupon_rate(self):
        with pytest.raises(BondValidationError, match="票息率"):
            validate(coupon_rate=-0.01)

    @pytest.mark.parametrize("ytm", [-2.0, -3.5])
    def test_yield_making_discount_factor_non_positive(self, ytm):
        # 频率 2 时，1 + ytm/2 <= 0 即 ytm <= -2
        with pytest.raises(BondValidationError, match="折现因子"):
            validate(ytm=ytm)

    def test_non_integer_periods_rejected(self):
        # 2.5 年 × 每年 1 期 = 2.5 期，不是整数个付息期
        with pytest.raises(BondValidationError, match="整数个付息期"):
            validate(frequency=1, years_to_maturity=2.5)

    @pytest.mark.parametrize("frequency", [0, 3, 7, 365, -2])
    def test_unsupported_frequency(self, frequency):
        with pytest.raises(BondValidationError, match="付息频率"):
            validate(frequency=frequency)

    @pytest.mark.parametrize("field", ["face_value", "coupon_rate", "ytm"])
    def test_non_finite_values(self, field):
        with pytest.raises(BondValidationError, match="有限数值"):
            validate(**{field: float("nan")})
        with pytest.raises(BondValidationError, match="有限数值"):
            validate(**{field: float("inf")})

    def test_multiple_errors_reported_together(self):
        with pytest.raises(BondValidationError) as exc_info:
            validate(face_value=-1.0, coupon_rate=-0.05, years_to_maturity=0.0)
        assert len(exc_info.value.errors) >= 3


class TestAcceptsBoundaryInputs:
    def test_zero_coupon_is_allowed(self):
        assert validate(coupon_rate=0.0).coupon_rate == 0.0

    def test_zero_yield_is_allowed(self):
        assert validate(ytm=0.0).ytm == 0.0

    def test_mildly_negative_yield_is_allowed(self):
        # 1 + (-0.5)/2 = 0.75 > 0，折现因子仍为正
        assert validate(ytm=-0.5).ytm == -0.5

    def test_spec_is_frozen(self):
        spec = validate()
        with pytest.raises(AttributeError):
            spec.ytm = 0.99  # type: ignore[misc]


class TestYieldShiftValidation:
    def test_shifted_yield_must_keep_discount_factor_positive(self):
        spec = validate(ytm=0.01)
        with pytest.raises(BondValidationError, match="折现因子"):
            validate_yield_shift(spec, -3.0)

    def test_valid_shift_returns_shifted_yield(self):
        spec = validate(ytm=0.05)
        assert validate_yield_shift(spec, 0.01) == pytest.approx(0.06)
