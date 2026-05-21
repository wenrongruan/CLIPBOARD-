from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, List, Optional


@dataclass(frozen=True)
class StartupEvent:
    name: str
    started_ms: float
    duration_ms: float
    ok: bool = True


class StartupMetrics:
    """Small startup timing collector for product-path baselines."""

    def __init__(self, started_at: Optional[float] = None):
        self._started_at = time.perf_counter() if started_at is None else started_at
        self._events: List[StartupEvent] = []

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        ok = False
        try:
            yield
            ok = True
        finally:
            ended = time.perf_counter()
            self._events.append(
                StartupEvent(
                    name=name,
                    started_ms=(started - self._started_at) * 1000,
                    duration_ms=(ended - started) * 1000,
                    ok=ok,
                )
            )

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self._events.append(
            StartupEvent(
                name=name,
                started_ms=(now - self._started_at) * 1000,
                duration_ms=0.0,
                ok=True,
            )
        )

    def events(self) -> list[StartupEvent]:
        return list(self._events)

    def total_ms(self) -> float:
        if not self._events:
            return 0.0
        return max(event.started_ms + event.duration_ms for event in self._events)

    def format_summary(self) -> str:
        if not self._events:
            return "startup: no events"
        parts = [
            f"{event.name}={event.duration_ms:.1f}ms{'!' if not event.ok else ''}"
            for event in self._events
        ]
        return f"startup total={self.total_ms():.1f}ms; " + ", ".join(parts)
