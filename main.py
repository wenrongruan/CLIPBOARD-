import sys
import os
import logging
import platform
import threading

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QCursor
from PySide6.QtCore import Qt, QMetaObject, Q_ARG, QUrl
from PySide6.QtGui import QDesktopServices

IS_MACOS = platform.system() == "Darwin"

from config import Config
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

# 配置日志 (只显示警告和错误)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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

        # 初始化语言设置
        set_language(Config.get_language())

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

    def _init_components(self):
        """初始化核心组件"""
        # 使用数据库工厂创建合适的数据库管理器
        self.db_manager = create_database_manager()
        self.repository = ClipboardRepository(self.db_manager)

    def _create_tray_icon(self):
        """创建系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self.app)
        self.tray_icon.setIcon(get_app_icon())
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
        self.clipboard_monitor = ClipboardMonitor(self.repository)

        # 本地/MySQL 同步服务（始终启动）
        self.sync_service = SyncService(self.repository)

        # 云端同步服务（叠加层，有 token 时自动启动）
        self.cloud_api = None
        self.cloud_sync_service = None
        if Config.get_cloud_access_token():
            try:
                from core.cloud_sync_service import CloudSyncService
                from core.cloud_api import CloudAPIClient

                self.cloud_api = CloudAPIClient(Config.get_cloud_api_url())
                self.cloud_api.set_tokens(
                    Config.get_cloud_access_token(),
                    Config.get_cloud_refresh_token(),
                )
                self.cloud_sync_service = CloudSyncService(self.repository, self.cloud_api)

                # 监听剪贴板新增条目，自动加入云端上传队列
                self.clipboard_monitor.item_added.connect(self._on_new_item_for_cloud)

                logger.info("云端同步已启用（叠加模式）")
            except Exception as e:
                logger.warning(f"云端同步启动失败: {e}")

        # 初始化插件管理器
        self.plugin_manager = PluginManager()
        self.plugin_manager.load_plugins()

        self.main_window = MainWindow(
            self.repository,
            self.clipboard_monitor,
            self.sync_service,
            plugin_manager=self.plugin_manager,
            cloud_api=self.cloud_api,
        )

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
            self.cloud_sync_service.start()

    def _on_new_item_for_cloud(self, item):
        """剪贴板新条目回调 — 加入云端上传队列"""
        if self.cloud_sync_service:
            self.cloud_sync_service.enqueue_upload(item)

    def _advance_sync_after_cloud(self, items):
        """云端拉取写入本地后，推进 SyncService 游标"""
        if items:
            max_id = max(item.id for item in items if item.id)
            if max_id:
                self.sync_service.advance_sync_id(max_id)

    def _show_window(self):
        """显示主窗口"""
        self.main_window.show_window()

    def _on_tray_activated(self, reason):
        """托盘图标被点击"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if IS_MACOS:
                # macOS 上左键点击显示菜单
                self.tray_icon.contextMenu().popup(QCursor.pos())
            else:
                self._show_window()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            # 右键点击显示菜单（主要用于 macOS）
            self.tray_icon.contextMenu().popup(QCursor.pos())

    def _init_hotkey(self):
        """初始化全局热键"""
        self.hotkey_listener = None

        if not HOTKEY_AVAILABLE:
            logger.warning("pynput 未安装，全局热键功能不可用")
            return

        hotkey = Config.get_hotkey()
        if not hotkey:
            return

        try:
            # 创建热键监听器
            self.hotkey_listener = keyboard.GlobalHotKeys({
                hotkey: self._on_hotkey_pressed
            })
            self.hotkey_listener.start()
            logger.info(f"全局热键已注册: {hotkey}")
        except Exception as e:
            logger.error(f"注册全局热键失败: {e}")
            if IS_MACOS:
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
        self.sync_service.stop()
        if self.cloud_sync_service:
            self.cloud_sync_service.stop()
        self.tray_icon.hide()
        # 关闭云端 API 客户端
        if self.cloud_api is not None:
            self.cloud_api.close()
        # 关闭持久数据库连接
        if hasattr(self.db_manager, 'close'):
            self.db_manager.close()
        self.app.quit()

    def run(self) -> int:
        """运行应用"""
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
