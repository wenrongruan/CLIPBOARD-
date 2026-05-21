from __future__ import annotations

import pytest

from core.health_reporter import HealthReporter


def test_add_replaces_same_component():
    reporter = HealthReporter()

    reporter.add("hotkey", "warning", "old", since_ts=1)
    reporter.add("hotkey", "warning", "new", since_ts=2)

    issues = reporter.list()
    assert len(issues) == 1
    assert issues[0].component == "hotkey"
    assert issues[0].message == "new"
    assert issues[0].since_ts == 2


def test_list_orders_by_level_then_component():
    reporter = HealthReporter()

    reporter.add("mysql", "warning", "mysql degraded", since_ts=1)
    reporter.add("cloud_sync", "error", "cloud failed", since_ts=1)
    reporter.add("analytics", "info", "local only", since_ts=1)

    assert [(i.level, i.component) for i in reporter.list()] == [
        ("error", "cloud_sync"),
        ("warning", "mysql"),
        ("info", "analytics"),
    ]


def test_format_summary_limits_rows_and_reports_remaining_count():
    reporter = HealthReporter()
    reporter.add("cloud_sync", "warning", "云端同步失败", since_ts=1)
    reporter.add("mysql", "warning", "MySQL 降级", since_ts=1)
    reporter.add("hotkey", "warning", "热键不可用", since_ts=1)

    summary = reporter.format_summary(limit=2)

    assert "本地剪贴板历史仍可继续使用" in summary
    assert "云端同步失败" in summary
    assert "热键不可用" in summary
    assert "MySQL 降级" not in summary
    assert "另有 1 项状态" in summary


def test_unknown_level_raises():
    reporter = HealthReporter()

    with pytest.raises(ValueError):
        reporter.add("x", "fatal", "bad level")
