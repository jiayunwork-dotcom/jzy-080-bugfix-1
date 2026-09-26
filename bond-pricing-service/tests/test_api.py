"""HTTP 接口行为：三个入口、示范债券、结构化错误响应。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sample import SAMPLE_BOND

client = TestClient(app)


class TestSampleEndpoint:
    def test_sample_bond_loads_and_prices_at_par(self):
        resp = client.get("/sample")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bond"] == SAMPLE_BOND
        # 平价关系可经服务自身复现
        assert body["engine_result"]["dirty_price"] == pytest.approx(100.0, abs=1e-9)


class TestPriceEndpoint:
    def test_par_bond_full_price_and_cashflow_detail(self):
        resp = client.post("/price", json=SAMPLE_BOND)
        assert resp.status_code == 200
        body = resp.json()
        assert body["dirty_price"] == pytest.approx(100.0, abs=1e-9)

        flows = body["cashflows"]
        assert len(flows) == 10
        assert flows[0]["period"] == 1
        assert flows[0]["cashflow"] == pytest.approx(2.5)
        assert flows[-1]["cashflow"] == pytest.approx(102.5)
        # 全价 = 逐期现值之和
        assert sum(f["present_value"] for f in flows) == pytest.approx(
            body["dirty_price"], abs=1e-9
        )

    def test_zero_coupon_macaulay_duration_via_risk_endpoint(self):
        payload = {**SAMPLE_BOND, "coupon_rate": 0.0}
        resp = client.post("/risk", json=payload)
        assert resp.status_code == 200
        assert resp.json()["macaulay_duration"] == pytest.approx(5.0, abs=1e-9)


class TestRiskEndpoint:
    def test_risk_metrics_of_sample_bond(self):
        resp = client.post("/risk", json=SAMPLE_BOND)
        assert resp.status_code == 200
        body = resp.json()
        assert body["dirty_price"] == pytest.approx(100.0, abs=1e-9)
        # 平价债闭式解：MacDur = (1/m)(1+r)/r [1 − (1+r)^(−n)]
        expected_mac = 0.5 * (1.025 / 0.025) * (1.0 - 1.025**-10)
        assert body["macaulay_duration"] == pytest.approx(expected_mac, rel=1e-9)
        assert body["modified_duration"] == pytest.approx(
            expected_mac / 1.025, rel=1e-9
        )
        assert body["convexity"] > 0.0


class TestSensitivityEndpoint:
    def test_second_order_tracks_exact_repricing(self):
        resp = client.post("/sensitivity", json={**SAMPLE_BOND, "yield_shift": 0.01})
        assert resp.status_code == 200
        body = resp.json()
        # 收益率上行 100bp：一阶高估跌幅，二阶更贴近精确重定价
        assert body["exact_price"] < body["base_price"]
        assert body["first_order_price"] < body["exact_price"]
        assert abs(body["second_order_error"]) < abs(body["first_order_error"])

    def test_zero_shift_gives_three_equal_prices(self):
        resp = client.post("/sensitivity", json={**SAMPLE_BOND, "yield_shift": 0.0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["first_order_price"] == pytest.approx(body["exact_price"])
        assert body["second_order_price"] == pytest.approx(body["exact_price"])


class TestStructuredErrors:
    def test_invalid_bond_input_returns_structured_422(self):
        payload = {**SAMPLE_BOND, "face_value": -100.0}
        resp = client.post("/price", json=payload)
        assert resp.status_code == 422
        error = resp.json()["error"]
        assert error["code"] == "INVALID_BOND_INPUT"
        assert error["details"]
        assert any("面值" in detail for detail in error["details"])

    def test_yield_breaking_discount_factor_returns_structured_422(self):
        payload = {**SAMPLE_BOND, "ytm": -2.0}
        resp = client.post("/risk", json=payload)
        assert resp.status_code == 422
        error = resp.json()["error"]
        assert error["code"] == "INVALID_BOND_INPUT"
        assert any("折现因子" in detail for detail in error["details"])

    def test_bad_shift_returns_structured_422(self):
        payload = {**SAMPLE_BOND, "ytm": 0.01, "yield_shift": -3.0}
        resp = client.post("/sensitivity", json=payload)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_BOND_INPUT"

    def test_malformed_request_returns_structured_422(self):
        resp = client.post("/price", json={"face_value": 100.0})
        assert resp.status_code == 422
        error = resp.json()["error"]
        assert error["code"] == "MALFORMED_REQUEST"
        assert error["details"]

    def test_health(self):
        assert client.get("/health").json() == {"status": "ok"}
