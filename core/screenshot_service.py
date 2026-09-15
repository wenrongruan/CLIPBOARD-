"""截图服务：区域 / 全屏 / 窗口三种取景，产出图片并存入剪贴板历史。

为什么 macOS 用子进程而不是 ScreenCaptureKit
--------------------------------------------
`/usr/sbin/screencapture` 自带框选和窗口选择 UI（含空格切换、Esc 取消、
多屏拼接、Retina 全分辨率），是一条成熟且零额外依赖的路径；自己用
ScreenCaptureKit 实现要额外引入 pyobjc 框架并重写整套选择交互，收益为负。
代价是首次使用需要 macOS 的「屏幕录制」权限（由系统 TCC 弹窗授权），
`has_screen_recording_permission()` / `request_screen_recording_permission()`
就是给上层做权限引导用的。

其他平台走 Qt：全屏用 `QScreen.grabWindow`，区域/窗口用
`ui/screenshot_overlay.py` 的冻结屏幕遮罩框选（Qt 没有现成控件）。

线程模型
--------
`capture()` 立即返回，真正的取景在后台线程完成（`screencapture` 是阻塞子进程，
用户可能拖十几秒才松手），入库也在后台线程，最后通过 Qt 信号把
`ClipboardItem` 投回主线程——`QClipboard` 只能在 GUI 线程操作，所以
「复制到剪贴板」这一步必须在主线程做。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"

#: 取景模式
REGION = "region"
FULL = "full"
WINDOW = "window"
SCREENSHOT_MODES = (REGION, FULL, WINDOW)

#: 截图条目的 source_app 标记，方便在历史里按来源检索
SCREENSHOT_SOURCE_APP = "screenshot"

_MACOS_SCREENCAPTURE = "/usr/sbin/screencapture"

# 交互式框选可能持续很久（用户慢慢拖），给足超时但不无限等；
# 全屏是即时的，超时只用于兜住 screencapture 卡死。
_INTERACTIVE_TIMEOUT_S = 300.0
_NON_INTERACTIVE_TIMEOUT_S = 30.0


# ---------------------------------------------------------------------------
# macOS「屏幕录制」权限
# ---------------------------------------------------------------------------


def has_screen_recording_permission() -> bool:
    """macOS: 是否已授予「屏幕录制」权限。

    非 macOS，或 pyobjc-framework-Quartz 不可用导致探测失败时，一律返回 True，
    让流程继续走——宁可让 screencapture 自己失败，也不要在能力探测上误判成
    "没权限"而把功能整条挡死。
    """
    if not IS_MACOS:
        return True
    try:
        from Quartz import CGPreflightScreenCaptureAccess
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        return True


def request_screen_recording_permission() -> bool:
    """macOS: 主动触发一次系统 TCC 授权弹窗（仅有首次会真正弹）。

    已在「系统设置 → 隐私与安全性 → 屏幕录制」里被明确拒绝过时，系统不会再弹，
    此时返回 False，调用方需要引导用户手动去设置里勾选。
    """
    if not IS_MACOS:
        return True
    try:
        from Quartz import CGRequestScreenCaptureAccess
        return bool(CGRequestScreenCaptureAccess())
    except Exception:
        logger.debug("CGRequestScreenCaptureAccess 不可用", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 取景
# ---------------------------------------------------------------------------


def build_macos_args(mode: str, out_path: str) -> list:
    """拼装 screencapture 参数（独立出来便于单测断言）。

    - ``-x`` 静音；``-t png`` 固定 PNG（无损，适合截图）
    - region：``-i`` 交互 + ``-s`` 只允许鼠标框选（空格不再切到窗口模式，
      因为窗口取景已经是独立入口）
    - window：``-i`` 交互 + ``-w`` 只允许窗口选择 + ``-o`` 去掉窗口阴影
    - full：``-m`` 只截主显示器，多屏时行为可预期
    """
    args = [_MACOS_SCREENCAPTURE, "-x", "-t", "png"]
    if mode == REGION:
        args += ["-i", "-s"]
    elif mode == WINDOW:
        args += ["-i", "-w", "-o"]
    else:
        args += ["-m"]
    args.append(out_path)
    return args


def capture_macos(mode: str) -> Optional[bytes]:
    """调用系统 screencapture 取图。

    返回 PNG 字节；用户按 Esc / 右键取消、调用失败或超时都返回 None。
    取消不是错误，上层应当静默忽略。
    """
    fd, out_path = tempfile.mkstemp(prefix="sc_shot_", suffix=".png")
    os.close(fd)
    try:
        args = build_macos_args(mode, out_path)
        timeout = (
            _NON_INTERACTIVE_TIMEOUT_S if mode == FULL else _INTERACTIVE_TIMEOUT_S
        )
        proc = subprocess.run(args, capture_output=True, timeout=timeout)
        if proc.returncode != 0:
            # Esc 取消时 screencapture 返回非 0 且不写文件，属正常路径。
            # 其他非 0 也大多来自权限不足，交给上层统一提示。
            logger.info(
                "screencapture 未产出图片 (mode=%s, rc=%s)", mode, proc.returncode
            )
            return None
        # mkstemp 建出来的空文件在取消时仍然是 0 字节，必须靠大小判定。
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return None
        with open(out_path, "rb") as f:
            return f.read()
    except subprocess.TimeoutExpired:
        logger.warning("screencapture 超时 (mode=%s)", mode)
        return None
    except Exception as e:
        logger.warning(f"screencapture 调用失败: {e}", exc_info=True)
        return None
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _pixmap_to_png(pixmap) -> Optional[bytes]:
    from PySide6.QtCore import QBuffer, QIODevice

    if pixmap is None or pixmap.isNull():
        return None
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        if not pixmap.save(buf, "PNG"):
            return None
        return bytes(buf.data())
    finally:
        buf.close()


def capture_qt(mode: str) -> Optional[bytes]:
    """非 macOS 回退实现。必须在 GUI 线程调用（Qt 抓屏不是线程安全的）。

    窗口模式在非 macOS 上退化为区域框选：跨进程枚举并抓取任意窗口在 Qt 里没有
    可靠实现，与其做一个经常抓错的版本，不如让用户手动框一下。
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return None

    if mode == FULL:
        screen = app.primaryScreen()
        if screen is None:
            return None
        return _pixmap_to_png(screen.grabWindow(0))

    try:
        from ui.screenshot_overlay import select_region
    except Exception as e:
        logger.warning(f"区域框选组件不可用: {e}", exc_info=True)
        return None
    return _pixmap_to_png(select_region())


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


class ScreenshotService(QObject):
    """截图 → 入库 → 复制到剪贴板 的编排。

    只依赖 ClipboardMonitor 的公开入库接口，不直接碰数据库。
    """

    #: 截图已存入历史（携带 ClipboardItem）
    item_saved = Signal(object)
    #: 截图失败（携带面向用户的错误文案）
    capture_failed = Signal(str)
    #: macOS 缺「屏幕录制」权限，需要上层弹引导
    permission_required = Signal()

    # 内部信号：把后台线程的产物投回主线程（跨线程自动走 QueuedConnection）
    _persisted = Signal(object)
    _worker_failed = Signal(str)

    def __init__(self, monitor=None, parent=None):
        super().__init__(parent)
        self._monitor = monitor
        self._in_progress = False
        self._persisted.connect(self._on_persisted)
        self._worker_failed.connect(self._on_worker_failed)

    # ---- 对外入口 ----

    def capture(self, mode: str = REGION) -> bool:
        """发起一次截图。返回 False 表示本次请求未被接受（原因见信号）。"""
        if mode not in SCREENSHOT_MODES:
            self.capture_failed.emit(f"未知的截图模式: {mode}")
            return False
        if self._in_progress:
            logger.info("已有截图在进行中，忽略本次请求 (mode=%s)", mode)
            return False
        if self._monitor is None:
            self.capture_failed.emit("剪贴板服务不可用，无法保存截图")
            return False
        if not has_screen_recording_permission():
            self.permission_required.emit()
            return False

        self._in_progress = True
        if IS_MACOS:
            threading.Thread(
                target=self._capture_and_persist,
                args=(mode,),
                name="screenshot-capture",
                daemon=True,
            ).start()
        else:
            # Qt 抓屏 / 遮罩框选必须在 GUI 线程上跑，拿到字节后再丢给后台入库，
            # 避免解码+缩略图阻塞界面。
            data = capture_qt(mode)
            if not data:
                self._in_progress = False
                return True
            threading.Thread(
                target=self._persist_only,
                args=(data,),
                name="screenshot-persist",
                daemon=True,
            ).start()
        return True

    def is_busy(self) -> bool:
        return self._in_progress

    # ---- 托盘 / 热键用的无参槽（QMetaObject.invokeMethod 需要槽名） ----

    @Slot()
    def capture_region(self) -> None:
        self.capture(REGION)

    @Slot()
    def capture_full(self) -> None:
        self.capture(FULL)

    @Slot()
    def capture_window(self) -> None:
        self.capture(WINDOW)

    # ---- 后台线程 ----

    def _capture_and_persist(self, mode: str) -> None:
        """macOS 路径：取景 + 入库都在后台线程完成。"""
        try:
            data = capture_macos(mode)
        except Exception as e:  # capture_macos 自己已兜底，这里是最后一道保险
            logger.error(f"截图取景异常: {e}", exc_info=True)
            self._worker_failed.emit(str(e))
            return
        if not data:
            # 取消：静默复位，不打扰用户
            self._persisted.emit(None)
            return
        self._persist_only(data)

    def _persist_only(self, data: bytes) -> None:
        try:
            item = self._monitor.persist_image_bytes(
                data,
                source_app=SCREENSHOT_SOURCE_APP,
                preview_prefix=self._preview_prefix(),
            )
        except Exception as e:
            logger.error(f"截图入库失败: {e}", exc_info=True)
            self._worker_failed.emit(str(e))
            return
        if item is None:
            # 只可能是被 max_image_size_kb 限制拦下（重复图会返回已有条目）
            self._worker_failed.emit("__TOO_LARGE__")
            return
        self._persisted.emit(item)

    @staticmethod
    def _preview_prefix() -> str:
        try:
            from i18n import t
            return t("screenshot")
        except Exception:
            return "截图"

    # ---- 主线程回调 ----

    @Slot(object)
    def _on_persisted(self, item) -> None:
        self._in_progress = False
        if item is None:
            return
        # QClipboard 只能在 GUI 线程操作，所以复制留在这里；
        # copy_to_clipboard 内部会同步 _last_image_hash，避免
        # 剪贴板监听把这张图当成"用户新复制的内容"再存一遍。
        try:
            from config import settings
            if settings().screenshot_copy_to_clipboard:
                self._monitor.copy_to_clipboard(item)
        except Exception:
            logger.debug("截图复制到剪贴板失败", exc_info=True)
        self.item_saved.emit(item)

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        self._in_progress = False
        if message == "__TOO_LARGE__":
            try:
                from i18n import t
                message = t("screenshot_too_large")
            except Exception:
                message = "截图过大，未保存（超过图片大小上限）"
        self.capture_failed.emit(message)
