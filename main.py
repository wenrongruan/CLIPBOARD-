import sys
import os
import logging
import platform
import threading

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QCursor
from PySide6.QtCore import Qt, QMetaObject, Q_ARG

IS_MACOS = platform.system() == "Darwin"

from config import Config
from core.db_factory import create_database_manager
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.sync_service import SyncService
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


def create_default_icon() -> QIcon:
    """创建一个简单的默认图标"""
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

        # macOS 特定设置
        if IS_MACOS:
            # 设置应用名称（显示在菜单栏）
            self.app.setApplicationName("共享剪贴板")
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
        self.tray_icon.setIcon(create_default_icon())
        self.tray_icon.setToolTip("共享剪贴板")

        # 创建托盘菜单
        menu = QMenu()

        # macOS 使用更符合习惯的菜单项名称
        show_text = "显示共享剪贴板" if IS_MACOS else "显示窗口"
        show_action = QAction(show_text, menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        menu.addSeparator()

        pause_action = QAction("暂停监控", menu)
        pause_action.setCheckable(True)
        pause_action.triggered.connect(self._toggle_monitoring)
        self.pause_action = pause_action
        menu.addAction(pause_action)

        menu.addSeparator()

        # macOS 使用 "退出 AppName" 的格式
        quit_text = "退出共享剪贴板" if IS_MACOS else "退出"
        quit_action = QAction(quit_text, menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _create_main_window(self):
        """创建主窗口"""
        self.clipboard_monitor = ClipboardMonitor(self.repository)
        self.sync_service = SyncService(self.repository)

        self.main_window = MainWindow(
            self.repository,
            self.clipboard_monitor,
            self.sync_service,
        )

        # 连接退出信号
        self.main_window.quit_requested.connect(self._quit)

        # 启动服务
        self.clipboard_monitor.start()
        self.sync_service.start()

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

    def _toggle_monitoring(self, checked: bool):
        """切换监控状态"""
        if checked:
            self.clipboard_monitor.stop()
            self.sync_service.stop()
            self.pause_action.setText("恢复监控")
        else:
            self.clipboard_monitor.start()
            self.sync_service.start()
            self.pause_action.setText("暂停监控")

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

        self.clipboard_monitor.stop()
        self.sync_service.stop()
        self.tray_icon.hide()
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
