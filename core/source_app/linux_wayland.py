"""Linux Wayland source app provider（折衷实现）。

Wayland 没有"查询任意前台窗口"的标准 API，我们按顺序尝试：
1. GNOME Shell：``org.gnome.Shell.Eval`` 读 ``global.display.focus_window``
   （Mutter 3.38+ 默认禁用，能成功就算赚到）。
2. KDE KWin：``org.kde.KWin.activeClient``（实际字段视版本而定）。
3. 兜底：返回 ``SourceApp(app_name="Wayland", bundle_id=$XDG_CURRENT_DESKTOP)``。
"""
from __future__ import annotations

import logging
import os

from .base import SourceApp, SourceAppProvider

logger = logging.getLogger(__name__)


class WaylandSourceAppProvider(SourceAppProvider):
    """Wayland 折衷 provider，依赖 jeepney (D-Bus)。"""

    def __init__(self) -> None:
        self._available = False
        self._jeepney = None
        self._DBusAddress = None
        self._new_method_call = None
        self._open_dbus_connection = None

        if not os.environ.get("WAYLAND_DISPLAY"):
            logger.info("WAYLAND_DISPLAY 不存在，Wayland provider 不可用")
            return

        try:
            import jeepney  # type: ignore
            from jeepney import DBusAddress, new_method_call  # type: ignore
            from jeepney.io.blocking import open_dbus_connection  # type: ignore

            self._jeepney = jeepney
            self._DBusAddress = DBusAddress
            self._new_method_call = new_method_call
            self._open_dbus_connection = open_dbus_connection
            self._available = True
        except ImportError as e:
            logger.info(f"jeepney 不可用: {e}")

    @property
    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------

    def _fallback(self) -> SourceApp:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP") or "wayland"
        return SourceApp(app_name="Wayland", bundle_id=desktop.lower())

    def get_current(self) -> SourceApp:
        if not self._available:
            return SourceApp()
        try:
            # 1) GNOME Shell.Eval
            app = self._try_gnome()
            if app is not None and not app.is_empty:
                return app

            # 2) KDE KWin activeClient
            app = self._try_kwin()
            if app is not None and not app.is_empty:
                return app

            # 3) 兜底
            return self._fallback()
        except Exception as e:
            logger.warning(f"Wayland get_current 失败: {e}")
            return self._fallback()

    # --- GNOME --------------------------------------------------------

    def _try_gnome(self) -> SourceApp | None:
        try:
            addr = self._DBusAddress(
                "/org/gnome/Shell",
                bus_name="org.gnome.Shell",
                interface="org.gnome.Shell",
            )
            script = (
                "let w = global.display.focus_window;"
                "w ? (w.get_wm_class() || '') + '\\n' + (w.get_title() || '') : ''"
            )
            msg = self._new_method_call(addr, "Eval", "s", (script,))
            conn = self._open_dbus_connection(bus="SESSION")
            try:
                reply = conn.send_and_get_reply(msg, timeout=1.0)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            body = reply.body if reply is not None else None
            if not body:
                return None
            success = bool(body[0]) if len(body) >= 1 else False
            payload = body[1] if len(body) >= 2 else ""
            if not success or not payload:
                return None

            # Eval 返回 JSON 字符串，这里是简单文本，直接按行拆
            try:
                import json
                value = json.loads(payload) if payload and payload.strip().startswith(("\"", "'")) else payload
            except Exception:
                value = payload
            if not isinstance(value, str):
                value = str(value)
            parts = value.split("\n", 1)
            wm_class = parts[0].strip() if parts else ""
            title = parts[1].strip() if len(parts) > 1 else ""
            if not wm_class and not title:
                return None
            return SourceApp(
                app_name=wm_class,
                bundle_id=wm_class.lower(),
                exe_path="",
                window_title=title,
            )
        except Exception as e:
            logger.debug(f"GNOME Shell.Eval 失败: {e}")
            return None

    # --- KDE ----------------------------------------------------------

    def _try_kwin(self) -> SourceApp | None:
        try:
            addr = self._DBusAddress(
                "/KWin",
                bus_name="org.kde.KWin",
                interface="org.kde.KWin",
            )
            msg = self._new_method_call(addr, "activeClient", "", ())
            conn = self._open_dbus_connection(bus="SESSION")
            try:
                reply = conn.send_and_get_reply(msg, timeout=1.0)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            body = reply.body if reply is not None else None
            if not body:
                return None
            raw = body[0]
            if not raw:
                return None
            # KWin 返回结构多变；尝试从字符串里提取 wm_class / title
            if isinstance(raw, dict):
                wm_class = str(raw.get("resourceClass") or raw.get("wm_class") or "")
                title = str(raw.get("caption") or raw.get("title") or "")
            else:
                wm_class = ""
                title = str(raw)
            if not wm_class and not title:
                return None
            return SourceApp(
                app_name=wm_class,
                bundle_id=wm_class.lower(),
                exe_path="",
                window_title=title,
            )
        except Exception as e:
            logger.debug(f"KWin activeClient 失败: {e}")
            return None
