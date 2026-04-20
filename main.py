import atexit
import sys
import os
import time
import logging
import platform
import threading

_STARTUP_T0 = time.time()

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
)
from i18n import t, set_language
from core.db_factory import create_database_manager
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.sync_service import SyncService
from core.plugin_manager import PluginManager
from ui.main_window import MainWindow

# 全局热键支持
try:
    from pynput import keyboard
    HOTKEY_AVAILABLE = True
except ImportError:
    HOTKEY_AVAILABLE = False

# 日志配置：默认 WARNING，设置 SC_DEBUG=1 可切到 DEBUG 并同时落盘到 logs/debug.log
_SC_DEBUG = os.environ.get("SC_DEBUG", "").strip() not in ("", "0", "false", "False")
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
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)  # 托盘模式
        # Why: update_settings 延迟 2s 合并落盘，Qt 正常退出路径（Cmd+Q、
        # SIGTERM 下的 aboutToQuit）若不兜底会丢失未 flush 的改动。
        self.app.aboutToQuit.connect(flush_settings)

        from PySide6.QtGui import QPixmapCache
        QPixmapCache.setCacheLimit(10240)

        # 初始化语言设置
        set_language(settings().language)

        # macOS 特定设置
        if IS_MACOS:
            # 设置应用名称（显示在菜单栏）
            self.app.setApplicationName(t("app_name"))
            # macOS 上隐藏 Dock 图标（作为菜单栏应用运行）
            self.app.setQuitOnLastWindowClosed(False)

        # 初始化组件
        self._init_components()

        # 创建系统托盘
        self._create_tray_icon()

        # 创建主窗口
        self._create_main_window()

        # 初始化全局热键
        self._init_hotkey()

        # Why: 若 keyring 不可用导致凭据只能以 base64/DPAPI 回退形式保存，
        # 安全等级低于系统钥匙串。主窗口构造过程中已触发过 token 读取，
        # 此时 _active_backend 已确定，弹一次托盘气泡提醒用户。
        self._maybe_warn_degraded_store()

        # 若 MySQL 连接失败已降级到 SQLite，提示用户同步未生效。
        self._maybe_warn_mysql_fallback()

    def _init_components(self):
        """初始化核心组件"""
        logger.debug(f"[startup] _init_components 开始 t=+{time.time()-_STARTUP_T0:.2f}s")
        _t = time.time()
        # 使用数据库工厂创建合适的数据库管理器
        self.db_manager = create_database_manager()
        self.repository = ClipboardRepository(self.db_manager)
        logger.debug(f"[startup] db_manager+repository 用时 {time.time()-_t:.3f}s")

    def _create_tray_icon(self):
        """创建系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self.app)
        # macOS 托盘需模板图(setIsMask)才能跟随深色菜单栏;Dock 仍用彩色 get_app_icon
        self.tray_icon.setIcon(create_fallback_icon() if IS_MACOS else get_app_icon())
        self.tray_icon.setToolTip(t("app_name"))

        # 创建托盘菜单
        menu = QMenu()

        show_action = QAction(t("show_window"), menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        menu.addSeparator()

        quit_action = QAction(t("quit"), menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _create_main_window(self):
        """创建主窗口"""
        logger.debug(f"[startup] _create_main_window 开始 t=+{time.time()-_STARTUP_T0:.2f}s")
        self.clipboard_monitor = ClipboardMonitor(self.repository)

        # 本地/MySQL 同步服务（始终启动）
        self.sync_service = SyncService(self.repository)

        # 云端同步服务（叠加层，有 token 时自动启动）
        self.cloud_api = None
        self.cloud_sync_service = None
        self.file_sync_service = None
        self.file_repository = None
        self.entitlement_service = None
        self._cloud_sync_error = None
        _t = time.time()
        _has_token = get_cloud_access_token()
        logger.debug(f"[startup] get_cloud_access_token 用时 {time.time()-_t:.3f}s, has_token={bool(_has_token)}")
        if _has_token:
            try:
                from core.cloud_sync_service import CloudSyncService
                from core.cloud_api import get_cloud_client

                self.cloud_api = get_cloud_client()
                self.cloud_sync_service = CloudSyncService(self.repository, self.cloud_api)

                # 监听剪贴板新增条目，自动加入云端上传队列
                self.clipboard_monitor.item_added.connect(self._on_new_item_for_cloud)

                # 付费闸 + 文件云同步（复用 app_meta 持久化，无额外依赖）
                try:
                    from core.entitlement_service import get_entitlement_service
                    from core.file_repository import CloudFileRepository
                    from core.file_sync_service import FileCloudSyncService

                    self.entitlement_service = get_entitlement_service(
                        cloud_api=self.cloud_api, repository=self.repository,
                    )
                    self.entitlement_service.refresh_async()

                    self.file_repository = CloudFileRepository(self.db_manager)
                    if settings().files_sync_enabled:
                        self.file_sync_service = FileCloudSyncService(
                            self.file_repository,
                            self.cloud_api,
                            self.entitlement_service,
                            self.repository,
                        )
                except Exception as ent_err:
                    logger.warning(f"文件云同步初始化失败: {ent_err}", exc_info=True)
                    self.file_repository = None
                    self.file_sync_service = None

                logger.info("云端同步已启用（叠加模式）")
            except Exception as e:
                logger.error(f"云端同步启动失败，已降级到本地存储: {e}", exc_info=True)
                self.cloud_api = None
                self.cloud_sync_service = None
                self._cloud_sync_error = str(e)
                # 通过托盘气泡提示用户：已登录但云端同步未生效
                try:
                    if hasattr(self, "tray_icon") and self.tray_icon is not None:
                        self.tray_icon.showMessage(
                            t("app_name"),
                            "云端同步启动失败，已降级到本地存储。请检查网络或查看日志。",
                            QSystemTrayIcon.MessageIcon.Warning,
                            8000,
                        )
                except Exception as notify_err:
                    logger.warning(f"托盘通知发送失败: {notify_err}")

        # 初始化插件管理器
        _t = time.time()
        self.plugin_manager = PluginManager()
        self.plugin_manager.load_plugins()
        logger.debug(f"[startup] PluginManager.load_plugins 用时 {time.time()-_t:.3f}s")

        _t = time.time()
        self.main_window = MainWindow(
            self.repository,
            self.clipboard_monitor,
            self.sync_service,
            plugin_manager=self.plugin_manager,
            cloud_api=self.cloud_api,
            cloud_sync_service=self.cloud_sync_service,
            file_sync_service=self.file_sync_service,
            file_repository=self.file_repository,
            entitlement_service=self.entitlement_service,
        )
        logger.debug(f"[startup] MainWindow(__init__) 用时 {time.time()-_t:.3f}s, 累计 t=+{time.time()-_STARTUP_T0:.2f}s")

        # 连接退出信号
        self.main_window.quit_requested.connect(self._quit)

        # 启动服务
        self.clipboard_monitor.start()
        self.sync_service.start()
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
            QTimer.singleShot(20000, self.cloud_sync_service.start)
            # Why: 正常 _quit 流程会调 stop() 落盘；atexit 是针对 SIGTERM/
            # 未捕获异常等非正常退出的兜底，确保游标不丢失。
            atexit.register(self._atexit_persist_cloud_cursor)

        if self.file_sync_service:
            def _start_file_sync():
                try:
                    self.file_sync_service.start()
                    atexit.register(self._atexit_persist_file_cursor)
                except Exception as e:
                    logger.warning(f"文件云同步启动失败: {e}", exc_info=True)
            QTimer.singleShot(20000, _start_file_sync)

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

    def _maybe_warn_mysql_fallback(self):
        """若 MySQL 初始化失败已降级到本地 SQLite，通过托盘气泡提醒一次用户。"""
        try:
            from core.db_factory import get_mysql_fallback_reason
            reason = get_mysql_fallback_reason()
            if not reason:
                return
            if not hasattr(self, "tray_icon") or self.tray_icon is None:
                return
            self.tray_icon.showMessage(
                t("app_name"),
                f"MySQL 连接失败，已降级到本地数据库（同步暂不生效）。请检查设置中的 MySQL 配置。\n原因：{reason}",
                QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )
        except Exception:
            logger.debug("MySQL 降级提示发送失败", exc_info=True)

    def _maybe_warn_degraded_store(self):
        """若凭据存储降级到非 keyring 后端，通过托盘气泡提醒一次用户。"""
        try:
            from utils import secure_store
            if not secure_store.is_degraded():
                return
            backend = secure_store.get_active_backend()
            if not hasattr(self, "tray_icon") or self.tray_icon is None:
                return
            self.tray_icon.showMessage(
                t("app_name"),
                f"当前密钥未加密存储（{backend}），建议安装 keyring 库以提升凭据安全性：pip install keyring",
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )
        except Exception:
            logger.debug("降级警告发送失败", exc_info=True)

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
        """初始化全局热键"""
        self.hotkey_listener = None

        if not HOTKEY_AVAILABLE:
            logger.warning("pynput 未安装，全局热键功能不可用")
            return

        hotkey = get_effective_hotkey()
        if not hotkey:
            return

        try:
            # 创建热键监听器
            self.hotkey_listener = keyboard.GlobalHotKeys({
                hotkey: self._on_hotkey_pressed
            })
            self.hotkey_listener.start()
            logger.info(f"全局热键已注册: {hotkey}")
            # macOS: pynput 无权限时常静默失败，延迟检查线程存活
            if IS_MACOS:
                QTimer.singleShot(3000, self._check_hotkey_listener_alive)
        except Exception as e:
            logger.error(f"注册全局热键失败: {e}")
            if IS_MACOS:
                self._prompt_input_monitoring_permission()

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
            QDesktopServices.openUrl(QUrl(
                "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
            ))

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

    def _quit(self):
        """退出应用"""
        # 停止热键监听
        if self.hotkey_listener:
            self.hotkey_listener.stop()

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
        # 关闭持久数据库连接
        if hasattr(self.db_manager, 'close'):
            self.db_manager.close()
        self.app.quit()

    def run(self) -> int:
        """运行应用"""
        logger.debug(f"[startup] 进入 app.exec() 事件循环 t=+{time.time()-_STARTUP_T0:.2f}s")
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
