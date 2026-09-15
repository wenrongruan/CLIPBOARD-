import atexit
import sys
import os
import time
import logging
import platform
import threading
from contextlib import nullcontext

_STARTUP_T0 = time.time()
_STARTUP_PERF_T0 = time.perf_counter()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QCursor
from PySide6.QtCore import Qt, QMetaObject, Q_ARG, QUrl, QTimer
from PySide6.QtGui import QDesktopServices

IS_MACOS = platform.system() == "Darwin"

from config import (
    settings,
    flush_settings,
    get_cloud_access_token,
    get_effective_hotkey,
    get_effective_screenshot_hotkey,
)
from i18n import t, set_language
from core.app_context import AppContext
from core.db_factory import create_database_manager
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.screenshot_service import (
    ScreenshotService,
    REGION as SCREENSHOT_REGION,
    FULL as SCREENSHOT_FULL,
    WINDOW as SCREENSHOT_WINDOW,
)
from core.sync_service import SyncService
from core.plugin_manager import PluginManager
from core.startup_metrics import StartupMetrics
from ui.main_window import MainWindow

# 全局热键支持
# macOS 上不直接用 pynput，改走 NSEvent monitor（详见 core/macos_hotkey.py 的 Why）。
# 其他平台仍使用 pynput.
keyboard = None
HOTKEY_AVAILABLE = False
if IS_MACOS:
    try:
        from core.macos_hotkey import MacOSGlobalHotkey  # noqa: F401
        HOTKEY_AVAILABLE = True
    except ImportError:
        HOTKEY_AVAILABLE = False
else:
    try:
        from pynput import keyboard
        HOTKEY_AVAILABLE = True
    except ImportError:
        HOTKEY_AVAILABLE = False

# 日志配置：默认 WARNING，设置 SC_DEBUG=1 可切到 DEBUG 并同时落盘到 logs/debug.log
_SC_DEBUG = os.environ.get("SC_DEBUG", "").strip() not in ("", "0", "false", "False")
_SC_STARTUP_METRICS = os.environ.get("SC_STARTUP_METRICS", "").strip() not in ("", "0", "false", "False")
_log_level = logging.DEBUG if _SC_DEBUG else logging.WARNING
_log_handlers = [logging.StreamHandler()]
if _SC_DEBUG:
    try:
        _log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(_log_dir, exist_ok=True)
        _log_handlers.append(logging.FileHandler(os.path.join(_log_dir, "debug.log"), encoding="utf-8"))
    except Exception:
        pass
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s.%(msecs)03d - %(levelname)s - %(name)s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
    force=True,
)
logger = logging.getLogger(__name__)
if _SC_DEBUG:
    logger.warning(f"[startup] SC_DEBUG 已启用，DEBUG 日志将写入 logs/debug.log  t=+{time.time()-_STARTUP_T0:.2f}s")


def get_app_icon() -> QIcon:
    """获取应用图标"""
    # 尝试加载生成的图标
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 优先使用 ICO 文件（Windows）或 PNG 文件
    if IS_MACOS:
        icon_path = os.path.join(base_dir, "icons", "icon_macos.png")
    else:
        icon_path = os.path.join(base_dir, "icons", "app.ico")

    if os.path.exists(icon_path):
        return QIcon(icon_path)

    # 备用：使用 icon.png
    png_path = os.path.join(base_dir, "icon.png")
    if os.path.exists(png_path):
        return QIcon(png_path)

    # 最后备用：生成简单图标
    return create_fallback_icon()


def create_fallback_icon() -> QIcon:
    """创建备用图标（当图标文件不存在时）"""
    # macOS 菜单栏图标需要较小尺寸，且支持深色/浅色模式
    if IS_MACOS:
        size = 22
        # macOS 菜单栏图标使用模板图像（黑色图标，系统自动适配深色模式）
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # 使用黑色绘制，macOS 会自动处理深色模式
        painter.setBrush(QColor("#000000"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(3, 2, 16, 18, 2, 2)

        painter.setBrush(QColor("#000000"))
        painter.drawRoundedRect(7, 0, 8, 4, 1, 1)

        painter.setPen(QColor("#ffffff"))
        painter.drawLine(5, 8, 17, 8)
        painter.drawLine(5, 12, 17, 12)
        painter.drawLine(5, 16, 14, 16)

        painter.end()

        icon = QIcon(pixmap)
        # 设置为模板图像，macOS 会自动适配深色/浅色模式
        icon.setIsMask(True)
        return icon
    else:
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制剪贴板形状
        painter.setBrush(QColor("#0078d4"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(8, 4, 48, 56, 6, 6)

        # 绘制夹子
        painter.setBrush(QColor("#005a9e"))
        painter.drawRoundedRect(20, 0, 24, 12, 4, 4)

        # 绘制纸张线条
        painter.setPen(QColor("#ffffff"))
        painter.drawLine(16, 24, 48, 24)
        painter.drawLine(16, 34, 48, 34)
        painter.drawLine(16, 44, 40, 44)

        painter.end()

        return QIcon(pixmap)


class ClipboardApp:
    def __init__(self):
        self.startup_metrics = StartupMetrics(started_at=_STARTUP_PERF_T0)
        with self.startup_metrics.phase("qt_app_init"):
            self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)  # 托盘模式
        # Why: update_settings 延迟 2s 合并落盘，Qt 正常退出路径（Cmd+Q、
        # SIGTERM 下的 aboutToQuit）若不兜底会丢失未 flush 的改动。
        self.app.aboutToQuit.connect(flush_settings)

        from PySide6.QtGui import QPixmapCache
        QPixmapCache.setCacheLimit(32768)  # 缩略图像素缓存上限，单位 KB（32 MB），减少翻页/搜索时重复解码

        # 初始化语言设置
        set_language(settings().language)

        # macOS 特定设置
        if IS_MACOS:
            # 设置应用名称（显示在菜单栏）
            self.app.setApplicationName(t("app_name"))
            # macOS 上隐藏 Dock 图标（作为菜单栏应用运行）
            self.app.setQuitOnLastWindowClosed(False)

        # 初始化组件
        with self.startup_metrics.phase("init_components"):
            self._init_components()

        # 创建系统托盘
        with self.startup_metrics.phase("create_tray_icon"):
            self._create_tray_icon()

        # 创建主窗口
        with self.startup_metrics.phase("create_main_window"):
            self._create_main_window()

        # 初始化全局热键
        with self.startup_metrics.phase("init_hotkey"):
            self._init_hotkey()

        with self.startup_metrics.phase("startup_health_flush"):
            self._collect_degraded_store_health()
            self._collect_mysql_fallback_health()
            self._flush_startup_health_notifications()
        self.startup_metrics.mark("event_loop_ready")

    def _init_components(self):
        """初始化核心组件（Phase 1: 全部走 AppContext）"""
        logger.debug(f"[startup] _init_components 开始 t=+{time.time()-_STARTUP_T0:.2f}s")
        _t = time.time()
        # Phase 1: 通过 AppContext 装配所有 service
        self.ctx = AppContext.bootstrap()
        # 兼容旧字段（下方代码仍以 self.xxx 形式访问）
        self.db_manager = self.ctx.db
        self.repository = self.ctx.repository
        logger.debug(f"[startup] AppContext.bootstrap 用时 {time.time()-_t:.3f}s")
        # 截图服务复用剪贴板监控的入库链路；在这里建是因为托盘菜单比主窗口先构造。
        self.screenshot_service = ScreenshotService(self.ctx.clipboard_monitor)
        self.screenshot_service.item_saved.connect(self._on_screenshot_saved)
        self.screenshot_service.capture_failed.connect(self._on_screenshot_failed)
        self.screenshot_service.permission_required.connect(
            self._prompt_screen_recording_permission
        )
        # aboutToQuit 兜底：保证非正常退出路径也能清理 db / monitor / plugin
        self.app.aboutToQuit.connect(self._shutdown_context)

    def _create_tray_icon(self):
        """创建系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self.app)
        # macOS 托盘需模板图(setIsMask)才能跟随深色菜单栏;Dock 仍用彩色 get_app_icon
        self.tray_icon.setIcon(create_fallback_icon() if IS_MACOS else get_app_icon())
        self.tray_icon.setToolTip(t("app_name"))

        # 创建托盘菜单
        menu = QMenu()
        # 持有引用：菜单里嵌了子菜单，父 QMenu 若是临时对象会被 GC 掉，
        # 表现为右键后子项失效。
        self.tray_menu = menu

        show_action = QAction(t("show_window"), menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        menu.addSeparator()

        # 截图子菜单：区域 / 全屏 / 窗口
        screenshot_menu = QMenu(t("screenshot"), menu)
        for mode, label_key in (
            (SCREENSHOT_REGION, "screenshot_region"),
            (SCREENSHOT_FULL, "screenshot_full"),
            (SCREENSHOT_WINDOW, "screenshot_window"),
        ):
            action = QAction(t(label_key), screenshot_menu)
            action.triggered.connect(
                lambda _checked=False, m=mode: self._request_screenshot(m)
            )
            screenshot_menu.addAction(action)
        menu.addMenu(screenshot_menu)

        menu.addSeparator()

        quit_action = QAction(t("quit"), menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _create_main_window(self):
        """创建主窗口（Phase 1: 所有 service 从 AppContext 获取）"""
        logger.debug(f"[startup] _create_main_window 开始 t=+{time.time()-_STARTUP_T0:.2f}s")
        ctx = self.ctx

        # 暴露旧字段路径，保证 main.py 内部其他方法兼容
        self.clipboard_monitor = ctx.clipboard_monitor
        self.sync_service = ctx.sync_service
        self.cloud_api = ctx.cloud_api
        self.cloud_sync_service = ctx.cloud_sync_service
        self.file_sync_service = ctx.file_sync_service
        self.file_repository = ctx.file_repository
        self.entitlement_service = ctx.entitlement_service
        self._cloud_sync_error = ctx._cloud_sync_error

        # 云端同步开启后，剪贴板新增条目要进上传队列；云端启动失败时给用户托盘提示
        if ctx.cloud_sync_service is not None:
            self.clipboard_monitor.item_added.connect(self._on_new_item_for_cloud)
        elif ctx._cloud_sync_error and get_cloud_access_token():
            self._record_health_issue(
                "cloud_sync",
                "warning",
                "云端同步启动失败，已降级到本地存储。请检查网络或查看日志。",
            )

        # 插件加载（AppContext 只构造 PluginManager，加载交给 main 在 UI 时刻执行）
        self.plugin_manager = ctx.plugin_manager

        # v3.4 服务
        self.space_service = ctx.space_service
        self.tag_service = ctx.tag_service
        self.share_service = ctx.share_service

        _t = time.time()
        self.main_window = MainWindow(ctx=ctx)
        logger.debug(f"[startup] MainWindow(__init__) 用时 {time.time()-_t:.3f}s, 累计 t=+{time.time()-_STARTUP_T0:.2f}s")

        # 连接退出信号
        self.main_window.quit_requested.connect(self._quit)

        # 启动服务
        self.clipboard_monitor.monitor_unhealthy.connect(
            lambda msg: self._on_runtime_health_warning("clipboard_monitor", msg)
        )
        self.clipboard_monitor.monitor_stopped.connect(
            lambda msg: self._on_runtime_health_warning("clipboard_monitor", msg)
        )
        self.clipboard_monitor.start()
        self.sync_service.start()
        QTimer.singleShot(1500, self._load_plugins_deferred)
        if self.cloud_sync_service:
            # 云端拉取的新条目也通知 UI 刷新
            self.cloud_sync_service.new_items_available.connect(
                self.main_window._on_new_items
            )
            # 云端写入本地后，推进 SyncService 游标避免重复通知
            self.cloud_sync_service.new_items_available.connect(
                self._advance_sync_after_cloud
            )
            # Why: 主窗口刚 show 时，UI 渲染、插件加载、剪贴板监听写库会抢主线程
            # 和 SQLite 锁；首次 pull/push 及其主线程 DB 扫描会让快速操作卡顿。
            # 延后 20 秒再启动云端同步，给 UI 留出稳定窗口。
            QTimer.singleShot(20000, self._start_cloud_sync_deferred)
        if self.cloud_api and settings().files_sync_enabled:
            QTimer.singleShot(20000, self._start_file_sync_deferred)

    def _load_plugins_deferred(self):
        """Load optional plugins after the core clipboard services are running."""
        if not getattr(self, "plugin_manager", None):
            return
        try:
            _t = time.time()
            with self._startup_phase("plugin_load_deferred"):
                self.plugin_manager.load_plugins()
            logger.debug(
                f"[startup] PluginManager.load_plugins deferred 用时 {time.time()-_t:.3f}s"
            )
        except Exception as e:
            logger.warning(f"插件加载失败: {e}", exc_info=True)
            self._on_runtime_health_warning(
                "plugin_manager",
                "插件加载失败，基础剪贴板功能仍可使用。",
            )

    def _startup_phase(self, name: str):
        metrics = getattr(self, "startup_metrics", None)
        return metrics.phase(name) if metrics is not None else nullcontext()

    def _start_cloud_sync_deferred(self):
        """Start optional cloud sync after the local clipboard path is ready."""
        self._refresh_optional_services_from_context()
        if not getattr(self, "cloud_sync_service", None):
            return
        try:
            with self._startup_phase("cloud_sync_start_deferred"):
                self.cloud_sync_service.start()
            if not getattr(self, "_cloud_cursor_atexit_registered", False):
                atexit.register(self._atexit_persist_cloud_cursor)
                self._cloud_cursor_atexit_registered = True
        except Exception as e:
            logger.warning(f"云端同步启动失败: {e}", exc_info=True)
            self._on_runtime_health_warning(
                "cloud_sync",
                "云端同步启动失败，已降级到本地剪贴板历史。",
            )

    def _start_file_sync_deferred(self):
        """Start optional file sync after the local clipboard path is ready."""
        try:
            # 登录/登出可能发生在这个 20 秒延迟窗口内。以 AppContext 当前值
            # 为准，避免重启已停止的旧 service 或重复创建第二套同步线程。
            self._refresh_optional_services_from_context()
            with self._startup_phase("file_sync_start_deferred"):
                if not getattr(self, "file_sync_service", None):
                    self._ensure_file_sync_services()
                if not getattr(self, "file_sync_service", None):
                    return
                self.file_sync_service.start()
            if not getattr(self, "_file_cursor_atexit_registered", False):
                atexit.register(self._atexit_persist_file_cursor)
                self._file_cursor_atexit_registered = True
        except Exception as e:
            logger.warning(f"文件云同步启动失败: {e}", exc_info=True)
            self._on_runtime_health_warning(
                "file_sync",
                "文件云同步启动失败，剪贴板文本和图片历史仍可继续使用。",
            )

    def _refresh_optional_services_from_context(self):
        """把动态登录/登出后的可选云服务引用同步回应用壳。"""
        ctx = getattr(self, "ctx", None)
        if ctx is None:
            return
        for name in (
            "cloud_api",
            "cloud_sync_service",
            "entitlement_service",
            "file_repository",
            "file_sync_service",
        ):
            # 兼容测试/旧调用方传入的精简 context；只有 context 明确声明
            # 该字段时才让它覆盖应用壳上的现值。正式 AppContext 始终声明全量字段，
            # 因而登出后的显式 None 仍能正确清掉旧引用。
            if hasattr(ctx, name):
                setattr(self, name, getattr(ctx, name))

    def _ensure_file_sync_services(self):
        """Build optional file-sync services on demand."""
        self._refresh_optional_services_from_context()
        if not getattr(self, "cloud_api", None):
            return
        if getattr(self, "entitlement_service", None) is None:
            from core.entitlement_service import get_entitlement_service
            self.entitlement_service = get_entitlement_service(
                cloud_api=self.cloud_api,
                repository=self.repository,
            )
            self.entitlement_service.refresh_async()
        else:
            self.entitlement_service.set_cloud_api(self.cloud_api)

        if getattr(self, "file_repository", None) is None:
            from core.file_repository import CloudFileRepository
            self.file_repository = CloudFileRepository(self.db_manager)

        if getattr(self, "file_sync_service", None) is None:
            from core.file_sync_service import FileCloudSyncService
            self.file_sync_service = FileCloudSyncService(
                self.file_repository,
                self.cloud_api,
                self.entitlement_service,
                self.repository,
            )

        if getattr(self, "ctx", None) is not None:
            self.ctx.entitlement_service = self.entitlement_service
            self.ctx.file_repository = self.file_repository
            self.ctx.file_sync_service = self.file_sync_service
        if getattr(self, "main_window", None) is not None:
            self.main_window.entitlement_service = self.entitlement_service
            self.main_window.file_repository = self.file_repository
            self.main_window.file_sync_service = self.file_sync_service
            controller = getattr(self.main_window, "cloud_controller", None)
            if controller is not None:
                controller.bootstrap_files_stack_after_login()

    def _shutdown_context(self):
        """aboutToQuit 兜底：让 AppContext 清理基础资源。

        _quit() 已经按精细顺序停掉了 monitor / plugin / db，这里只在 AppContext
        还活着时做一次 idempotent 收尾，避免非正常退出路径（Cmd+Q、SIGTERM 等）
        漏掉 ctx.shutdown()。重复调用是安全的：shutdown() 内部 try/except 包裹了
        每一步，AppContext._instance 在第一次清理后被置 None，再次 current() 会 raise。
        """
        try:
            if AppContext._instance is not None:
                AppContext._instance.shutdown()
        except Exception:
            logger.debug("AppContext shutdown 兜底失败", exc_info=True)

    def _atexit_persist_cloud_cursor(self):
        """进程退出兜底：持久化云端同步游标。"""
        try:
            if getattr(self, "cloud_sync_service", None) is not None:
                self.cloud_sync_service.persist_sync_cursor()
        except Exception:
            # atexit 阶段 logger 可能已关闭；尽力 debug 一次，失败就只能放弃
            try:
                logger.debug("atexit persist cloud cursor failed", exc_info=True)
            except Exception:
                pass

    def _atexit_persist_file_cursor(self):
        try:
            if getattr(self, "file_sync_service", None) is not None:
                self.file_sync_service.persist_sync_cursor()
        except Exception:
            try:
                logger.debug("atexit persist file cursor failed", exc_info=True)
            except Exception:
                pass

    def _record_health_issue(self, component: str, level: str, message: str) -> None:
        try:
            from core import health_reporter
            health_reporter.add_issue(component, level, message)
        except Exception:
            logger.debug("记录健康状态失败", exc_info=True)

    def _flush_startup_health_notifications(self):
        """启动结束后把所有降级状态合并成一条托盘提示。"""
        try:
            from core import health_reporter
            message = health_reporter.format_summary(limit=3)
            if not message:
                return
            if not hasattr(self, "tray_icon") or self.tray_icon is None:
                return
            self.tray_icon.showMessage(
                t("app_name"),
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )
        except Exception:
            logger.debug("健康状态聚合提示发送失败", exc_info=True)

    def _on_runtime_health_warning(self, component: str, message: str):
        self._record_health_issue(component, "warning", message)
        try:
            if hasattr(self, "tray_icon") and self.tray_icon is not None:
                self.tray_icon.showMessage(
                    t("app_name"),
                    message,
                    QSystemTrayIcon.MessageIcon.Warning,
                    8000,
                )
        except Exception:
            logger.debug("运行时健康状态提示发送失败", exc_info=True)

    def _collect_mysql_fallback_health(self):
        """若 MySQL 初始化失败已降级到本地 SQLite，登记健康状态。"""
        try:
            from core.db_factory import get_mysql_fallback_reason
            reason = get_mysql_fallback_reason()
            if not reason:
                return
            self._record_health_issue(
                "mysql",
                "warning",
                f"MySQL 连接失败，已降级到本地数据库（同步暂不生效）。请检查设置中的 MySQL 配置。\n原因：{reason}",
            )
        except Exception:
            logger.debug("MySQL 降级状态登记失败", exc_info=True)

    def _collect_degraded_store_health(self):
        """若凭据存储降级到非 keyring 后端，登记健康状态。"""
        try:
            from utils import secure_store
            if not secure_store.is_degraded():
                return
            backend = secure_store.get_active_backend()
            self._record_health_issue(
                "secure_store",
                "warning",
                f"当前密钥未加密存储（{backend}），建议安装 keyring 库以提升凭据安全性：pip install keyring",
            )
        except Exception:
            logger.debug("凭据存储降级状态登记失败", exc_info=True)

    def _on_new_item_for_cloud(self, item):
        """剪贴板新条目回调 — 加入云端上传队列"""
        if self.cloud_sync_service:
            self.cloud_sync_service.enqueue_upload(item)

    def _advance_sync_after_cloud(self, items):
        """云端拉取写入本地后，推进 SyncService 游标"""
        if items:
            max_id = max((item.id for item in items if item.id), default=0)
            if max_id:
                self.sync_service.advance_sync_id(max_id)

    def _show_window(self):
        """显示主窗口"""
        self.main_window.show_window()

    def _on_tray_activated(self, reason):
        """托盘图标被点击"""
        # macOS 下系统会自动弹出 contextMenu，手动 popup 会双触发，直接交还系统
        if IS_MACOS:
            return
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            # 右键点击显示菜单
            self.tray_icon.contextMenu().popup(QCursor.pos())

    def _init_hotkey(self):
        """初始化全局热键（「唤出窗口」+「截图」两个）"""
        self.hotkey_listener = None
        self.screenshot_hotkey_listener = None

        if not HOTKEY_AVAILABLE:
            logger.warning("全局热键功能不可用（macOS 缺 AppKit / 其他平台缺 pynput）")
            self._record_health_issue(
                "hotkey",
                "warning",
                "全局热键不可用：底层依赖缺失。仍可通过托盘图标打开窗口。",
            )
            return

        hotkey = get_effective_hotkey()
        screenshot_hotkey = get_effective_screenshot_hotkey()
        if screenshot_hotkey and screenshot_hotkey == hotkey:
            # 同一个键注册两次时后注册的会顶掉先前那个（pynput 的 dict 甚至直接塌成一项）。
            # 保留「唤出窗口」优先，截图退化为只能从托盘菜单发起。
            logger.warning(f"截图热键与唤出窗口热键相同 ({hotkey})，跳过截图热键注册")
            self._record_health_issue(
                "hotkey",
                "warning",
                f"截图热键与「显示窗口」热键冲突（都是 {hotkey}），截图热键未生效；"
                "可在设置 → 通用里改成不同的组合，或从托盘菜单发起截图。",
            )
            screenshot_hotkey = ""

        if not hotkey and not screenshot_hotkey:
            return

        # macOS: pynput 的 CGEventTap 后台线程在新版系统上按 CapsLock 系列键
        # 会触发 TSM dispatch_assert_queue 闪退（SIGTRAP）。改用 NSEvent monitor,
        # 回调走主线程,绕开这条崩溃链路。详见 core/macos_hotkey.py 的 Why。
        if IS_MACOS:
            if not self._has_accessibility_permission():
                logger.warning("未授予辅助功能/输入监控权限,跳过全局热键监听")
                self._record_health_issue(
                    "hotkey",
                    "warning",
                    "全局热键不可用：缺少输入监控权限。仍可通过菜单栏图标打开窗口。",
                )
                self._prompt_input_monitoring_permission()
                return
            # 权限没问题时才注册；若两个热键里有任何一个装不上（典型原因就是缺权限），
            # 只在最后统一弹一次引导，避免连弹两个对话框。
            self._hotkey_permission_suspect = False
            self.hotkey_listener = self._register_macos_hotkey(
                hotkey, self._on_hotkey_pressed, "唤出窗口"
            )
            self.screenshot_hotkey_listener = self._register_macos_hotkey(
                screenshot_hotkey, self._on_screenshot_hotkey, "截图"
            )
            if self._hotkey_permission_suspect:
                self._prompt_input_monitoring_permission()
            return

        # 非 macOS：继续走 pynput（GlobalHotKeys 用 dict 一次注册多个组合键）
        mapping = {}
        if hotkey:
            mapping[hotkey] = self._on_hotkey_pressed
        if screenshot_hotkey:
            mapping[screenshot_hotkey] = self._on_screenshot_hotkey
        if not mapping:
            return
        try:
            self.hotkey_listener = keyboard.GlobalHotKeys(mapping)
            self.hotkey_listener.start()
            logger.info(f"全局热键已注册: {sorted(mapping)}")
        except Exception as e:
            logger.error(f"注册全局热键失败: {e}")
            self._record_health_issue(
                "hotkey",
                "warning",
                f"全局热键注册失败：{e}",
            )

    def _register_macos_hotkey(self, spec: str, callback, label: str):
        """注册一个 macOS 全局热键（NSEvent monitor）。spec 为空或注册失败返回 None。"""
        if not spec:
            return None
        try:
            from core.macos_hotkey import MacOSGlobalHotkey
            listener = MacOSGlobalHotkey(spec, callback)
            if listener.start():
                logger.info(f"全局热键已注册（NSEvent monitor）: {label} = {spec}")
                return listener
            logger.warning(f"{label}热键装载失败,疑似缺少输入监控权限")
            self._record_health_issue(
                "hotkey",
                "warning",
                f"{label}热键监听未启用，疑似缺少输入监控权限。仍可通过菜单栏图标操作。",
            )
            # macOS 在缺「输入监控」权限时 addGlobalMonitor 返回 None 但不抛异常，
            # 这是唯一能区分"装不上"和"其他异常"的信号，交给调用方合并弹一次引导。
            self._hotkey_permission_suspect = True
            return None
        except Exception as e:
            logger.error(f"注册 macOS {label}热键失败: {e}", exc_info=True)
            self._record_health_issue(
                "hotkey",
                "warning",
                f"{label}热键注册失败：{e}",
            )
            return None

    @staticmethod
    def _has_accessibility_permission() -> bool:
        """macOS: 检测「输入监控」权限（pynput 全局热键实际依赖此权限，非辅助功能）。"""
        try:
            # CGPreflightListenEventAccess 对应 TCC kTCCServiceListenEvent
            from Quartz import CGPreflightListenEventAccess
            return bool(CGPreflightListenEventAccess())
        except Exception:
            # pyobjc-framework-Quartz 未装或符号缺失时安全降级，让流程继续
            return True

    def _check_hotkey_listener_alive(self):
        """macOS: 3 秒后检查热键监听是否真正在运行"""
        listener = getattr(self, "hotkey_listener", None)
        if listener is None:
            return
        # pynput Listener 通常有 running 属性；兜底用 is_alive()
        running = getattr(listener, "running", None)
        if running is None:
            is_alive = getattr(listener, "is_alive", None)
            running = bool(is_alive()) if callable(is_alive) else True
        if not running:
            logger.warning("pynput 热键监听未运行，疑似缺少输入监控权限")
            self._on_runtime_health_warning(
                "hotkey",
                "全局热键监听未运行，疑似缺少输入监控权限。仍可通过托盘图标打开窗口。",
            )
            self._prompt_input_monitoring_permission()

    def _prompt_input_monitoring_permission(self):
        """macOS: 引导用户授权输入监控权限"""
        msg = QMessageBox()
        msg.setWindowTitle("需要「输入监控」权限")
        msg.setText(
            "共享剪贴板需要「输入监控」权限才能使用全局快捷键唤出剪贴板面板。\n\n"
            "请前往：系统设置 → 隐私与安全性 → 输入监控\n"
            "将「共享剪贴板」添加到允许列表，然后重启应用。"
        )
        msg.setInformativeText("如果暂时跳过，仍可通过点击菜单栏图标使用。")
        msg.setIcon(QMessageBox.Icon.Information)
        open_btn = msg.addButton("打开系统设置", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("暂时跳过", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            # macOS 13+ 使用新格式 URL；12 及以下保留旧格式
            mac_ver_str = platform.mac_ver()[0]  # 形如 "13.4.1"
            try:
                mac_major = int(mac_ver_str.split(".")[0])
            except (ValueError, IndexError):
                mac_major = 12
            if mac_major >= 13:
                prefs_url = (
                    "x-apple.systempreferences:com.apple.settings."
                    "PrivacySecurity.extension?Privacy_ListenEvent"
                )
            else:
                prefs_url = (
                    "x-apple.systempreferences:com.apple.preference.security"
                    "?Privacy_ListenEvent"
                )
            QDesktopServices.openUrl(QUrl(prefs_url))

    def _on_hotkey_pressed(self):
        """热键被按下时触发"""
        # 在主线程中显示窗口
        # 使用 QMetaObject.invokeMethod 从非 Qt 线程安全调用
        try:
            QMetaObject.invokeMethod(
                self.main_window,
                "show_window",
                Qt.QueuedConnection
            )
        except Exception as e:
            logger.error(f"热键触发显示窗口失败: {e}")

    # ========== 截图 ==========

    #: mode -> ScreenshotService 上的无参槽名（QMetaObject.invokeMethod 需要槽名）
    _SCREENSHOT_SLOTS = {
        SCREENSHOT_REGION: "capture_region",
        SCREENSHOT_FULL: "capture_full",
        SCREENSHOT_WINDOW: "capture_window",
    }

    def _request_screenshot(self, mode: str = SCREENSHOT_REGION):
        """发起一次截图。可被托盘菜单（主线程）或热键回调（非 Qt 线程）调用。

        取景本身由 ScreenshotService 在后台线程/主线程自行安排，这里只用
        QueuedConnection 把调用投递到主线程，保证 Qt 侧对象都在 GUI 线程被碰。
        """
        service = getattr(self, "screenshot_service", None)
        slot = self._SCREENSHOT_SLOTS.get(mode)
        if service is None or not slot:
            logger.warning(f"截图请求被忽略: service={service!r} mode={mode!r}")
            return
        try:
            QMetaObject.invokeMethod(service, slot, Qt.QueuedConnection)
        except Exception as e:
            logger.error(f"发起截图失败: {e}")

    def _on_screenshot_hotkey(self):
        """截图热键回调：默认走区域框选。"""
        self._request_screenshot(SCREENSHOT_REGION)

    def _on_screenshot_saved(self, item):
        """截图已入库（必要时也已复制到剪贴板），给用户一个轻提示。"""
        try:
            from config import settings as _settings
            copied = bool(_settings().screenshot_copy_to_clipboard)
        except Exception:
            copied = True
        message = t("screenshot_saved") if copied else t("screenshot_saved_no_copy")
        self._notify_tray(message)

    def _on_screenshot_failed(self, message: str):
        logger.warning(f"截图失败: {message}")
        self._record_health_issue("screenshot", "warning", message)
        self._notify_tray(message, warning=True)

    def _notify_tray(self, message: str, warning: bool = False):
        """托盘气泡提示。缺托盘（如 headless 测试）时静默跳过。"""
        try:
            icon = getattr(self, "tray_icon", None)
            if icon is None:
                return
            icon.showMessage(
                t("app_name"),
                message,
                QSystemTrayIcon.MessageIcon.Warning
                if warning
                else QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
        except Exception:
            logger.debug("托盘提示发送失败", exc_info=True)

    def _prompt_screen_recording_permission(self):
        """macOS: 引导用户授权「屏幕录制」权限（截图必需）。"""
        from core.screenshot_service import request_screen_recording_permission

        msg = QMessageBox()
        msg.setWindowTitle(t("screenshot_permission_title"))
        msg.setText(t("screenshot_permission_msg"))
        msg.setInformativeText(t("screenshot_permission_hint"))
        msg.setIcon(QMessageBox.Icon.Information)
        open_btn = msg.addButton(
            t("open_system_settings"), QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton(t("cancel"), QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() != open_btn:
            return

        # 先让系统弹一次 TCC 授权框（首次有效）；用户此前拒绝过就不会再弹，
        # 此时仍把设置页打开，由用户手动勾选。
        granted = request_screen_recording_permission()
        if granted:
            return
        mac_ver_str = platform.mac_ver()[0]  # 形如 "13.4.1"
        try:
            mac_major = int(mac_ver_str.split(".")[0])
        except (ValueError, IndexError):
            mac_major = 12
        if mac_major >= 13:
            prefs_url = (
                "x-apple.systempreferences:com.apple.settings."
                "PrivacySecurity.extension?Privacy_ScreenCapture"
            )
        else:
            prefs_url = (
                "x-apple.systempreferences:com.apple.preference.security"
                "?Privacy_ScreenCapture"
            )
        QDesktopServices.openUrl(QUrl(prefs_url))

    def _quit(self):
        """退出应用"""
        self._refresh_optional_services_from_context()
        # 停止热键监听（唤出窗口 + 截图两个监听器）
        for listener in (
            getattr(self, "hotkey_listener", None),
            getattr(self, "screenshot_hotkey_listener", None),
        ):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    logger.debug("停止热键监听失败", exc_info=True)

        # 卸载插件
        if hasattr(self, 'plugin_manager'):
            self.plugin_manager.unload_all()

        self.clipboard_monitor.stop()
        self.main_window._copy_executor.shutdown(wait=False)
        self.main_window._cloud_executor.shutdown(wait=False)
        self.sync_service.stop()
        if self.cloud_sync_service:
            self.cloud_sync_service.stop()
        if self.file_sync_service:
            try:
                self.file_sync_service.stop()
            except Exception:
                logger.debug("文件云同步停止失败", exc_info=True)
        self.tray_icon.hide()
        # 关闭云端 API 客户端（统一通过 reset_cloud_client 清理单例）
        try:
            from core.cloud_api import reset_cloud_client
            reset_cloud_client()
        except Exception:
            logger.debug("reset_cloud_client failed", exc_info=True)
        # 刷新延迟写入的配置
        flush_settings()
        # 关闭持久数据库连接。Why: close() 内部异常会被吞掉，若 SQLite WAL
        # checkpoint 失败下次启动会触发磁盘恢复 I/O；记一行 warning 方便排查。
        if hasattr(self.db_manager, 'close'):
            try:
                self.db_manager.close()
            except Exception as e:
                logger.warning(f"db_manager.close 失败（WAL 可能未 checkpoint）: {e}", exc_info=True)
        # Why: ThreadPoolExecutor 的 atexit 会 join 所有 worker；若有网络请求
        # 卡在 socket 上，进程就退不掉（托盘已 hide 但 Python 还活着）。
        # 给正常收尾 1.5s，超时直接 _exit 兜底。
        QTimer.singleShot(1500, lambda: os._exit(0))
        self.app.quit()

    def run(self) -> int:
        """运行应用"""
        logger.debug(f"[startup] 进入 app.exec() 事件循环 t=+{time.time()-_STARTUP_T0:.2f}s")
        if _SC_DEBUG or _SC_STARTUP_METRICS:
            logger.warning(f"[startup-metrics] {self.startup_metrics.format_summary()}")
        return self.app.exec()


def main():
    try:
        app = ClipboardApp()
        sys.exit(app.run())
    except Exception as e:
        logger.exception(f"应用启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
