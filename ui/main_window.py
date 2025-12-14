from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QMenu,
    QDialog,
    QFormLayout,
    QComboBox,
    QDialogButtonBox,
    QMessageBox,
    QFileDialog,
    QSizePolicy,
)

from core.models import ClipboardItem
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.sync_service import SyncService
from config import Config
from .edge_window import EdgeHiddenWindow
from .clipboard_item import ClipboardItemWidget
from .styles import MAIN_STYLE


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedSize(500, 200)
        self.setStyleSheet(MAIN_STYLE)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 停靠边缘
        self.dock_combo = QComboBox()
        self.dock_combo.addItems(["右侧", "左侧", "顶部", "底部"])
        edge_map = {"right": 0, "left": 1, "top": 2, "bottom": 3}
        current_edge = Config.get_dock_edge()
        self.dock_combo.setCurrentIndex(edge_map.get(current_edge, 0))
        layout.addRow("停靠位置:", self.dock_combo)

        # 数据库路径（可手动输入或浏览选择）
        db_layout = QHBoxLayout()
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setText(Config.get_database_path())
        self.db_path_edit.setPlaceholderText("输入路径或点击浏览，支持网络路径如 /Volumes/...")
        db_layout.addWidget(self.db_path_edit)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_db_path)
        db_layout.addWidget(browse_btn)

        layout.addRow("数据库路径:", db_layout)

        # 按钮
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

    def _browse_db_path(self):
        import platform
        import os

        # 确定起始目录：优先使用当前路径的目录，否则用默认位置
        current_path = self.db_path_edit.text()
        if current_path and os.path.exists(os.path.dirname(current_path)):
            start_dir = current_path
        elif platform.system() == "Darwin" and os.path.exists("/Volumes"):
            # macOS: 从 /Volumes 开始方便访问网络驱动器
            start_dir = "/Volumes"
        else:
            start_dir = Config.get_database_path()

        # 使用非原生对话框以支持网络文件夹
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择数据库文件位置（可导航到 /Volumes 访问网络驱动器）",
            start_dir,
            "SQLite数据库 (*.db)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if path:
            self.db_path_edit.setText(path)

    def get_settings(self) -> dict:
        edge_map = {0: "right", 1: "left", 2: "top", 3: "bottom"}
        return {
            "dock_edge": edge_map[self.dock_combo.currentIndex()],
            "database_path": self.db_path_edit.text(),
        }


class MainWindow(EdgeHiddenWindow):
    quit_requested = Signal()  # 退出信号

    def __init__(
        self,
        repository: ClipboardRepository,
        clipboard_monitor: ClipboardMonitor,
        sync_service: SyncService,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.clipboard_monitor = clipboard_monitor
        self.sync_service = sync_service

        self._current_page = 0
        self._total_pages = 1
        self._page_size = Config.PAGE_SIZE
        self._search_query = ""
        self._items: List[ClipboardItem] = []

        self.setStyleSheet(MAIN_STYLE)
        self._setup_ui()
        self._connect_signals()
        self._load_items()

    def _setup_ui(self):
        # 直接在窗口上设置布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 顶部：搜索和设置
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索剪贴板...")
        self.search_input.textChanged.connect(self._on_search_changed)
        header_layout.addWidget(self.search_input, 1)

        self.pin_btn = QPushButton("📌")
        self.pin_btn.setToolTip("固定窗口")
        self.pin_btn.setFixedWidth(36)
        self.pin_btn.clicked.connect(self._toggle_pin)
        header_layout.addWidget(self.pin_btn)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setFixedWidth(36)
        self.settings_btn.clicked.connect(self._show_settings)
        header_layout.addWidget(self.settings_btn)

        self.quit_btn = QPushButton("✕")
        self.quit_btn.setToolTip("退出应用")
        self.quit_btn.setFixedWidth(36)
        self.quit_btn.clicked.connect(self._request_quit)
        header_layout.addWidget(self.quit_btn)

        layout.addLayout(header_layout)

        # 中间：列表
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(2)
        layout.addWidget(self.list_widget, 1)

        # 底部：分页
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(8)

        self.prev_btn = QPushButton("◀ 上一页")
        self.prev_btn.clicked.connect(self._prev_page)
        pagination_layout.addWidget(self.prev_btn)

        self.page_label = QLabel("1 / 1")
        self.page_label.setObjectName("pageLabel")
        self.page_label.setAlignment(Qt.AlignCenter)
        pagination_layout.addWidget(self.page_label, 1)

        self.next_btn = QPushButton("下一页 ▶")
        self.next_btn.clicked.connect(self._next_page)
        pagination_layout.addWidget(self.next_btn)

        layout.addLayout(pagination_layout)

        # 搜索防抖定时器
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)

    def _connect_signals(self):
        # 剪贴板监控信号
        self.clipboard_monitor.item_added.connect(self._on_item_added)

        # 同步服务信号
        self.sync_service.new_items_available.connect(self._on_new_items)

    def _load_items(self):
        if self._search_query:
            items, total = self.repository.search(
                self._search_query, self._current_page, self._page_size
            )
        else:
            items, total = self.repository.get_items(
                self._current_page, self._page_size
            )

        self._items = items
        self._total_pages = max(1, (total + self._page_size - 1) // self._page_size)
        self._update_list()
        self._update_pagination()

    def _update_list(self):
        self.list_widget.clear()

        for item in self._items:
            widget = ClipboardItemWidget(item)
            widget.clicked.connect(self._on_item_clicked)
            widget.delete_clicked.connect(self._on_item_delete)
            widget.star_clicked.connect(self._on_item_star)

            list_item = QListWidgetItem(self.list_widget)
            list_item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, widget)

    def _update_pagination(self):
        self.page_label.setText(f"{self._current_page + 1} / {self._total_pages}")
        self.prev_btn.setEnabled(self._current_page > 0)
        self.next_btn.setEnabled(self._current_page < self._total_pages - 1)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._load_items()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._load_items()

    def _on_search_changed(self, text: str):
        self._search_timer.stop()
        self._search_timer.start(300)  # 300ms 防抖

    def _do_search(self):
        self._search_query = self.search_input.text().strip()
        self._current_page = 0
        self._load_items()

    def _on_item_clicked(self, item: ClipboardItem):
        # 需要从数据库获取完整数据（包括图片）
        if item.is_image:
            full_item = self.repository.get_item_by_id(item.id)
            if full_item:
                item = full_item

        self.clipboard_monitor.copy_to_clipboard(item)

    def _on_item_delete(self, item: ClipboardItem):
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这条记录吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.repository.delete_item(item.id)
            self._load_items()

    def _on_item_star(self, item: ClipboardItem):
        self.repository.toggle_star(item.id)
        self._load_items()

    def _on_item_added(self, item: ClipboardItem):
        # 如果在第一页且没有搜索，刷新列表
        if self._current_page == 0 and not self._search_query:
            self._load_items()

    def _on_new_items(self, items: List[ClipboardItem]):
        # 来自其他设备的新记录
        if self._current_page == 0 and not self._search_query:
            self._load_items()

    def _toggle_pin(self):
        is_pinned = self.toggle_pin()
        self.pin_btn.setText("📍" if is_pinned else "📌")
        self.pin_btn.setToolTip("取消固定" if is_pinned else "固定窗口")

    def _show_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            settings = dialog.get_settings()

            # 应用停靠边缘
            new_edge = settings["dock_edge"]
            if new_edge != Config.get_dock_edge():
                self.set_dock_edge(new_edge)

            # 数据库路径变更需要重启
            new_db_path = settings["database_path"]
            if new_db_path != Config.get_database_path():
                Config.set_database_path(new_db_path)
                QMessageBox.information(
                    self,
                    "需要重启",
                    "数据库路径已更改，请重启应用程序以生效。",
                )

    def _request_quit(self):
        """请求退出应用"""
        self.quit_requested.emit()
