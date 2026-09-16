"""来源 App 图标缓存。

按 (bundle_id, exe_path) 缓存 QIcon，所有平台都有统一兜底（QStyle.SP_FileIcon）。
- Windows：用 QFileIconProvider 从 exe_path 解包
- macOS：NSWorkspace（PyObjC 可用时）根据 bundle_id 定位 app 再取图标
- Linux：QIcon.fromTheme(bundle_id)（简化；未找到就兜底）

仅做内存 LRU 缓存（上限 128）。跨平台失败都不会抛。

macOS 上「取图标」为什么必须自己定尺寸
--------------------------------------
`NSWorkspace.iconForFile_()` 返回的 NSImage 背后是 App 的 .icns，里面带
1024x1024 的 representation。直接 `TIFFRepresentation()` → `NSBitmapImageRep` →
PNG 编码，就是在为一张 1024x1024 的图做全量重编码，实测每个 App 要 130ms
（冷启动 300~500ms），产出 1~2MB 的 PNG。而调用方
（ui/clipboard_item.py::_make_source_icon_label）只把它放进一个 16x16 的 QLabel，
Retina 下最多也就需要 32x32。

改成先开一块 32x32 的位图把 NSImage 画进去再编码，同样的图标只要 0.4ms，
快 300 倍以上。启动时会为第一页里每个不同的来源 App 取一次图标，本机 21 种来源
App，这一项就是秒级差异。
"""

from __future__ import annotations

import logging
import sys
from collections import OrderedDict
from typing import Optional

from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QFileIconProvider, QStyle

logger = logging.getLogger(__name__)


_MAX_ENTRIES = 128

#: 取图标时编码的像素边长。调用方只要 16x16 逻辑像素，Retina 下 32 就够；
#: 别调大 —— 这一项直接决定每个 App 的取图标耗时（见模块 docstring）。
_ICON_PIXELS = 32


def _nsimage_to_png(ns_image, pixels: int = _ICON_PIXELS):
    """把 NSImage 画进一块 pixels x pixels 的位图并编码成 PNG 字节。

    必须先缩后编码：直接对原始 NSImage 做 TIFFRepresentation 会带上 .icns 里
    1024x1024 的那一档，编码成本上百毫秒，而结果会被缩到 16px 显示。
    返回 None 表示转换失败（调用方自行兜底）。
    """
    from AppKit import (  # type: ignore
        NSBitmapImageRep,
        NSCompositingOperationCopy,
        NSDeviceRGBColorSpace,
        NSGraphicsContext,
        NSPNGFileType,
        NSZeroRect,
    )

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, pixels, pixels, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    if rep is None:
        return None
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    if ctx is None:
        return None
    NSGraphicsContext.saveGraphicsState()
    try:
        NSGraphicsContext.setCurrentContext_(ctx)
        # fromRect 传 NSZeroRect = 整张图；目标 rect 就是整块画布，等比铺满
        ns_image.drawInRect_fromRect_operation_fraction_(
            ((0.0, 0.0), (float(pixels), float(pixels))),
            NSZeroRect,
            NSCompositingOperationCopy,
            1.0,
        )
    finally:
        NSGraphicsContext.restoreGraphicsState()
    data = rep.representationUsingType_properties_(NSPNGFileType, None)
    return bytes(data) if data is not None else None


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
                    # 缩到 _ICON_PIXELS 再编码，别把 1024x1024 全量重编码一遍
                    data = _nsimage_to_png(ns_image, _ICON_PIXELS)
                    if data:
                        pix = QPixmap()
                        pix.loadFromData(data)
                        if not pix.isNull():
                            return QIcon(pix)
        except Exception:
            pass
        # 兜底到 QFileIconProvider。
        # Why 跳过 .app：实测对 .app 目录它给的是通用「文件夹」图标
        # （Chrome / Finder / 微信 全变成同一个蓝色文件夹），比没有更误导人；
        # 这种情况干脆返回 None，让上层用 SP_FileIcon。非 .app 的 exe 路径
        # （macOS 上少数来源 App 落库的是可执行文件路径）仍走这条路。
        if exe_path and not exe_path.rstrip("/").lower().endswith(".app"):
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
