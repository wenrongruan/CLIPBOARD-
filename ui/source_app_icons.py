"""来源 App 图标缓存。

按 (bundle_id, exe_path) 缓存 QIcon，所有平台都有统一兜底（QStyle.SP_FileIcon）。
- Windows：用 QFileIconProvider 从 exe_path 解包
- macOS：NSWorkspace（PyObjC 可用时）根据 bundle_id 定位 app 再取图标
- Linux：QIcon.fromTheme(bundle_id)（简化；未找到就兜底）

仅做内存 LRU 缓存（上限 128）。跨平台失败都不会抛。
"""

from __future__ import annotations

import logging
import sys
from collections import OrderedDict
from typing import Optional

from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFileIconProvider, QStyle

logger = logging.getLogger(__name__)


_MAX_ENTRIES = 128


class SourceAppIconCache:
    """小型 LRU 缓存：(bundle_id, exe_path) -> QIcon。"""

    _instance: Optional["SourceAppIconCache"] = None

    def __init__(self) -> None:
        self._cache: "OrderedDict[tuple, QIcon]" = OrderedDict()
        self._provider: Optional[QFileIconProvider] = None
        self._fallback: Optional[QIcon] = None

    @classmethod
    def instance(cls) -> "SourceAppIconCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def clear(self) -> None:
        self._cache.clear()

    def get(self, bundle_id: str = "", exe_path: str = "") -> QIcon:
        """返回对应 App 的图标。都为空时返回兜底图标。"""
        bundle_id = bundle_id or ""
        exe_path = exe_path or ""
        key = (bundle_id, exe_path)

        # 空键直接兜底（避免给无意义 widget 拼接）
        if not bundle_id and not exe_path:
            return self._get_fallback()

        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        icon = self._resolve(bundle_id, exe_path)
        if icon is None or icon.isNull():
            icon = self._get_fallback()

        self._cache[key] = icon
        self._cache.move_to_end(key)
        # LRU evict
        while len(self._cache) > _MAX_ENTRIES:
            self._cache.popitem(last=False)
        return icon

    # ----- internal -----

    def _get_fallback(self) -> QIcon:
        if self._fallback is None:
            app = QApplication.instance()
            if app is not None:
                try:
                    self._fallback = app.style().standardIcon(QStyle.SP_FileIcon)
                except Exception:
                    self._fallback = QIcon()
            else:
                self._fallback = QIcon()
        return self._fallback

    def _get_provider(self) -> QFileIconProvider:
        if self._provider is None:
            self._provider = QFileIconProvider()
        return self._provider

    def _resolve(self, bundle_id: str, exe_path: str) -> Optional[QIcon]:
        try:
            if sys.platform == "win32":
                return self._resolve_windows(exe_path)
            if sys.platform == "darwin":
                return self._resolve_macos(bundle_id, exe_path)
            # linux / other
            return self._resolve_linux(bundle_id, exe_path)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"source app icon resolve failed: {exc}")
            return None

    def _resolve_windows(self, exe_path: str) -> Optional[QIcon]:
        if not exe_path:
            return None
        fi = QFileInfo(exe_path)
        if not fi.exists():
            return None
        icon = self._get_provider().icon(fi)
        return icon if not icon.isNull() else None

    def _resolve_macos(self, bundle_id: str, exe_path: str) -> Optional[QIcon]:
        # 优先 NSWorkspace（若 PyObjC 可用）
        try:
            from AppKit import NSWorkspace  # type: ignore
            ws = NSWorkspace.sharedWorkspace()
            app_path = None
            if bundle_id:
                app_path = ws.absolutePathForAppBundleWithIdentifier_(bundle_id)
            if not app_path and exe_path:
                app_path = exe_path
            if app_path:
                ns_image = ws.iconForFile_(app_path)
                if ns_image is not None:
                    # NSImage -> QIcon 转换：走 PNG 字节中转
                    try:
                        from Cocoa import NSBitmapImageRep, NSPNGFileType  # type: ignore
                        tiff = ns_image.TIFFRepresentation()
                        rep = NSBitmapImageRep.imageRepWithData_(tiff)
                        png_data = rep.representationUsingType_properties_(
                            NSPNGFileType, None
                        )
                        from PySide6.QtGui import QPixmap
                        pix = QPixmap()
                        pix.loadFromData(bytes(png_data))
                        if not pix.isNull():
                            return QIcon(pix)
                    except Exception:
                        pass
        except Exception:
            pass
        # 兜底到 QFileIconProvider（Mac 下对 .app 路径也能拿到图标）
        if exe_path:
            fi = QFileInfo(exe_path)
            if fi.exists():
                icon = self._get_provider().icon(fi)
                if not icon.isNull():
                    return icon
        return None

    def _resolve_linux(self, bundle_id: str, exe_path: str) -> Optional[QIcon]:
        if bundle_id:
            icon = QIcon.fromTheme(bundle_id)
            if not icon.isNull():
                return icon
            # 某些 WM_CLASS 含点号，去掉 dot-suffix 再试一次
            base = bundle_id.split(".")[-1]
            if base and base != bundle_id:
                icon = QIcon.fromTheme(base)
                if not icon.isNull():
                    return icon
        if exe_path:
            fi = QFileInfo(exe_path)
            if fi.exists():
                icon = self._get_provider().icon(fi)
                if not icon.isNull():
                    return icon
        return None


__all__ = ["SourceAppIconCache"]
