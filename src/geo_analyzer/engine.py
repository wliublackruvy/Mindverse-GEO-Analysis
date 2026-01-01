from __future__ import annotations

import re
import threading
from typing import Callable, Dict, List, Optional

from .analytics import AnalyticsTracker
from .errors import SensitiveContentError
from .llm import LLMObservation, LLMOrchestrator
from .logger import ProcessLogger
from .models import (
    AdviceItem,
    ConversionCard,
    DiagnosticReport,
    DiagnosisRequest,
    Industry,
    SimulationMetrics,
    SimulationSnapshot,
)
from .notifier import ReportUpdateNotifier


class GeoSimulationEngine:
    """High-level orchestrator fulfilling PRD F-01 ~ F-06 + E-01/E-02."""

    _NEGATIVE_KEYWORDS = {
        "bug": 0.15,
        "投诉": 0.12,
        "延迟": 0.1,
        "slow": 0.08,
        "昂贵": 0.07,
        "复杂": 0.05,
        "崩溃": 0.16,
    }
    _POSITIVE_KEYWORDS = {
        "旗舰": 0.12,
        "智能": 0.08,
        "高端": 0.07,
        "领先": 0.1,
        "trusted": 0.09,
        "稳定": 0.05,
    }
    _NEGATIVE_TAG_PHRASES = [
        "性价比高",
        "界面复杂",
        "稳定性波动",
        "客服响应慢",
    ]
    _INDUSTRY_COMPETITORS: Dict[Industry, List[str]] = {
        Industry.SAAS: ["OptiStack", "DataPulse", "NeuronSuite"],
        Industry.CONSUMER_ELECTRONICS: ["NovaWave", "ArcLight", "PulseOne"],
        Industry.FINANCE: ["FinPulse", "LedgerX", "CrestPay"],
        Industry.EDUCATION: ["LearnSphere", "EduNova", "MindBridge"],
        Industry.OTHER: ["OmniLab", "PrimeSphere", "TerraBeam"],
    }

    def __init__(
        self,
        *,
        iterations: int = 20,
        logger: ProcessLogger | None = None,
        tracker: AnalyticsTracker | None = None,
        orchestrator: LLMOrchestrator | None = None,
        email_notifier: ReportUpdateNotifier | None = None,
        retry_executor: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self.iterations = iterations
        self.logger = logger or ProcessLogger()
        self.tracker = tracker or AnalyticsTracker()
        self.email_notifier = email_notifier or ReportUpdateNotifier()
        self.retry_executor = retry_executor or self._default_retry_executor
        self.orchestrator = orchestrator or LLMOrchestrator(
            industry_competitors=self._INDUSTRY_COMPETITORS,
            positive_keywords=self._POSITIVE_KEYWORDS,
            negative_keywords=self._NEGATIVE_KEYWORDS,
            negative_tags=self._NEGATIVE_TAG_PHRASES,
        )
        self._version_store: Dict[str, int] = {}
        self._pending_retry_keys: set[str] = set()
        self._version_lock = threading.Lock()

    def run(self, request: DiagnosisRequest) -> DiagnosticReport:
        request.validate()
        benchmark_copy = self.industry_benchmark_copy(request.industry)
        # PRD: Analytics – funnel + industry coverage tracking.
        self.tracker.track(
            "funnel_visit",
            {
                "industry": request.industry.value,
                "company": request.company_name,
            },
        )
        self.tracker.track(
            "form_submitted",
            {
                "industry": request.industry.value,
                "product": request.product_name,
            },
        )
        self.tracker.track(
            "industry_distribution",
            {"industry": request.industry.value, "benchmark": benchmark_copy},
        )
        self.tracker.track(
            "wait_stage_started",
            {"iterations_per_platform": self.iterations},
        )

        metrics, task_id = self._run_simulation(request, log=self.logger)

        conversion_card = self._build_conversion_card(metrics, request)
        advices = self._build_advices(metrics, request)
        self.tracker.track(
            "cta_rendered",
            {"mode": conversion_card.mode, "sov": metrics.sov_percentage},
        )
        self.tracker.track(
            "report_ready",
            {
                "negative_rate": metrics.negative_rate,
                "competitors": list(metrics.competitors.keys()),
            },
        )
        self.tracker.track(
            "report_share_enabled",
            {"coverage": metrics.coverage},
        )

        analytics_payload = [
            {"event": event.name, "payload": event.payload}
            for event in self.tracker.flush()
        ]
        version = self._next_report_version(request)
        report = DiagnosticReport(
            request=request,
            task_id=task_id,
            benchmark_copy=benchmark_copy,
            metrics=metrics,
            conversion_card=conversion_card,
            advices=advices,
            logs=self.logger.entries,
            analytics=analytics_payload,
            version=version,
        )
        if metrics.cache_note:
            self._schedule_cache_retry(
                self._clone_request(request),
                benchmark_copy=benchmark_copy,
            )
        return report

    def industry_benchmark_copy(self, industry: Industry) -> str:
        return f"该行业平均 AI 推荐率为 {industry.benchmark_rate}%"

    def _generate_industry_estimation(
        self,
        request: DiagnosisRequest,
        *,
        coverage: Optional[Dict[str, bool]] = None,
        cache_note: Optional[str] = None,
        log: Optional[ProcessLogger] = None,
    ) -> SimulationMetrics:
        if log:
            log.log(
                "System",
                "API 超时，触发静默降级，使用行业通用估算模型",
            )
        sov = request.industry.benchmark_rate
        recommendation_count = round(self.iterations * sov / 100)
        negative_rate = 8.0
        snapshots = [
            SimulationSnapshot(
                iteration=i * 5,
                sov_progress=sov,
                negative_rate=negative_rate,
            )
            for i in range(1, 1 + self.iterations // 5)
        ]
        return SimulationMetrics(
            sov_percentage=float(sov),
            recommendation_count=recommendation_count,
            negative_rate=negative_rate,
            negative_tags=["Based on Industry Estimation"],
            competitors={},
            coverage=coverage or {"doubao": False, "deepseek": False},
            cache_note=cache_note,
            degraded=True,
            estimation_note="Based on Industry Estimation",
            snapshots=snapshots,
        )

    def _run_simulation(
        self, request: DiagnosisRequest, log: Optional[ProcessLogger] = None
    ) -> tuple[SimulationMetrics, str]:
        llm_result = self.orchestrator.simulate(request, iterations=self.iterations)
        normalized_description = request.product_description.lower()
        if "timeout" in normalized_description or "熔断" in request.product_description:
            # PRD: E-01 – allow测试输入强制模拟熔断场景.
            llm_result.degraded = True
            llm_result.observations = []
        active_logger = log or self.logger
        if active_logger:
            active_logger.log("System", f"实时任务 {llm_result.task_id} 已创建")
        for platform, covered in llm_result.coverage.items():
            state = "在线" if covered else "不可用"
            if active_logger:
                active_logger.log(
                    "System",
                    f"{platform} 覆盖状态: {state}",
                )
        if llm_result.cache_note:
            if active_logger:
                active_logger.log("System", llm_result.cache_note)
        if llm_result.degraded or not llm_result.observations:
            if active_logger:
                active_logger.log(
                    "System",
                    "LLM 实时接口连续失败，触发 E-01 行业估算",
                )
            metrics = self._generate_industry_estimation(
                request,
                coverage=llm_result.coverage,
                cache_note=llm_result.cache_note,
                log=active_logger,
            )
            self._record_trace_summary(llm_result.task_id, metrics)
            return metrics, llm_result.task_id
        metrics = self._build_metrics_from_observations(
            llm_result.observations,
            request,
            per_platform_runs=self.iterations,
            coverage=llm_result.coverage,
            logger=active_logger,
        )
        metrics.coverage = llm_result.coverage
        metrics.cache_note = llm_result.cache_note
        self._record_trace_summary(llm_result.task_id, metrics)
        return metrics, llm_result.task_id

    def _build_metrics_from_observations(
        self,
        observations: List[LLMObservation],
        request: DiagnosisRequest,
        *,
        per_platform_runs: int,
        coverage: Dict[str, bool],
        logger: Optional[ProcessLogger] = None,
    ) -> SimulationMetrics:
        competitor_counts: Dict[str, int] = {}
        negative_tags: List[str] = []
        snapshots: List[SimulationSnapshot] = []
        recommendation_totals: Dict[str, int] = {}
        platform_runs: Dict[str, int] = {}
        recommendation_count = 0
        negative_count = 0

        for idx, observation in enumerate(observations):
            platform_key = getattr(observation, "platform_key", "")
            if platform_key:
                platform_runs[platform_key] = platform_runs.get(platform_key, 0) + 1
            provider = observation.platform
            status = "Cache" if observation.cached else "Success"
            # PRD: F-03 – emit pseudo console logs for progress体验.
            if logger:
                logger.log(
                    "System",
                    f"正在连接 {provider} 知识库... {status}",
                )
            if observation.recommended:
                recommendation_count += 1
                recommendation_totals[platform_key] = recommendation_totals.get(platform_key, 0) + 1
                if logger:
                    logger.log(
                        "Engine",
                        f"{provider} 推荐 {request.product_name}",
                    )
            else:
                competitor = observation.competitor or self._fallback_competitor(request)
                if competitor:
                    competitor_counts[competitor] = competitor_counts.get(competitor, 0) + 1
                    if logger:
                        logger.log(
                            "Engine",
                            f"{provider} 更倾向 {competitor}",
                        )
            if observation.sentiment < 0:
                negative_count += 1
            tag = observation.tag or "体验顺畅"
            negative_tags.append(tag)
            if logger:
                logger.log(
                    "Analysis",
                    f'监测到关键词: "{tag}"',
                )
            if (idx + 1) % 5 == 0:
                sov_progress = (recommendation_count / (idx + 1)) * 100
                negative_rate_progress = (negative_count / (idx + 1)) * 100
                snapshots.append(
                    SimulationSnapshot(
                        iteration=idx + 1,
                        sov_progress=round(sov_progress, 2),
                        negative_rate=round(negative_rate_progress, 2),
                    )
                )

        total_runs = max(1, len(observations))
        negative_rate = round((negative_count / total_runs) * 100, 2)
        active_platforms = sum(1 for key, covered in coverage.items() if covered)
        if not active_platforms:
            active_platforms = max(1, len(platform_runs))
        average_recommendations = round(
            sum(recommendation_totals.values()) / max(1, active_platforms)
        )
        # PRD: F-02 – SOV = 推荐次数 / 20 * 100% (per-platform average).
        sov_percentage = round(
            (average_recommendations / max(1, per_platform_runs)) * 100,
            2,
        )
        return SimulationMetrics(
            sov_percentage=sov_percentage,
            recommendation_count=average_recommendations,
            negative_rate=negative_rate,
            negative_tags=negative_tags or ["体验顺畅"],
            competitors=competitor_counts,
            snapshots=snapshots,
        )

    def _record_trace_summary(self, task_id: str, metrics: SimulationMetrics) -> None:
        trace_store = getattr(self.orchestrator, "trace_store", None)
        if not trace_store:
            return
        trace_store.record_summary(
            task_id,
            {
                "sov_percentage": metrics.sov_percentage,
                "negative_rate": metrics.negative_rate,
                "recommendation_count": metrics.recommendation_count,
                "coverage": metrics.coverage,
                "degraded": metrics.degraded,
                "cache_note": metrics.cache_note,
            },
        )

    def _schedule_cache_retry(
        self,
        request: DiagnosisRequest,
        *,
        benchmark_copy: str,
    ) -> None:
        # PRD: F-06.6 – 命中缓存时需离线补数并邮件同步最新版本.
        retry_key = self._version_key(request)
        with self._version_lock:
            if retry_key in self._pending_retry_keys:
                return
            self._pending_retry_keys.add(retry_key)

        def job() -> None:
            try:
                self._retry_realtime_refresh(
                    request,
                    benchmark_copy=benchmark_copy,
                    retry_key=retry_key,
                )
            finally:
                with self._version_lock:
                    self._pending_retry_keys.discard(retry_key)

        self.retry_executor(job)

    def _retry_realtime_refresh(
        self,
        request: DiagnosisRequest,
        *,
        benchmark_copy: str,
        retry_key: str,
    ) -> None:
        try:
            llm_result = self.orchestrator.simulate(
                request,
                iterations=self.iterations,
            )
        except SensitiveContentError:
            return
        if llm_result.cache_note or llm_result.degraded or not llm_result.observations:
            return
        metrics = self._build_metrics_from_observations(
            llm_result.observations,
            request,
            per_platform_runs=self.iterations,
            coverage=llm_result.coverage,
            logger=None,
        )
        metrics.coverage = llm_result.coverage
        metrics.cache_note = None
        self._record_trace_summary(llm_result.task_id, metrics)
        conversion_card = self._build_conversion_card(metrics, request)
        advices = self._build_advices(metrics, request)
        report = DiagnosticReport(
            request=request,
            task_id=llm_result.task_id,
            benchmark_copy=benchmark_copy,
            metrics=metrics,
            conversion_card=conversion_card,
            advices=advices,
            logs=[],
            analytics=[],
            version=self._next_report_version_for_key(retry_key),
        )
        self.email_notifier.send_report_update(report)

    def _version_key(self, request: DiagnosisRequest) -> str:
        normalized = request.normalized_full_text()
        return f"{normalized}|{request.work_email.lower()}"

    def _next_report_version(self, request: DiagnosisRequest) -> int:
        key = self._version_key(request)
        return self._next_report_version_for_key(key)

    def _next_report_version_for_key(self, key: str) -> int:
        with self._version_lock:
            version = self._version_store.get(key, 0) + 1
            self._version_store[key] = version
            return version

    def _default_retry_executor(self, job: Callable[[], None]) -> None:
        worker = threading.Thread(target=job, daemon=True)
        worker.start()

    def _clone_request(self, request: DiagnosisRequest) -> DiagnosisRequest:
        return DiagnosisRequest(
            company_name=request.company_name,
            product_name=request.product_name,
            product_description=request.product_description,
            industry=request.industry,
            work_email=request.work_email,
        )

    def _fallback_competitor(self, request: DiagnosisRequest) -> Optional[str]:
        inline = re.findall(r"[A-Z][A-Za-z0-9\-]+", request.product_description)
        deduped: Dict[str, None] = {}
        for candidate in inline:
            deduped.setdefault(candidate, None)
        if deduped:
            normalized_company = request.company_name.lower()
            normalized_product = request.product_name.lower()
            for candidate in deduped:
                lowered = candidate.lower()
                if lowered not in {normalized_company, normalized_product}:
                    return candidate
        industry_candidates = self._INDUSTRY_COMPETITORS.get(request.industry, [])
        return industry_candidates[0] if industry_candidates else None

    def _build_conversion_card(
        self, metrics: SimulationMetrics, request: DiagnosisRequest
    ) -> ConversionCard:
        # PRD: F-04 – drive动态 CTA based on SOV/负面阈值.
        sov = metrics.sov_percentage
        negative = metrics.negative_rate
        if sov < 15 or negative > 10:
            mode = "crisis"
            title = "您的品牌正在被 AI 遗忘"
            body = "您在 AI 里的存在感低于行业基准 40%。如不干预，市场将被竞品瓜分。"
            cta = "联系铭予：立即修复声誉"
            tone_icon = "🔴"
        elif 15 <= sov < 60:
            mode = "growth"
            title = "您错失了 40%+ 的精准流量"
            top_competitor = next(iter(metrics.competitors), "竞品")
            body = (
                f"您已进入视野，但排名被{top_competitor}压制。"
                "铭予 GEO 方案可帮您跃升至 Top 3。"
            )
            cta = "联系铭予：获取增长方案"
            tone_icon = "⚡️"
        else:
            mode = "defense"
            title = "表现卓越，但需警惕追兵"
            body = (
                "新锐竞品正在通过 GEO 试图取代您的位置。铭予帮您建立数据护城河。"
            )
            cta = "联系铭予：巩固领袖地位"
            tone_icon = "🛡️"
        return ConversionCard(
            mode=mode,
            title=title,
            body=body,
            cta=cta,
            tone_icon=tone_icon,
        )

    def _build_advices(
        self, metrics: SimulationMetrics, request: DiagnosisRequest
    ) -> List[AdviceItem]:
        advices: List[AdviceItem] = []
        industry_label = request.industry.display_label
        # PRD: F-05 – three tactical bulletins based on SOV/负面/竞品.
        if metrics.sov_percentage < 40:
            advices.append(
                AdviceItem(
                    text=(
                        f"建议增加‘{request.product_name} + {industry_label}场景’的"
                        "高权重语料投喂，强化实体关联。"
                    )
                )
            )
        else:
            advices.append(
                AdviceItem(
                    text=(
                        f"{request.product_name} 的声量高于行业均值，"
                        "请继续用案例夯实语义锚点。"
                    )
                )
            )

        negative_tag = metrics.negative_tags[0] if metrics.negative_tags else "体验顺畅"
        if metrics.negative_rate > 10:
            advices.append(
                AdviceItem(
                    text=(
                        f"检测到‘{negative_tag}’标签。建议针对性发布技术解析文章进行语义清洗。"
                    )
                )
            )
        else:
            advices.append(
                AdviceItem(
                    text="保持积极口碑，并定期同步 Roadmap，防止旧反馈被放大。"
                )
            )

        if metrics.competitors:
            competitor = max(metrics.competitors, key=metrics.competitors.get)
            advices.append(
                AdviceItem(
                    text=(
                        f"建议在语料中强调与{competitor}的差异化功能，建立独特性神经元连接。"
                    )
                )
            )
        else:
            advices.append(
                AdviceItem(
                    text="建议持续监测新竞品，并将差异化卖点固化到 Prompt。"
                )
            )

        return advices
