import pytest

from geo_analyzer import (
    AnalyticsTracker,
    GeoSimulationEngine,
    Industry,
    SensitiveContentError,
    ValidationError,
    DiagnosisRequest,
)
from geo_analyzer.logger import ProcessLogger
from geo_analyzer.llm import LLMObservation, LLMRunResult
from geo_analyzer.notifier import ReportUpdateNotifier

pytestmark = pytest.mark.unit


def build_request(**overrides):
    defaults = {
        "company_name": "Mingyu Tech",
        "product_name": "Aurora GEO",
        "product_description": (
            "旗舰级 GEO 自动化引擎，领先的智能语义对齐能力，"
            "以高端分析模型提供稳定体验。"
        ),
        "industry": Industry.SAAS,
        "work_email": "ops@mingyu.com",
    }
    defaults.update(overrides)
    return DiagnosisRequest(**defaults)


def test_request_validation_requires_description_length():
    # PRD: F-01 – form requires描述字段≥10个字符.
    request = build_request(product_description="太短")
    with pytest.raises(ValidationError):
        request.validate()


def test_industry_benchmark_copy_matches_prd():
    engine = GeoSimulationEngine()
    snippet = engine.industry_benchmark_copy(Industry.SAAS)
    assert snippet.startswith("该行业平均 AI 推荐率为")
    assert "27%" in snippet


def test_simulation_generates_logs_and_snapshots():
    # PRD: F-02 – 引擎需跑足 20 次模拟并返回 SOV 数据.
    # PRD: F-03 – 等待体验需要滚动日志与每5次快照.
    logger = ProcessLogger()
    engine = GeoSimulationEngine(logger=logger)
    report = engine.run(build_request())
    assert len(report.metrics.snapshots) >= engine.iterations // 5
    assert len(report.logs) >= 20
    assert report.metrics.recommendation_count <= engine.iterations
    assert report.task_id
    assert report.version == 1


def test_low_sov_triggers_crisis_card():
    # PRD: F-04 – SOV<15% 或负面>10% 触发危机模式 CTA.
    description = (
        "遗留系统频繁崩溃且 bug 横生，slow 响应带来大量投诉，"
        "延迟导致体验复杂且昂贵。"
    )
    engine = GeoSimulationEngine()
    report = engine.run(
        build_request(product_description=description, product_name="Legacy GEO")
    )
    assert report.conversion_card.mode == "crisis"
    assert report.metrics.sov_percentage < 15 or report.metrics.negative_rate > 10


def test_sensitive_content_blocks_generation():
    # PRD: E-02 – 含敏感词立即停止生成并返回拦截.
    request = build_request(product_description="涉及政治暴力的描述，请处理")
    engine = GeoSimulationEngine()
    with pytest.raises(SensitiveContentError):
        engine.run(request)


def test_sensitive_company_name_also_blocks_generation():
    # PRD: E-02 – 任一输入字段命中敏感词也需拦截.
    request = build_request(company_name="政治先锋科技有限公司")
    engine = GeoSimulationEngine()
    with pytest.raises(SensitiveContentError):
        engine.run(request)


def test_timeout_triggers_industry_estimation():
    # PRD: E-01 – API 熔断 3 次后静默降级行业估算.
    class DegradedOrchestrator:
        def simulate(self, request, iterations):
            return LLMRunResult(
                task_id="degraded-task",
                observations=[],
                coverage={"doubao": False, "deepseek": False},
                cache_note=None,
                degraded=True,
            )

    engine = GeoSimulationEngine(orchestrator=DegradedOrchestrator())
    report = engine.run(build_request())
    assert report.metrics.degraded is True
    assert report.metrics.estimation_note == "Based on Industry Estimation"
    assert report.task_id == "degraded-task"


def test_advices_cover_exact_prd_copies_and_analytics():
    # PRD: F-05 – 输出三条战术建议，含 SOV、负面、竞品文案.
    # PRD: Analytics – 埋点需记录 funnel、CTA、报告分享等事件.
    tracker = AnalyticsTracker()
    description = (
        "NovaWave bug 慢 slow 延迟 带来投诉，ArcLight 崩溃得更频繁。"
    )
    engine = GeoSimulationEngine(tracker=tracker)
    report = engine.run(build_request(product_description=description))
    texts = [advice.text for advice in report.advices]
    assert "建议增加‘Aurora GEO + SaaS场景’" in texts[0]
    assert any("检测到" in text for text in texts)
    assert any("差异化功能" in text for text in texts)
    event_names = [event["event"] for event in report.analytics]
    for required in [
        "funnel_visit",
        "form_submitted",
        "wait_stage_started",
        "cta_rendered",
        "report_ready",
        "report_share_enabled",
    ]:
        assert required in event_names


def test_cache_retry_dispatches_email_on_success():
    # PRD: F-06.6 – 缓存命中后需离线补数并邮件同步最新实时结果.
    class DeterministicOrchestrator:
        def __init__(self):
            self.calls = 0

        def simulate(self, request, iterations):
            self.calls += 1
            cached_observation = LLMObservation(
                iteration=1,
                platform="豆包",
                platform_key="doubao",
                recommended=True,
                competitor=None,
                sentiment=0.3,
                tag="体验顺畅",
                cached=True,
            )
            live_observation = LLMObservation(
                iteration=1,
                platform="豆包",
                platform_key="doubao",
                recommended=True,
                competitor=None,
                sentiment=0.4,
                tag="体验顺畅",
                cached=False,
            )
            if self.calls == 1:
                return LLMRunResult(
                    task_id="cached-task",
                    observations=[cached_observation],
                    coverage={"doubao": True, "deepseek": False},
                    cache_note="(来自缓存，已进入实时重试队列)",
                    degraded=False,
                )
            return LLMRunResult(
                task_id="fresh-task",
                observations=[live_observation],
                coverage={"doubao": True, "deepseek": False},
                cache_note=None,
                degraded=False,
            )

    notifier = ReportUpdateNotifier()

    def immediate(job):
        job()

    engine = GeoSimulationEngine(
        orchestrator=DeterministicOrchestrator(),
        email_notifier=notifier,
        retry_executor=immediate,
    )
    report = engine.run(build_request())
    assert report.version == 1
    assert report.metrics.cache_note is not None
    assert notifier.sent_notifications
    notification = notifier.sent_notifications[-1]
    assert notification.report_version == 2
    assert notification.metrics["sov_percentage"] >= 0
