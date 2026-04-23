"""macOS 平台 source app provider。

用 PyObjC 的 AppKit.NSWorkspace 拿前台应用。窗口标题需要
Accessibility 权限，本迭代留空。
"""
from __future__ import annotations

import logging

from .base import SourceApp, SourceAppProvider

logger = logging.getLogger(__name__)


class MacOSSourceAppProvider(SourceAppProvider):
    """macOS 实现，基于 PyObjC AppKit。"""

    def __init__(self) -> None:
        self._available = False
        self._NSWorkspace = None
        try:
            from AppKit import NSWorkspace  # type: ignore
            self._NSWorkspace = NSWorkspace
            self._available = True
        except ImportError as e:
            logger.info(f"AppKit (pyobjc) 不可用: {e}")

    @property
    def is_available(self) -> bool:
        return self._available

    def get_current(self) -> SourceApp:
        if not self._available:
            return SourceApp()
        try:
            workspace = self._NSWorkspace.sharedWorkspace()
            app = workspace.frontmostApplication()
            if app is None:
                return SourceApp()

            app_name = ""
            bundle_id = ""
            exe_path = ""

            try:
                app_name = str(app.localizedName() or "")
            except Exception:
                pass
            try:
                bundle_id = str(app.bundleIdentifier() or "")
            except Exception:
                pass
            try:
                url = app.bundleURL()
                if url is not None:
                    exe_path = str(url.path() or "")
            except Exception:
                pass

            return SourceApp(
                app_name=app_name,
                bundle_id=bundle_id,
                exe_path=exe_path,
                window_title="",  # 需要 Accessibility API，本迭代不做
            )
        except Exception as e:
            logger.warning(f"macOS get_current 失败: {e}")
            return SourceApp()
