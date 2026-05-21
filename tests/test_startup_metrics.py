from __future__ import annotations

import pytest

from core.startup_metrics import StartupMetrics


def test_phase_records_duration_and_summary():
    metrics = StartupMetrics()

    with metrics.phase("bootstrap"):
        pass

    events = metrics.events()
    assert len(events) == 1
    assert events[0].name == "bootstrap"
    assert events[0].ok is True
    assert events[0].duration_ms >= 0
    assert "bootstrap=" in metrics.format_summary()


def test_phase_records_failed_scope():
    metrics = StartupMetrics()

    with pytest.raises(RuntimeError):
        with metrics.phase("broken"):
            raise RuntimeError("boom")

    events = metrics.events()
    assert len(events) == 1
    assert events[0].name == "broken"
    assert events[0].ok is False
    assert "broken=" in metrics.format_summary()
    assert "!" in metrics.format_summary()


def test_mark_records_zero_duration_event():
    metrics = StartupMetrics()

    metrics.mark("ready")

    events = metrics.events()
    assert len(events) == 1
    assert events[0].name == "ready"
    assert events[0].duration_ms == 0
