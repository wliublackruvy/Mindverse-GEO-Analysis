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
    request = build_request(product_description="太短")
    with pytest.raises(ValidationError):
        request.validate()


def test_industry_benchmark_copy_matches_prd():
    engine = GeoSimulationEngine()
    snippet = engine.industry_benchmark_copy(Industry.SAAS)
    assert snippet.startswith("该行业平均 AI 推荐率为")
    assert "27%" in snippet


def test_simulation_generates_logs_and_snapshots():
    logger = ProcessLogger()
    engine = GeoSimulationEngine(logger=logger)
    report = engine.run(build_request())
    assert len(report.metrics.snapshots) == 4  # every 5 runs
    assert len(report.logs) >= 20  # console log lines exist
    assert report.metrics.recommendation_count <= engine.iterations


def test_low_sov_triggers_crisis_card():
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
    request = build_request(product_description="涉及政治暴力的描述，请处理")
    engine = GeoSimulationEngine()
    with pytest.raises(SensitiveContentError):
        engine.run(request)


def test_timeout_triggers_industry_estimation():
    request = build_request(product_description="系统 timeout 需要降级")
    engine = GeoSimulationEngine()
    report = engine.run(request)
    assert report.metrics.degraded is True
    assert report.metrics.estimation_note == "Based on Industry Estimation"


def test_advices_cover_competitor_logic_and_analytics():
    tracker = AnalyticsTracker()
    description = (
        "旗舰方案对标 NovaWave 与 ArcLight，保持智能与稳定优势。"
    )
    engine = GeoSimulationEngine(tracker=tracker)
    report = engine.run(build_request(product_description=description))
    assert len(report.advices) == 3
    assert any("NovaWave" in advice.text for advice in report.advices)
    event_names = [event["event"] for event in report.analytics]
    assert "form_submitted" in event_names
    assert "conversion_card_shown" in event_names
