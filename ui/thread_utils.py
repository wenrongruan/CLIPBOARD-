"""QThread 生命周期的共享工具。

Why: PySide6 里 QThread 对象若只被局部变量持有，CPython 可能在线程仍在
isRunning() 时就把它析构，Qt 随即 qFatal("QThread: Destroyed while thread is
still running") 直接 abort 整个进程 —— 没有 Python 异常、无法 try/except。

所以凡是"启动后不再被 UI 长期持有"的后台线程，都必须在这里登记一个强引用，
finished 时再释放。此前 main_window_helpers 用 `window._migration_worker` 单个
槽位保存引用，重复触发迁移时旧线程被新线程覆盖 → 覆盖即 abort。
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)

_ACTIVE_THREADS: set = set()


def track_thread(thread: QThread) -> QThread:
    """保持 QThread 的 Python 强引用直到 finished，并在结束后安全释放。

    返回同一个 thread，方便链式使用：`track_thread(worker).start()`。
    """
    _ACTIVE_THREADS.add(thread)

    def _release():
        _ACTIVE_THREADS.discard(thread)
        thread.deleteLater()

    thread.finished.connect(_release)
    # Why 兜底：若调用方登记后因异常从未 start()，finished 永远不发射，
    # 这条强引用会变成永久僵尸。对象被销毁时（无论何种原因）都释放。
    thread.destroyed.connect(lambda _obj=None: _ACTIVE_THREADS.discard(thread))
    return thread


def active_thread_count() -> int:
    """当前仍在运行的受管线程数（用于诊断与测试）。"""
    return sum(1 for t in list(_ACTIVE_THREADS) if t.isRunning())
