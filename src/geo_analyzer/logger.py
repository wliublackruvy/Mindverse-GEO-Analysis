from __future__ import annotations

from typing import List


class ProcessLogger:
    """Captures console-like logs used by the waiting experience (F-03)."""

    def __init__(self) -> None:
        self._entries: List[str] = []

    def log(self, channel: str, message: str) -> None:
        entry = f"> [{channel}] {message}"
        self._entries.append(entry)

    @property
    def entries(self) -> List[str]:
        return list(self._entries)
