"""FastAPI server exposing the GEO Analyzer engine end to end."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analytics import AnalyticsTracker
from .engine import GeoSimulationEngine
from .errors import SensitiveContentError, ValidationError
from .models import DiagnosticReport, DiagnosisRequest, Industry

app = FastAPI(
    title="GEO Analyzer API",
    version="1.0.0",
    description="MVP server fulfilling GEO-Analyzer-2025 PRD.",
)

engine = GeoSimulationEngine()
external_analytics = AnalyticsTracker()
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=FRONTEND_DIR, html=False),
        name="static",
    )


class DiagnosisPayload(BaseModel):
    company_name: str = Field(..., min_length=1)
    product_name: str = Field(..., min_length=1)
    product_description: str = Field(..., min_length=10)
    industry: Industry
    work_email: str = Field(..., min_length=5)


class AdviceResponse(BaseModel):
    text: str


class ConversionCardResponse(BaseModel):
    mode: str
    title: str
    body: str
    cta: str
    tone_icon: str


class SimulationSnapshotResponse(BaseModel):
    iteration: int
    sov_progress: float
    negative_rate: float


class SimulationMetricsResponse(BaseModel):
    sov_percentage: float
    recommendation_count: int
    negative_rate: float
    negative_tags: List[str]
    competitors: Dict[str, int]
    coverage: Dict[str, bool]
    cache_note: Optional[str] = None
    degraded: bool = False
    estimation_note: Optional[str] = None
    snapshots: List[SimulationSnapshotResponse]


class DiagnosisResponse(BaseModel):
    task_id: str
    benchmark_copy: str
    metrics: SimulationMetricsResponse
    conversion_card: ConversionCardResponse
    advices: List[AdviceResponse]
    logs: List[str]
    analytics: List[Dict[str, Any]]
    report_version: int


class AnalyticsEventPayload(BaseModel):
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class RawTraceEntryResponse(BaseModel):
    platform: str
    prompt_type: str
    content: List[str]
    mentions: List[str]
    sentiment: Dict[str, float]
    latency_ms: float
    recorded_at: float


class LLMTraceResponse(BaseModel):
    task_id: str
    raw: List[RawTraceEntryResponse]
    summary: Optional[Dict[str, Any]] = None


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    if not FRONTEND_DIR.exists():
        raise HTTPException(status_code=404, detail="frontend not available")
    return FileResponse(FRONTEND_DIR / "index.html")


@app.post("/diagnosis", response_model=DiagnosisResponse)
def create_diagnosis(payload: DiagnosisPayload) -> DiagnosisResponse:
    request = DiagnosisRequest(
        company_name=payload.company_name,
        product_name=payload.product_name,
        product_description=payload.product_description,
        industry=payload.industry,
        work_email=payload.work_email,
    )
    try:
        report = engine.run(request)
    except SensitiveContentError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    return _serialize_report(report)


@app.post("/analytics/events")
def ingest_analytics_event(event: AnalyticsEventPayload) -> Dict[str, str]:
    # PRD: Analytics – capture CTA clicks / report share telemetry from前端.
    external_analytics.track(event.event, event.payload)
    return {"status": "accepted"}


@app.get("/trace/{task_id}", response_model=LLMTraceResponse)
def get_llm_trace(task_id: str) -> LLMTraceResponse:
    trace = engine.orchestrator.trace_store.get_trace(task_id)
    if not trace["raw"] and not trace["summary"]:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace


def _serialize_report(report: DiagnosticReport) -> DiagnosisResponse:
    return DiagnosisResponse(
        task_id=report.task_id,
        benchmark_copy=report.benchmark_copy,
        metrics=SimulationMetricsResponse(
            sov_percentage=report.metrics.sov_percentage,
            recommendation_count=report.metrics.recommendation_count,
            negative_rate=report.metrics.negative_rate,
            negative_tags=report.metrics.negative_tags,
            competitors=report.metrics.competitors,
            coverage=report.metrics.coverage,
            cache_note=report.metrics.cache_note,
            degraded=report.metrics.degraded,
            estimation_note=report.metrics.estimation_note,
            snapshots=[
                SimulationSnapshotResponse(
                    iteration=snapshot.iteration,
                    sov_progress=snapshot.sov_progress,
                    negative_rate=snapshot.negative_rate,
                )
                for snapshot in report.metrics.snapshots
            ],
        ),
        conversion_card=ConversionCardResponse(
            mode=report.conversion_card.mode,
            title=report.conversion_card.title,
            body=report.conversion_card.body,
            cta=report.conversion_card.cta,
            tone_icon=report.conversion_card.tone_icon,
        ),
        advices=[AdviceResponse(text=advice.text) for advice in report.advices],
        logs=report.logs,
        analytics=report.analytics,
        report_version=report.version,
    )
