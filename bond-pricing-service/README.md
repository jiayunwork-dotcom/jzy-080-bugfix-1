# Bond Pricing Service — 债券估值与利率风险核算引擎

面向内网长期运行的 HTTP 核算服务：对标准固定利率附息债给出**全价、逐期现金流现值、麦考利久期、修正久期、凸性**，以及**一阶 / 二阶价格敏感度与精确重定价对照**。只做估值与利率风险计算这一件事：纯 JSON 接口、无页面、无账户 / 持仓 / 成交概念。

## 计价口径（全服务统一固定）

约定：面值 `F`、年化票息率 `c`、每年付息 `m` 次、剩余 `n` 期、年化到期收益率 `y`，每期折现率 `r = y / m`。

| 项目 | 公式 |
| --- | --- |
| 每期票息 | `F · c / m`（末期另加面值 `F`） |
| 折现因子 | `(1 + r)^(−t)`，第 `t` 期 |
| 全价（脏价） | `P = Σ CF_t · (1+r)^(−t)` |
| 麦考利久期 | `Σ (t/m) · PV_t / P`（年） |
| 修正久期 | `MacDur / (1 + r)`（年） |
| 凸性 | `Σ [t(t+1)/m²] · PV_t / [P · (1+r)²]`（年²） |
| 一阶近似 | `P · (1 − ModDur · Δy)` |
| 二阶近似 | `P · (1 − ModDur · Δy + ½ · Conv · Δy²)` |

时间一律以年计、折现一律按每期折现率，定价 / 久期 / 凸性 / 敏感度四处共用同一套口径。凸性为正，因此收益率上行时一阶估计高估跌幅，二阶估计更贴近精确重定价——这一关系由 `/sensitivity` 现场重算给出，并有测试锁定。

## 工程结构（职责边界）

```
app/
├── validation.py    # 输入校验：非法参数在计算前被拒，冻结为不可变 BondSpec
├── cashflows.py     # 现金流梯子构建（哪一期付多少钱）
├── pricing.py       # 贴现与全价（逐期现值明细）
├── risk.py          # 麦考利 / 修正久期、凸性
├── sensitivity.py   # 一阶 / 二阶近似与精确重定价对照
├── sample.py        # 内置示范债券（五年期平价债）
├── schemas.py       # HTTP 请求 / 响应模型
└── main.py          # FastAPI 路由与结构化错误处理
tests/               # 定价、风险、敏感度、校验、API、并发六组测试
```

## 快速开始（容器，单条命令）

```bash
docker compose up --build
```

或纯 Docker：

```bash
docker build -t bond-pricing-service . && docker run --rm -p 8000:8000 bond-pricing-service
```

服务监听 `http://localhost:8000`，交互式接口文档在 `/docs`（OpenAPI JSON 在 `/openapi.json`）。多核部署可用 `uvicorn app.main:app --workers N` 水平扩展——引擎无共享状态，并发请求的中间计算互不干扰。

本地开发（非容器）：

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8000
pytest            # 运行全部测试
```

## 接口一览

所有利率均为年化小数（5% = 0.05），`frequency` 支持 1 / 2 / 4 / 12。

### `GET /sample` — 内置示范债券

返回五年期平价债（面值 100、票息 5%、半年付息、收益率 5%）的参数与引擎核算结果，可手工核对：全价恰为 100，每期票息 2.5，共 10 期。

### `POST /price` — 定价

```bash
curl -s localhost:8000/price -H 'Content-Type: application/json' -d '{
  "face_value": 100, "coupon_rate": 0.05, "frequency": 2,
  "years_to_maturity": 5, "ytm": 0.05
}'
```

返回 `dirty_price` 与逐期 `cashflows`（期序号、时间、现金流、折现因子、现值）。

### `POST /risk` — 久期与凸性

请求体同上，返回 `dirty_price`、`macaulay_duration`、`modified_duration`、`convexity`。

### `POST /sensitivity` — 敏感度对照

```bash
curl -s localhost:8000/sensitivity -H 'Content-Type: application/json' -d '{
  "face_value": 100, "coupon_rate": 0.05, "frequency": 2,
  "years_to_maturity": 5, "ytm": 0.05, "yield_shift": 0.01
}'
```

返回一阶近似、二阶近似、精确重定价三者价格及各自误差。收益率上行 100bp 时可以看到：一阶估计跌得最多，二阶估计最贴近精确价。

### 错误响应

非法输入（面值非正、到期年数非正、票息率为负、收益率低到折现因子非正、到期年数不对应整数个付息期等）一律返回 422 结构化错误，不会抛出未处理异常或返回残缺数字：

```json
{
  "error": {
    "code": "INVALID_BOND_INPUT",
    "message": "债券参数未通过估值口径校验",
    "details": ["面值必须为正数，收到 -100.0"]
  }
}
```

请求体缺字段 / 类型错误则返回 `MALFORMED_REQUEST`。

## 测试基准

`pytest` 覆盖以下必须恒成立的关系：

- 平价债（票息率 = 到期收益率）全价等于面值，且与付息频率无关；
- 零息债麦考利久期恰好等于剩余到期年数，凸性符合闭式解；
- 仅抬高到期收益率时全价严格下降；
- 付息频率成倍加密后，全价、久期、凸性仍按同一收益率口径自洽（泰勒二阶估计贴近精确重定价，价格随频率加密收敛）；
- 一阶 / 二阶 / 精确三种价格的大小关系与误差排序；
- 各类非法输入被拒并返回结构化错误；
- 并发请求的中间计算互不干扰。
