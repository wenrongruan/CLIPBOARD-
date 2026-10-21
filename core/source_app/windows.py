"""Windows 平台 source app provider。

优先用 pywin32 (win32gui / win32process) + psutil；
pywin32 不可用时 fallback 到 ctypes + Win32 API。
"""
from __future__ import annotations

import logging
import os

from .base import SourceApp, SourceAppProvider

logger = logging.getLogger(__name__)


def _pretty_app_name(exe_basename: str) -> str:
    """chrome.exe -> Chrome；code.exe -> Code。"""
    stem = exe_basename
    if stem.lower().endswith(".exe"):
        stem = stem[:-4]
    return stem[:1].upper() + stem[1:] if stem else ""


class WindowsSourceAppProvider(SourceAppProvider):
    """Windows 实现：pywin32 优先，ctypes 兜底。"""

    def __init__(self) -> None:
        self._available = False
        self._mode = "none"  # "pywin32" / "ctypes" / "none"
        self._win32gui = None
        self._win32process = None
        self._psutil = None
        self._ctypes = None
        self._wintypes = None

        # 先试 pywin32
        try:
            import win32gui  # type: ignore
            import win32process  # type: ignore
            self._win32gui = win32gui
            self._win32process = win32process
            self._mode = "pywin32"
            self._available = True
        except ImportError as e:
            logger.info(f"pywin32 不可用: {e}, 尝试 ctypes fallback")

        # psutil 不强求，但能大幅提升 exe 路径获取成功率
        try:
            import psutil  # type: ignore
            self._psutil = psutil
        except ImportError:
            self._psutil = None

        # 如果 pywin32 没拿到，尝试 ctypes
        if not self._available:
            try:
                import ctypes
                from ctypes import wintypes
                self._ctypes = ctypes
                self._wintypes = wintypes
                self._mode = "ctypes"
                self._available = True
            except Exception as e:  # pragma: no cover - 非 Windows 才可能走到
                logger.info(f"ctypes Win32 fallback 初始化失败: {e}")

    @property
    def is_available(self) -> bool:
        return self._available

    # --- 主入口 -------------------------------------------------------

    def get_current(self) -> SourceApp:
        if not self._available:
            return SourceApp()
        try:
            if self._mode == "pywin32":
                return self._get_via_pywin32()
            if self._mode == "ctypes":
                return self._get_via_ctypes()
        except Exception as e:
            logger.warning(f"Windows get_current 失败: {e}")
        return SourceApp()

    # --- pywin32 路径 --------------------------------------------------

    def _get_via_pywin32(self) -> SourceApp:
        hwnd = self._win32gui.GetForegroundWindow()
        if not hwnd:
            return SourceApp()
        try:
            title = self._win32gui.GetWindowText(hwnd) or ""
        except Exception:
            title = ""
        try:
            _tid, pid = self._win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = 0

        exe_path = ""
        exe_base = ""
        if pid and self._psutil is not None:
            try:
                proc = self._psutil.Process(pid)
                exe_base = proc.name() or ""
                try:
                    exe_path = proc.exe() or ""
                except Exception:
                    exe_path = ""
            except Exception:
                pass

        if not exe_base and exe_path:
            exe_base = os.path.basename(exe_path)

        return SourceApp(
            app_name=_pretty_app_name(exe_base),
            bundle_id=exe_base.lower(),
            exe_path=exe_path,
            window_title=title,
        )

    # --- ctypes 路径 ---------------------------------------------------

    def _get_via_ctypes(self) -> SourceApp:  # pragma: no cover - 真实跑需要 Windows
        ctypes = self._ctypes
        wintypes = self._wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return SourceApp()

        # 窗口标题
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""

        # pid
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        exe_path = ""
        if pid.value:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if h:
                try:
                    size = wintypes.DWORD(1024)
                    path_buf = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(h, 0, path_buf, ctypes.byref(size)):
                        exe_path = path_buf.value or ""
                finally:
                    kernel32.CloseHandle(h)

        # 某些情况下可用 psutil 兜底
        if not exe_path and self._psutil is not None and pid.value:
            try:
                exe_path = self._psutil.Process(pid.value).exe() or ""
            except Exception:
                pass

        exe_base = os.path.basename(exe_path) if exe_path else ""
        return SourceApp(
            app_name=_pretty_app_name(exe_base),
            bundle_id=exe_base.lower(),
            exe_path=exe_path,
            window_title=title,
        )
