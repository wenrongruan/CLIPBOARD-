import sys
import os
import logging
import platform

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

IS_MACOS = platform.system() == "Darwin"

from config import Config
from core.database import DatabaseManager
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.sync_service import SyncService
from ui.main_window import MainWindow

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

    def _init_components(self):
        """初始化核心组件"""
        db_path = Config.get_database_path()
        self.db_manager = DatabaseManager(db_path)
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

        # 启动服务
        self.clipboard_monitor.start()
        self.sync_service.start()

    def _show_window(self):
        """显示主窗口"""
        self.main_window.show_window()

    def _on_tray_activated(self, reason):
        """托盘图标被点击"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

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

    def _quit(self):
        """退出应用"""
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
