from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .models import DiagnosticReport


@dataclass
class ReportUpdateMessage:
    """Structured payload for离线补数邮件（PRD: F-06.6)."""

    to_email: str
    subject: str
    body: str
    report_version: int
    task_id: str
    metrics: Dict[str, float]


class ReportUpdateNotifier:
    """Minimal in-memory dispatcher for最新实时结果邮件."""

    def __init__(self) -> None:
        self._messages: List[ReportUpdateMessage] = []

    def send_report_update(self, report: DiagnosticReport) -> None:
        message = ReportUpdateMessage(
            to_email=report.request.work_email,
            subject="最新实时结果已准备就绪",
            body=(
                "最新实时结果已生成。"  # PRD: F-06.6 邮件同步内容
                f"报告版本 v{report.version}，SOV {report.metrics.sov_percentage}%"
                f" / 负面 {report.metrics.negative_rate}%。"
            ),
            report_version=report.version,
            task_id=report.task_id,
            metrics={
                "sov_percentage": report.metrics.sov_percentage,
                "negative_rate": report.metrics.negative_rate,
            },
        )
        self._messages.append(message)

    @property
    def sent_notifications(self) -> List[ReportUpdateMessage]:
        return list(self._messages)
