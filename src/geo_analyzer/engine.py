from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List

from .analytics import AnalyticsTracker
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


class GeoSimulationEngine:
    """High-level orchestrator that fulfills sections F-01 through F-05."""

    _DEGRADE_KEYWORDS = {"timeout", "熔断", "degrade"}
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
    ) -> None:
        self.iterations = iterations
        self.logger = logger or ProcessLogger()
        self.tracker = tracker or AnalyticsTracker()

    def run(self, request: DiagnosisRequest) -> DiagnosticReport:
        request.validate()
        benchmark_copy = self.industry_benchmark_copy(request.industry)
        self.tracker.track(
            "form_submitted",
            {
                "industry": request.industry.value,
                "company": request.company_name,
            },
        )
        self.tracker.track(
            "industry_viewed",
            {"industry": request.industry.value, "benchmark": benchmark_copy},
        )

        if self._should_use_industry_estimation(request):
            metrics = self._generate_industry_estimation(request)
        else:
            metrics = self._run_simulation(request)

        conversion_card = self._build_conversion_card(metrics, request)
        advices = self._build_advices(metrics, request)
        self.tracker.track(
            "conversion_card_shown",
            {"mode": conversion_card.mode, "sov": metrics.sov_percentage},
        )
        self.tracker.track(
            "report_ready",
            {
                "negative_rate": metrics.negative_rate,
                "competitors": list(metrics.competitors.keys()),
            },
        )

        analytics_payload = [
            {"event": event.name, "payload": event.payload} for event in self.tracker.events
        ]
        return DiagnosticReport(
            request=request,
            benchmark_copy=benchmark_copy,
            metrics=metrics,
            conversion_card=conversion_card,
            advices=advices,
            logs=self.logger.entries,
            analytics=analytics_payload,
        )

    def industry_benchmark_copy(self, industry: Industry) -> str:
        return f"该行业平均 AI 推荐率为 {industry.benchmark_rate}%"

    def _should_use_industry_estimation(self, request: DiagnosisRequest) -> bool:
        text = request.normalized_full_text()
        return any(keyword in text for keyword in self._DEGRADE_KEYWORDS)

    def _generate_industry_estimation(self, request: DiagnosisRequest) -> SimulationMetrics:
        self.logger.log(
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
            degraded=True,
            estimation_note="Based on Industry Estimation",
            snapshots=snapshots,
        )

    def _run_simulation(self, request: DiagnosisRequest) -> SimulationMetrics:
        base_strength = 0.45
        normalized_description = request.product_description.lower()
        for keyword, delta in self._POSITIVE_KEYWORDS.items():
            if keyword in normalized_description:
                base_strength += delta
        for keyword, delta in self._NEGATIVE_KEYWORDS.items():
            if keyword in normalized_description:
                base_strength -= delta / 2
        base_strength = max(0.05, min(0.95, base_strength))
        recommended_runs = int(round(self.iterations * base_strength))

        negative_ratio = 0.1
        for keyword, delta in self._NEGATIVE_KEYWORDS.items():
            if keyword in normalized_description:
                negative_ratio += delta
        negative_ratio = min(0.9, max(0.0, negative_ratio))
        negative_runs = int(round(self.iterations * negative_ratio))

        competitors = self._extract_competitors(request)
        competitor_counts: Dict[str, int] = {name: 0 for name in competitors}
        negative_tags: List[str] = []
        snapshots: List[SimulationSnapshot] = []
        recommendation_count = 0
        negative_count = 0

        for iteration in range(self.iterations):
            provider = "DeepSeek" if iteration % 2 else "豆包"
            self.logger.log(
                "System",
                f"正在连接 {provider} 知识库... Success",
            )
            if iteration < recommended_runs:
                recommendation_count += 1
                self.logger.log(
                    "Engine",
                    f"{provider} 推荐 {request.product_name}",
                )
            else:
                competitor = (
                    competitors[iteration % len(competitors)]
                    if competitors
                    else "其他竞品"
                )
                competitor_counts[competitor] = competitor_counts.get(competitor, 0) + 1
                self.logger.log(
                    "Engine",
                    f"{provider} 更倾向 {competitor}",
                )

            if iteration < negative_runs:
                negative_count += 1
                tag = self._NEGATIVE_TAG_PHRASES[iteration % len(self._NEGATIVE_TAG_PHRASES)]
                negative_tags.append(tag)
            else:
                tag = "体验顺畅"
            self.logger.log(
                "Analysis",
                f"监测到关键词: \"{tag}\"",
            )

            if (iteration + 1) % 5 == 0:
                sov_progress = (recommendation_count / (iteration + 1)) * 100
                negative_rate_progress = (negative_count / (iteration + 1)) * 100
                snapshots.append(
                    SimulationSnapshot(
                        iteration=iteration + 1,
                        sov_progress=round(sov_progress, 2),
                        negative_rate=round(negative_rate_progress, 2),
                    )
                )

        sov_percentage = round((recommendation_count / self.iterations) * 100, 2)
        negative_rate = round((negative_count / self.iterations) * 100, 2)
        return SimulationMetrics(
            sov_percentage=sov_percentage,
            recommendation_count=recommendation_count,
            negative_rate=negative_rate,
            negative_tags=negative_tags or ["体验顺畅"],
            competitors=competitor_counts,
            snapshots=snapshots,
        )

    def _extract_competitors(self, request: DiagnosisRequest) -> List[str]:
        inline = re.findall(r"[A-Z][A-Za-z0-9\-]+", request.product_description)
        candidates: List[str] = []
        for candidate in inline:
            if candidate.lower() not in {
                request.company_name.lower(),
                request.product_name.lower(),
            }:
                candidates.append(candidate)
        candidates.extend(self._INDUSTRY_COMPETITORS.get(request.industry, []))
        deduped: Dict[str, None] = {}
        for candidate in candidates:
            deduped.setdefault(candidate, None)
        return list(deduped.keys())

    def _build_conversion_card(
        self, metrics: SimulationMetrics, request: DiagnosisRequest
    ) -> ConversionCard:
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
                        f"{request.product_name} 的声量领先行业，但仍可通过加固"
                        "场景化案例库来稳定推荐率。"
                    )
                )
            )

        negative_tag = metrics.negative_tags[0] if metrics.negative_tags else "未知标签"
        if metrics.negative_rate > 10:
            advices.append(
                AdviceItem(
                    text=(
                        f"检测到“{negative_tag}”标签。建议针对性发布技术解析文章进行语义清洗。"
                    )
                )
            )
        else:
            advices.append(
                AdviceItem(
                    text="保持积极口碑，并定期同步 Roadmap，防止旧版本反馈被放大。"
                )
            )

        if metrics.competitors:
            competitor = next(iter(metrics.competitors.keys()))
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
                    text="持续监控潜在竞品输入，把差异化卖点固化为 Prompt 模板。"
                )
            )

        return advices
