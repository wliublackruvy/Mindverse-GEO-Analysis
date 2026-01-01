import pytest

fastapi = pytest.importorskip(
    "fastapi", reason="FastAPI is required for API surface tests."
)
from fastapi.testclient import TestClient  # type: ignore  # noqa: E402

from geo_analyzer.server import app
from geo_analyzer.models import Industry


def build_payload(**overrides):
    payload = {
        "company_name": "Mingyu Tech",
        "product_name": "Aurora GEO",
        "product_description": "旗舰级 GEO 自动化引擎，领先的智能语义对齐能力。",
        "industry": Industry.SAAS.value,
        "work_email": "ops@mingyu.com",
    }
    payload.update(overrides)
    return payload


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_diagnosis_endpoint_returns_report(client):
    response = client.post("/diagnosis", json=build_payload())
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert "metrics" in data
    assert data["conversion_card"]["mode"] in {"crisis", "growth", "defense"}
    assert len(data["advices"]) == 3
    assert data["report_version"] >= 1


def test_sensitive_payload_returns_400(client):
    response = client.post(
        "/diagnosis",
        json=build_payload(product_description="内容涉及政治敏感话题"),
    )
    assert response.status_code == 400
    assert "敏感词" in response.json()["detail"]


def test_timeout_payload_triggers_degraded_metrics(client):
    response = client.post(
        "/diagnosis",
        json=build_payload(product_description="本次调研出现 timeout 需要熔断"),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metrics"]["degraded"] is True
    assert data["metrics"]["estimation_note"] == "Based on Industry Estimation"


def test_frontend_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "GEO 智能分析与诊断平台" in response.text


def test_analytics_ingest_endpoint(client):
    response = client.post(
        "/analytics/events",
        json={"event": "cta_clicked", "payload": {"mode": "crisis"}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_trace_endpoint_returns_summary(client):
    response = client.post("/diagnosis", json=build_payload())
    task_id = response.json()["task_id"]
    trace = client.get(f"/trace/{task_id}")
    assert trace.status_code == 200
    payload = trace.json()
    assert payload["task_id"] == task_id
    assert payload["summary"] is not None
