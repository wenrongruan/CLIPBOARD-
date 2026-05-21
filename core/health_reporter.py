"""应用健康状态收集器。

用于把启动和运行时的降级状态集中起来：热键不可用、MySQL 降级、
凭据存储降级、云同步失败、剪贴板监听异常等。

本模块不依赖 Qt，方便单元测试；UI 层只负责展示 `format_summary()` 的结果。
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import List, Optional


@dataclass(frozen=True)
class HealthIssue:
    component: str
    level: str
    message: str
    since_ts: int


class HealthReporter:
    """线程安全的进程内健康状态表。

    同一个 component 只保留最新一条状态，避免重复托盘提示把用户淹没。
    """

    _LEVEL_RANK = {"error": 0, "warning": 1, "info": 2}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._issues: dict[str, HealthIssue] = {}

    def add(
        self,
        component: str,
        level: str,
        message: str,
        *,
        since_ts: Optional[int] = None,
    ) -> HealthIssue:
        if level not in self._LEVEL_RANK:
            raise ValueError(f"unknown health level: {level}")
        issue = HealthIssue(
            component=component,
            level=level,
            message=message,
            since_ts=since_ts if since_ts is not None else int(time.time()),
        )
        with self._lock:
            self._issues[component] = issue
        return issue

    def clear(self, component: Optional[str] = None) -> None:
        with self._lock:
            if component is None:
                self._issues.clear()
            else:
                self._issues.pop(component, None)

    def list(self) -> List[HealthIssue]:
        with self._lock:
            issues = list(self._issues.values())
        return sorted(
            issues,
            key=lambda issue: (self._LEVEL_RANK[issue.level], issue.component),
        )

    def format_summary(self, *, limit: int = 3) -> str:
        issues = self.list()
        if not issues:
            return ""
        shown = issues[:limit]
        lines = ["部分功能已降级，但本地剪贴板历史仍可继续使用："]
        lines.extend(f"- {issue.message}" for issue in shown)
        rest = len(issues) - len(shown)
        if rest > 0:
            lines.append(f"- 另有 {rest} 项状态，请查看日志或设置。")
        return "\n".join(lines)


_default_reporter = HealthReporter()


def add_issue(
    component: str,
    level: str,
    message: str,
    *,
    since_ts: Optional[int] = None,
) -> HealthIssue:
    return _default_reporter.add(
        component,
        level,
        message,
        since_ts=since_ts,
    )


def clear_issue(component: Optional[str] = None) -> None:
    _default_reporter.clear(component)


def list_issues() -> List[HealthIssue]:
    return _default_reporter.list()


def format_summary(*, limit: int = 3) -> str:
    return _default_reporter.format_summary(limit=limit)
