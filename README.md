# GEO 智能分析与诊断平台

GEO Analyzer 是根据《PRD/product_prd.md》中 GEO-Analyzer-2025（v1.0.0）定义的 MVP，面向 CMO/品牌经理提供国产大模型（豆包、DeepSeek）声量监测、情感分析与诊断报告的端到端方案。项目覆盖 PRD 第 1–4 章的快慢双链流程、异常降级与数据埋点策略。

## 产品概述（PRD §1）
- **目标**：把 Doubao/DeepSeek 的黑盒推荐/评价逻辑转化为 SOV（声量份额）、负面标签、竞品洞察，并通过 CTA 驱动铭予 GEO 解决方案的销售线索。
- **体验**：前端即时展示行业基准与缓存数据（“快链”），后台异步模拟 20 次/平台并通过 Web UI 日志、进度条缓解 3–6 分钟等待。
- **真实接入**：线上部署需直接调用官方 API，并保证所有响应可审计、可追溯。

## 架构与核心流程（PRD §2）
1. 用户填写公司/产品/描述/行业/邮箱并提交表单。
2. 前端立即回显行业基准 + “诊断来自豆包 & DeepSeek 实时调用”提示。
3. `GeoSimulationEngine` 通过 `LLMOrchestrator` 并发 Doubao/DeepSeek，Discovery & Evaluation Prompt 每平台 20 次，记录快照与日志。
4. NLP 处理生成 SOV、负面比率、竞品实体与关键词标签；`ProcessLogger` + snapshots 驱动 UI 渐进刷新。
5. 依据 SOV 区间渲染危机/增长/防御 CTA 卡片，触发铭予营销话术。
6. 任务完成后生成版本化报告、离线补数（命中缓存时后台重试+邮件），并暴露 `/trace/{task_id}` 回溯面板。

## 模块与 PRD 对照（PRD §3–4）
| PRD ID | 功能要点 | 主要实现 |
| --- | --- | --- |
| **F-01** Diagnosis Setup | 表单校验、敏感词拦截 | `DiagnosisRequest.validate`, `frontend/index.html` |
| **F-02** Simulation Engine | Doubao/DeepSeek 并发 20 次、SOV 计算、推荐/竞品识别 | `GeoSimulationEngine`, `LLMOrchestrator`, `DoubaoClient`, `DeepSeekClient` |
| **F-03** Process UX | 动态日志窗、5 次快照推进、静默提示 | `ProcessLogger`, `_build_metrics_from_observations`, `frontend/app.js` |
| **F-04** Conversion Logic | 危机/增长/防御 CTA + CTA 埋点 | `_build_conversion_card`, `frontend/app.js` |
| **F-05** 智能建议 | 声量、负面、竞品三条策略文案 | `_build_advices`, `frontend/app.js` |
| **F-06** Doubao & DeepSeek 接入 | Secrets 管理、Token Bucket、Task Queue、Trace、缓存补数、邮件通知 | `SecretsManager`, `TokenBucket`, `LLMTraceStore`, `_schedule_cache_retry`, `ReportUpdateNotifier`, `/trace` API |
| **E-01** 熔断降级 | Token 重试、行业估算 fallback、灰字说明 | `_run_simulation`, `_generate_industry_estimation` |
| **E-02** 敏感拦截 | 输入/输出敏感词检测、前端弹窗引导人工 | `SENSITIVE_KEYWORDS`, `_contains_sensitive_output`, `frontend modal` |
| **Analytics (§5)** | Funnel、CTA、Report share 埋点 | `AnalyticsTracker`, `engine.run` 埋点、`/analytics/events`, `frontend/app.js` |

## 目录结构
```
src/geo_analyzer/
  analytics.py       # 埋点跟踪
  engine.py          # GeoSimulationEngine 主流程
  errors.py          # Validation/Sensitive 异常
  frontend/          # Web 表单与可视化
  llm.py             # Doubao/DeepSeek 客户端、编排、Trace
  logger.py          # 动态日志
  models.py          # 表单模型、报告结构
  notifier.py        # 缓存补数完成邮件
  server.py          # FastAPI 接口 & 静态资源
tests/               # Pytest 覆盖 F-01~F-06、E-01/E-02、API
PRD/product_prd.md   # 官方需求文档（单一事实来源）
```

## 快速开始
1. **环境**：建议 Python 3.11+，并启用虚拟环境。
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install fastapi uvicorn requests pytest pytest-cov httpx
   ```
2. **配置密钥（PRD F-06.1）**：将 Doubao / DeepSeek API Key 写入环境变量或由 `SecretsManager` 注册。
   ```bash
   export DOUBAO_API_KEY="your-doubao-key"
   export DEEPSEEK_API_KEY="your-deepseek-key"
   ```
3. **运行服务**：
   ```bash
   uvicorn geo_analyzer.server:app --reload
   ```
   - `GET /`：前端落地页 + 快链体验
   - `POST /diagnosis`：创建诊断，返回报告
   - `POST /analytics/events`：接收前端埋点
   - `GET /trace/{task_id}`：查看任意任务的 raw/summary trace

4. **异步补数 & 邮件**：若实时调用命中缓存，`GeoSimulationEngine` 会后台重跑并通过 `ReportUpdateNotifier` 模拟邮件。生产中可在此处接入实际邮件服务或消息队列。

## 测试与质量
- 项目遵循 PRD「测试策略」要求：**任何改动后都需执行 `pytest -q`**（默认启用 `pytest-cov`，输出覆盖率摘要）。
- 单元/集成测试通过 `pytest.mark.unit`、`pytest.mark.integration` 区分，可分别运行：
  - `pytest -m unit`（覆盖核心引擎、LLM orchestration）
  - `pytest -m integration`（覆盖 FastAPI + 前端静态资源）
- 生成分组覆盖率报告：
  ```bash
  tools/run_coverage_reports.sh
  # 输出 coverage-unit.xml / coverage-integration.xml + 终端覆盖率
  ```
- 主要测试清单：
  - `tests/test_geo_engine.py`：表单校验、CTA/建议、降级、缓存补数
  - `tests/test_f06_llm.py`：Doubao/DeepSeek 客户端契约、TokenBucket、Trace、缓存逻辑
  - `tests/test_api_server.py`：FastAPI 路由 & 前端静态文件

## 运维与排障
- **缓存提示**：“(来自缓存，已进入实时重试队列)” 表示离线补数正在排队，成功后会生成新版报告并触发邮件。
- **API 熔断**：若 3 次重试仍失败，报告会显示 `degraded=True` 且 `estimation_note="Based on Industry Estimation"`，同时日志写入“API 超时，触发静默降级”以便定位。
- **敏感词**：输入或模型输出包含 `SENSITIVE_KEYWORDS` 会抛出 `SensitiveContentError`，前端弹窗提示联系人工顾问。
- **Trace 回放**：运营可通过 `/trace/{task_id}` 配合 `LLMTraceStore` 的 30 天原文 / 1 年 summary 记录排查任意任务。

## PRD Trace Summary
- **F-01~F-02**：`GeoSimulationEngine`, `LLMOrchestrator`, 前端表单，确保必填项与 20 次模拟。
- **F-03**：`ProcessLogger`, snapshots, `frontend/app.js` 的日志/进度条。
- **F-04~F-05**：`_build_conversion_card`, `_build_advices`, 前端 CTA/建议渲染与埋点。
- **F-06**：Secrets、Token Bucket、缓存补数、Trace、邮件通知、/analytics、/trace API。
- **E-01/E-02**：行业估算降级与敏感词防护全链路闭环。
- **Analytics (§5)**：Tracker + `/analytics/events` + 前端埋点满足漏斗、报告分享统计。

如需更多实现细节，请阅读 `PRD/product_prd.md` 与对应源码注释；该 PRD 仍是唯一事实来源，应在后续迭代中保持同步更新。
