from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass
class AnalyticsEvent:
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class AnalyticsTracker:
    """Minimal in-memory tracker used to satisfy Section 5 requirements."""

    def __init__(self) -> None:
        self._events: List[AnalyticsEvent] = []

    def track(self, name: str, payload: Dict[str, Any] | None = None) -> None:
        # PRD: Analytics – record funnel, industry, and share telemetry.
        self._events.append(AnalyticsEvent(name=name, payload=payload or {}))

    def flush(self) -> List[AnalyticsEvent]:
        events = list(self._events)
        self._events.clear()
        return events

    @property
    def events(self) -> List[AnalyticsEvent]:
        return list(self._events)
