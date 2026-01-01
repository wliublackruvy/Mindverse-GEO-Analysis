from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .errors import SensitiveContentError, ValidationError


class Industry(str, Enum):
    SAAS = "SaaS"
    CONSUMER_ELECTRONICS = "消费电子"
    FINANCE = "金融"
    EDUCATION = "教育"
    OTHER = "其他"

    @property
    def benchmark_rate(self) -> int:
        return {
            Industry.SAAS: 27,
            Industry.CONSUMER_ELECTRONICS: 25,
            Industry.FINANCE: 24,
            Industry.EDUCATION: 22,
            Industry.OTHER: 20,
        }[self]

    @property
    def display_label(self) -> str:
        return self.value


SENSITIVE_KEYWORDS = {
    "政治",
    "暴力",
    "色情",
    "terror",
    "weapon",
    "极端",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class DiagnosisRequest:
    company_name: str
    product_name: str
    product_description: str
    industry: Industry
    work_email: str

    def validate(self) -> None:
        if not self.company_name.strip():
            raise ValidationError("公司全称为必填项")
        if not self.product_name.strip():
            raise ValidationError("产品名称为必填项")
        description = self.product_description.strip()
        if len(description) < 10:
            raise ValidationError("产品描述至少需要 10 个字符")
        if not EMAIL_RE.match(self.work_email.strip()):
            raise ValidationError("请输入有效的工作邮箱")
        if self._contains_sensitive(description):
            raise SensitiveContentError(
                "检测到敏感词，无法在线生成，请联系人工顾问获取私密报告"
            )

    def _contains_sensitive(self, text: str) -> bool:
        normalized = self._normalized_text(text)
        return any(keyword.lower() in normalized for keyword in SENSITIVE_KEYWORDS)

    @staticmethod
    def _normalized_text(text: str) -> str:
        return text.lower()

    def normalized_full_text(self) -> str:
        return self._normalized_text(
            " ".join(
                [
                    self.company_name,
                    self.product_name,
                    self.product_description,
                    self.industry.value,
                ]
            )
        )


@dataclass
class SimulationSnapshot:
    iteration: int
    sov_progress: float
    negative_rate: float


@dataclass
class SimulationMetrics:
    sov_percentage: float
    recommendation_count: int
    negative_rate: float
    negative_tags: List[str]
    competitors: Dict[str, int]
    degraded: bool = False
    estimation_note: Optional[str] = None
    snapshots: List[SimulationSnapshot] = field(default_factory=list)


@dataclass
class ConversionCard:
    mode: str
    title: str
    body: str
    cta: str
    tone_icon: str


@dataclass
class AdviceItem:
    text: str


@dataclass
class DiagnosticReport:
    request: DiagnosisRequest
    benchmark_copy: str
    metrics: SimulationMetrics
    conversion_card: ConversionCard
    advices: List[AdviceItem]
    logs: List[str]
    analytics: List[Dict[str, str]]
