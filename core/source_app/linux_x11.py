"""Linux X11 source app provider。

用 python-xlib 读 _NET_ACTIVE_WINDOW / WM_CLASS / _NET_WM_NAME / _NET_WM_PID。
"""
from __future__ import annotations

import logging
import os

from .base import SourceApp, SourceAppProvider

logger = logging.getLogger(__name__)


class X11SourceAppProvider(SourceAppProvider):
    """Linux X11 实现。"""

    def __init__(self) -> None:
        self._available = False
        self._display = None
        self._Xlib = None
        self._X = None

        if not os.environ.get("DISPLAY"):
            logger.info("DISPLAY 环境变量不存在，X11 provider 不可用")
            return

        try:
            import Xlib  # type: ignore
            import Xlib.display  # type: ignore
            from Xlib import X  # type: ignore
            self._Xlib = Xlib
            self._X = X
            self._display = Xlib.display.Display()
            self._available = True
        except ImportError as e:
            logger.info(f"python-xlib 不可用: {e}")
        except Exception as e:
            logger.info(f"无法连接 X server: {e}")

    @property
    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------

    def _atom(self, name: str):
        return self._display.intern_atom(name)

    def _get_property(self, window, prop_name: str, prop_type):
        try:
            atom = self._atom(prop_name)
            prop = window.get_full_property(atom, prop_type)
            return prop.value if prop is not None else None
        except Exception:
            return None

    def get_current(self) -> SourceApp:
        if not self._available:
            return SourceApp()
        try:
            root = self._display.screen().root
            net_active = self._atom("_NET_ACTIVE_WINDOW")
            prop = root.get_full_property(net_active, self._X.AnyPropertyType)
            if prop is None or not prop.value:
                return SourceApp()
            window_id = int(prop.value[0])
            if window_id == 0:
                return SourceApp()

            win = self._display.create_resource_object("window", window_id)

            # WM_CLASS: (instance, class) 两个 NUL 分隔的字符串
            wm_class_atom = self._atom("WM_CLASS")
            wm_class_prop = win.get_full_property(wm_class_atom, self._X.AnyPropertyType)
            instance = ""
            cls = ""
            if wm_class_prop is not None and wm_class_prop.value:
                raw = wm_class_prop.value
                if isinstance(raw, bytes):
                    parts = raw.split(b"\x00")
                    parts = [p.decode("utf-8", "replace") for p in parts if p]
                else:
                    parts = [str(p) for p in raw if p]
                if len(parts) >= 2:
                    instance, cls = parts[0], parts[1]
                elif len(parts) == 1:
                    instance = cls = parts[0]

            # 标题：优先 _NET_WM_NAME，fallback WM_NAME
            title = ""
            for name in ("_NET_WM_NAME", "WM_NAME"):
                v = self._get_property(win, name, self._X.AnyPropertyType)
                if v:
                    if isinstance(v, bytes):
                        title = v.decode("utf-8", "replace")
                    else:
                        title = str(v)
                    break

            # pid
            pid = 0
            v = self._get_property(win, "_NET_WM_PID", self._X.AnyPropertyType)
            if v:
                try:
                    pid = int(v[0])
                except Exception:
                    pid = 0

            exe_path = ""
            if pid:
                try:
                    exe_path = os.readlink(f"/proc/{pid}/exe")
                except Exception:
                    exe_path = ""

            app_name = cls or instance
            bundle_id = (cls or instance).lower()

            return SourceApp(
                app_name=app_name,
                bundle_id=bundle_id,
                exe_path=exe_path,
                window_title=title,
            )
        except Exception as e:
            logger.warning(f"X11 get_current 失败: {e}")
            return SourceApp()
