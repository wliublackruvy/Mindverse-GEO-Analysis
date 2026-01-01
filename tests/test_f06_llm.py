# PRD: F-06

import pytest
import requests

from geo_analyzer.engine import GeoSimulationEngine
from geo_analyzer.errors import SensitiveContentError
from geo_analyzer.llm import (
    DeepSeekClient,
    DoubaoClient,
    LLMCall,
    LLMClientError,
    LLMOrchestrator,
    LLMTraceStore,
    SecretsManager,
    TokenBucket,
)
from geo_analyzer.models import DiagnosisRequest, Industry


def build_request(**overrides):
    payload = {
        "company_name": "Mingyu",
        "product_name": "Aurora GEO",
        "product_description": "旗舰 GEO 引擎，智能稳定且高端。",
        "industry": Industry.SAAS,
        "work_email": "ops@mingyu.com",
    }
    payload.update(overrides)
    return DiagnosisRequest(**payload)


def test_doubao_client_posts_real_chat_completion(monkeypatch):
    secrets = SecretsManager()
    secrets.register_key("doubao", "fake-doubao-key")
    bucket = TokenBucket(capacity=2, refill_rate_per_min=120)
    observed = {}

    def fake_post(self, url, headers=None, json=None, timeout=None):
        observed["url"] = url
        observed["payload"] = json

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "id": "doubao-1",
                    "choices": [
                        {
                            "message": {"content": "Aurora GEO 是不错的推荐"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 42},
                }

        return Response()

    monkeypatch.setattr(requests.Session, "post", fake_post)
    client = DoubaoClient(secrets=secrets, token_bucket=bucket, base_url="https://mock.doubao")
    response = client.create_chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert observed["url"].endswith("/v1/chat/completions")
    assert observed["payload"]["model"] == "doubao-pro"
    assert response["choices"][0]["finish_reason"] == "stop"


def test_deepseek_client_validates_finish_reason(monkeypatch):
    secrets = SecretsManager()
    secrets.register_key("deepseek", "fake-deepseek-key")
    bucket = TokenBucket(capacity=1, refill_rate_per_min=60)

    def fake_post(self, url, headers=None, json=None, timeout=None):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {"content": "some content"},
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"total_tokens": 7},
                }

        return Response()

    monkeypatch.setattr(requests.Session, "post", fake_post)
    client = DeepSeekClient(secrets=secrets, token_bucket=bucket, base_url="https://mock.deepseek")
    with pytest.raises(LLMClientError):
        client.create_chat_completion(messages=[{"role": "user", "content": "hi"}])


def test_three_strike_fallback_degrades_engine():
    class ExplodingClient:
        def create_chat_completion(self, *args, **kwargs):
            raise LLMClientError("network down")

    orchestrator = LLMOrchestrator(
        doubao_client=ExplodingClient(),
        deepseek_client=ExplodingClient(),
        positive_keywords={},
        negative_keywords={},
        negative_tags=["数据不足"],
    )
    engine = GeoSimulationEngine(orchestrator=orchestrator)
    report = engine.run(build_request())
    assert report.metrics.degraded is True
    assert report.metrics.estimation_note == "Based on Industry Estimation"


def test_cache_note_when_using_recent_llm_cache():
    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def create_chat_completion(self, *args, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                return {
                    "choices": [
                        {
                            "message": {"content": "Aurora GEO 推荐"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 3},
                }
            raise LLMClientError("temp failure")

    orchestrator = LLMOrchestrator(
        doubao_client=FlakyClient(),
        deepseek_client=None,
        positive_keywords={},
        negative_keywords={},
        negative_tags=["体验顺畅"],
    )
    result = orchestrator.simulate(build_request(), iterations=2)
    assert result.cache_note == "(来自缓存，已进入实时重试队列)"
    assert result.coverage["doubao"] is True
    assert len(result.observations) == 2
    assert result.observations[1].cached is True


def test_other_platform_continues_when_one_fails():
    class ExplodingClient:
        def create_chat_completion(self, *args, **kwargs):
            raise LLMClientError("down")

    class StableClient:
        def create_chat_completion(self, *args, **kwargs):
            return {
                "choices": [
                    {
                        "message": {"content": "Aurora GEO 推荐"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 1},
            }

    orchestrator = LLMOrchestrator(
        doubao_client=ExplodingClient(),
        deepseek_client=StableClient(),
        positive_keywords={},
        negative_keywords={},
        negative_tags=["体验顺畅"],
    )
    result = orchestrator.simulate(build_request(), iterations=3)
    assert result.degraded is False
    assert result.coverage["deepseek"] is True
    assert result.coverage["doubao"] is False
    assert all(obs.platform == "DeepSeek" for obs in result.observations)


def test_observations_include_twenty_runs_per_platform_offline():
    orchestrator = LLMOrchestrator(
        doubao_client=None,
        deepseek_client=None,
        positive_keywords={},
        negative_keywords={},
        negative_tags=["体验顺畅"],
    )
    result = orchestrator.simulate(build_request(), iterations=2)
    assert len(result.observations) == 4


def test_sensitive_output_raises_error(monkeypatch):
    secrets = SecretsManager()
    secrets.register_key("doubao", "fake-key")
    bucket = TokenBucket()

    def fake_post(self, url, headers=None, json=None, timeout=None):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {"content": "这段政治内容触发"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 5},
                }

        return Response()

    monkeypatch.setattr(requests.Session, "post", fake_post)
    orchestrator = LLMOrchestrator(
        doubao_client=DoubaoClient(secrets=secrets, token_bucket=bucket, base_url="https://mock"),
        deepseek_client=None,
        positive_keywords={},
        negative_keywords={},
        negative_tags=["体验顺畅"],
    )
    with pytest.raises(SensitiveContentError):
        orchestrator.simulate(build_request(), iterations=1)


def test_secrets_manager_revoke_and_alerts():
    secrets = SecretsManager()
    secrets.register_key("doubao", "key", quota_limit=100, expires_at=9999)
    secrets.record_usage("doubao", 10)
    assert secrets.consume_alerts() == []
    secrets.record_usage("doubao", 80)
    alerts = secrets.consume_alerts()
    assert alerts and alerts[0]["name"] == "doubao"
    secrets.revoke_key("doubao")
    with pytest.raises(KeyError):
        secrets.get_key("doubao")


def test_trace_store_retention_and_schema():
    current_time = {"value": 0}

    def fake_time():
        return current_time["value"]

    store = LLMTraceStore(raw_ttl=10, summary_ttl=20, time_fn=fake_time)
    call = LLMCall(
        task_id="task-1",
        platform="豆包",
        prompt_type="discovery",
        prompt_hash="hash",
        content="Aurora GEO 推荐",
        finish_reason="stop",
        mentions=["Aurora"],
        sentiment=0.4,
        cached=False,
        latency_ms=120.5,
    )
    store.record_raw(call)
    store.record_summary("task-1", {"sov_percentage": 50})
    trace = store.get_trace("task-1")
    assert trace["raw"][0]["content"] == ["Aurora GEO 推荐"]
    assert trace["summary"]["sov_percentage"] == 50
    current_time["value"] = 11
    trace = store.get_trace("task-1")
    assert trace["raw"] == []
    current_time["value"] = 25
    trace = store.get_trace("task-1")
    assert trace["summary"] is None


def test_orchestrator_records_trace_data():
    class StableClient:
        def create_chat_completion(self, *args, **kwargs):
            return {
                "choices": [
                    {
                        "message": {"content": "Aurora GEO 推荐"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 2},
            }

    trace_store = LLMTraceStore()
    orchestrator = LLMOrchestrator(
        doubao_client=StableClient(),
        deepseek_client=None,
        positive_keywords={},
        negative_keywords={},
        negative_tags=["体验顺畅"],
        trace_store=trace_store,
    )
    result = orchestrator.simulate(build_request(), iterations=1)
    trace = trace_store.get_trace(result.task_id)
    assert isinstance(trace["raw"], list)
