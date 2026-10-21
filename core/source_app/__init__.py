"""来源 App 捕获子包。

对外只暴露：
- ``SourceApp``、``SourceAppProvider``
- ``get_provider()``：按平台返回单例 provider
- ``get_current_source_app()``：模块级简便函数
"""
import logging
import os
import sys
from typing import Optional

from .base import SourceApp, SourceAppProvider

logger = logging.getLogger(__name__)

_provider: Optional[SourceAppProvider] = None


def _create_provider() -> SourceAppProvider:
    """根据当前平台/会话按需创建 provider，失败返回 noop。"""
    try:
        if sys.platform == "win32":
            from .windows import WindowsSourceAppProvider
            p = WindowsSourceAppProvider()
            if p.is_available:
                return p
        elif sys.platform == "darwin":
            from .macos import MacOSSourceAppProvider
            p = MacOSSourceAppProvider()
            if p.is_available:
                return p
        elif sys.platform.startswith("linux"):
            # 先试 Wayland，fallback 到 X11
            if os.environ.get("WAYLAND_DISPLAY"):
                from .linux_wayland import WaylandSourceAppProvider
                p = WaylandSourceAppProvider()
                if p.is_available:
                    return p
            from .linux_x11 import X11SourceAppProvider
            p = X11SourceAppProvider()
            if p.is_available:
                return p
    except Exception as e:  # pragma: no cover - 防御
        logger.warning(f"创建 source app provider 失败: {e}, 使用 noop 兜底")
    from .noop import NoopSourceAppProvider
    return NoopSourceAppProvider()


def get_provider() -> SourceAppProvider:
    """返回当前平台 provider（单例，按需创建）。"""
    global _provider
    if _provider is None:
        _provider = _create_provider()
    return _provider


def reset_provider() -> None:
    """测试辅助：清空单例缓存，让下一次 get_provider() 重新创建。"""
    global _provider
    _provider = None


def get_current_source_app() -> SourceApp:
    """模块级简便函数：返回当前前台应用，失败返回空 SourceApp。"""
    try:
        return get_provider().get_current()
    except Exception as e:
        logger.warning(f"get_current_source_app 失败: {e}")
        return SourceApp()


__all__ = [
    "SourceApp",
    "SourceAppProvider",
    "get_provider",
    "get_current_source_app",
    "reset_provider",
]
