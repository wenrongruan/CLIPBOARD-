"""本地匿名事件计数。

仅在本机存储到 `<config_dir>/analytics.json`，不做任何网络上报。
用于验证 P0 主路径是否生效（首次记录、首次唤出、首次搜索、首次复制历史、首次收藏）。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 事件常量
FIRST_RECORD = "first_record"
FIRST_WAKE = "first_wake"
FIRST_SEARCH = "first_search"
FIRST_COPY_HISTORY = "first_copy_history"
FIRST_STAR = "first_star"


class _LocalAnalytics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Optional[Path] = None
        self._data: Dict[str, dict] = {"first": {}, "count": {}}
        self._loaded = False

    def _resolve_path(self) -> Optional[Path]:
        if self._path is not None:
            return self._path
        try:
            from config import get_config_dir
            self._path = get_config_dir() / "analytics.json"
        except Exception:
            self._path = None
        return self._path

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        path = self._resolve_path()
        if path and path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data["first"] = dict(data.get("first") or {})
                    self._data["count"] = dict(data.get("count") or {})
            except Exception as exc:
                logger.debug(f"analytics 加载失败,使用空状态: {exc}")
        self._loaded = True

    def _save(self) -> None:
        path = self._resolve_path()
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp.replace(path)
        except Exception as exc:
            logger.debug(f"analytics 保存失败: {exc}")

    def mark_first(self, event: str) -> bool:
        """记录首次发生时间戳，已记录则跳过。返回是否本次新写入。"""
        try:
            with self._lock:
                self._ensure_loaded()
                if event in self._data["first"]:
                    return False
                import time
                self._data["first"][event] = int(time.time())
                self._save()
                return True
        except Exception:
            return False

    def incr(self, event: str, delta: int = 1) -> None:
        try:
            with self._lock:
                self._ensure_loaded()
                self._data["count"][event] = int(self._data["count"].get(event, 0)) + delta
                self._save()
        except Exception:
            pass

    def snapshot(self) -> Dict[str, dict]:
        with self._lock:
            self._ensure_loaded()
            return {
                "first": dict(self._data["first"]),
                "count": dict(self._data["count"]),
            }


_instance = _LocalAnalytics()


def mark_first(event: str) -> bool:
    return _instance.mark_first(event)


def incr(event: str, delta: int = 1) -> None:
    _instance.incr(event, delta)


def snapshot() -> Dict[str, dict]:
    return _instance.snapshot()
