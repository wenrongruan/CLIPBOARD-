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
    QGroupBox,
    QSpinBox,
    QTabWidget,
)

from core.models import ClipboardItem
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.sync_service import SyncService
from config import Config
from i18n import t, set_language, get_language, get_languages, SUPPORTED_LANGUAGES
from .edge_window import EdgeHiddenWindow
from .clipboard_item import ClipboardItemWidget
from .styles import MAIN_STYLE


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("settings"))
        self.setFixedSize(550, 480)
        self.setStyleSheet(MAIN_STYLE)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 使用选项卡组织设置
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # ========== 通用设置选项卡 ==========
        general_tab = QWidget()
        general_layout = QFormLayout(general_tab)
        general_layout.setSpacing(12)

        # 语言设置
        self.language_combo = QComboBox()
        languages = get_languages()
        self._language_codes = list(languages.keys())
        self.language_combo.addItems(list(languages.values()))
        current_lang = Config.get_language()
        if current_lang in self._language_codes:
            self.language_combo.setCurrentIndex(self._language_codes.index(current_lang))
        general_layout.addRow(t("language"), self.language_combo)

        # 停靠边缘
        self.dock_combo = QComboBox()
        self.dock_combo.addItems([t("dock_right"), t("dock_left"), t("dock_top"), t("dock_bottom")])
        edge_map = {"right": 0, "left": 1, "top": 2, "bottom": 3}
        current_edge = Config.get_dock_edge()
        self.dock_combo.setCurrentIndex(edge_map.get(current_edge, 0))
        general_layout.addRow(t("dock_position"), self.dock_combo)

        # 热键设置
        hotkey_layout = QHBoxLayout()
        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setText(Config.get_hotkey())
        self.hotkey_edit.setPlaceholderText(t("hotkey_placeholder"))
        hotkey_layout.addWidget(self.hotkey_edit)

        hotkey_help = QLabel("?")
        hotkey_help.setToolTip(t("hotkey_help"))
        hotkey_help.setStyleSheet("color: #888; font-weight: bold;")
        hotkey_layout.addWidget(hotkey_help)
        general_layout.addRow(t("global_hotkey"), hotkey_layout)

        tab_widget.addTab(general_tab, t("general"))

        # ========== 数据库设置选项卡 ==========
        db_tab = QWidget()
        db_layout = QVBoxLayout(db_tab)
        db_layout.setSpacing(12)

        # 数据库类型选择
        db_type_layout = QFormLayout()
        self.db_type_combo = QComboBox()
        self.db_type_combo.addItems([t("db_sqlite"), t("db_mysql")])
        self.db_type_combo.setCurrentIndex(0 if Config.get_db_type() == "sqlite" else 1)
        self.db_type_combo.currentIndexChanged.connect(self._on_db_type_changed)
        db_type_layout.addRow(t("db_type"), self.db_type_combo)
        db_layout.addLayout(db_type_layout)

        # SQLite 配置组
        self.sqlite_group = QGroupBox(t("sqlite_config"))
        sqlite_layout = QFormLayout(self.sqlite_group)

        path_layout = QHBoxLayout()
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setText(Config.get_database_path())
        self.db_path_edit.setPlaceholderText(t("path_placeholder"))
        path_layout.addWidget(self.db_path_edit)

        browse_btn = QPushButton(t("browse"))
        browse_btn.clicked.connect(self._browse_db_path)
        path_layout.addWidget(browse_btn)
        sqlite_layout.addRow(t("db_path"), path_layout)

        db_layout.addWidget(self.sqlite_group)

        # MySQL 配置组
        self.mysql_group = QGroupBox(t("mysql_config"))
        mysql_layout = QFormLayout(self.mysql_group)

        mysql_config = Config.get_mysql_config()

        self.mysql_host_edit = QLineEdit()
        self.mysql_host_edit.setText(mysql_config["host"])
        self.mysql_host_edit.setPlaceholderText("localhost")
        mysql_layout.addRow(t("host"), self.mysql_host_edit)

        self.mysql_port_spin = QSpinBox()
        self.mysql_port_spin.setRange(1, 65535)
        self.mysql_port_spin.setValue(mysql_config["port"])
        mysql_layout.addRow(t("port"), self.mysql_port_spin)

        self.mysql_user_edit = QLineEdit()
        self.mysql_user_edit.setText(mysql_config["user"])
        self.mysql_user_edit.setPlaceholderText("root")
        mysql_layout.addRow(t("username"), self.mysql_user_edit)

        self.mysql_password_edit = QLineEdit()
        self.mysql_password_edit.setText(mysql_config["password"])
        self.mysql_password_edit.setEchoMode(QLineEdit.Password)
        self.mysql_password_edit.setPlaceholderText(t("password"))
        mysql_layout.addRow(t("password"), self.mysql_password_edit)

        self.mysql_database_edit = QLineEdit()
        self.mysql_database_edit.setText(mysql_config["database"])
        self.mysql_database_edit.setPlaceholderText("clipboard")
        mysql_layout.addRow(t("db_name"), self.mysql_database_edit)

        # 测试连接按钮
        test_btn_layout = QHBoxLayout()
        self.test_connection_btn = QPushButton(t("test_connection"))
        self.test_connection_btn.clicked.connect(self._test_mysql_connection)
        test_btn_layout.addWidget(self.test_connection_btn)
        test_btn_layout.addStretch()
        mysql_layout.addRow("", test_btn_layout)

        db_layout.addWidget(self.mysql_group)
        db_layout.addStretch()

        tab_widget.addTab(db_tab, t("database"))

        # 根据当前数据库类型显示/隐藏配置组
        self._on_db_type_changed(self.db_type_combo.currentIndex())

        # ========== 按钮 ==========
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_db_type_changed(self, index: int):
        """数据库类型切换时显示/隐藏对应配置"""
        is_sqlite = index == 0
        self.sqlite_group.setVisible(is_sqlite)
        self.mysql_group.setVisible(not is_sqlite)

    def _browse_db_path(self):
        import platform
        import os

        current_path = self.db_path_edit.text()
        if current_path and os.path.exists(os.path.dirname(current_path)):
            start_dir = current_path
        elif platform.system() == "Darwin" and os.path.exists("/Volumes"):
            start_dir = "/Volumes"
        else:
            start_dir = Config.get_database_path()

        path, _ = QFileDialog.getSaveFileName(
            self,
            t("select_db_file"),
            start_dir,
            "SQLite (*.db)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if path:
            self.db_path_edit.setText(path)

    def _test_mysql_connection(self):
        """测试 MySQL 连接"""
        try:
            from core.mysql_database import MySQLDatabaseManager

            host = self.mysql_host_edit.text() or "localhost"
            port = self.mysql_port_spin.value()
            user = self.mysql_user_edit.text()
            password = self.mysql_password_edit.text()
            database = self.mysql_database_edit.text() or "clipboard"

            success, message = MySQLDatabaseManager.test_connection(
                host, port, user, password, database
            )

            if success:
                QMessageBox.information(self, t("connection_success"), message)
            else:
                QMessageBox.warning(self, t("connection_failed"), message)
        except ImportError:
            QMessageBox.warning(
                self, t("missing_dependency"),
                t("pymysql_required")
            )
        except Exception as e:
            QMessageBox.critical(self, t("error"), f"{str(e)}")

    def _on_accept(self):
        """确认保存设置前进行验证"""
        # 如果选择了 MySQL，验证连接
        if self.db_type_combo.currentIndex() == 1:
            try:
                from core.mysql_database import MySQLDatabaseManager

                host = self.mysql_host_edit.text() or "localhost"
                port = self.mysql_port_spin.value()
                user = self.mysql_user_edit.text()
                password = self.mysql_password_edit.text()
                database = self.mysql_database_edit.text() or "clipboard"

                success, message = MySQLDatabaseManager.test_connection(
                    host, port, user, password, database
                )

                if not success:
                    reply = QMessageBox.question(
                        self,
                        t("connection_failed"),
                        t("save_anyway", message=message),
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if reply != QMessageBox.Yes:
                        return
            except ImportError:
                QMessageBox.warning(
                    self, t("missing_dependency"),
                    t("pymysql_required")
                )
                return

        self.accept()

    def get_settings(self) -> dict:
        edge_map = {0: "right", 1: "left", 2: "top", 3: "bottom"}
        db_type = "sqlite" if self.db_type_combo.currentIndex() == 0 else "mysql"
        language = self._language_codes[self.language_combo.currentIndex()]

        return {
            "language": language,
            "dock_edge": edge_map[self.dock_combo.currentIndex()],
            "hotkey": self.hotkey_edit.text(),
            "db_type": db_type,
            "database_path": self.db_path_edit.text(),
            "mysql_host": self.mysql_host_edit.text() or "localhost",
            "mysql_port": self.mysql_port_spin.value(),
            "mysql_user": self.mysql_user_edit.text(),
            "mysql_password": self.mysql_password_edit.text(),
            "mysql_database": self.mysql_database_edit.text() or "clipboard",
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
        self.search_input.setPlaceholderText(t("search_placeholder"))
        self.search_input.textChanged.connect(self._on_search_changed)
        header_layout.addWidget(self.search_input, 1)

        self.pin_btn = QPushButton("📌")
        self.pin_btn.setToolTip(t("pin_window"))
        self.pin_btn.setFixedSize(28, 28)
        self.pin_btn.clicked.connect(self._toggle_pin)
        header_layout.addWidget(self.pin_btn)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setToolTip(t("settings"))
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.clicked.connect(self._show_settings)
        header_layout.addWidget(self.settings_btn)

        self.minimize_btn = QPushButton("—")
        self.minimize_btn.setToolTip(t("minimize"))
        self.minimize_btn.setFixedSize(28, 28)
        self.minimize_btn.clicked.connect(self._minimize_window)
        header_layout.addWidget(self.minimize_btn)

        self.quit_btn = QPushButton("✕")
        self.quit_btn.setToolTip(t("quit_app"))
        self.quit_btn.setFixedSize(28, 28)
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

        self.prev_btn = QPushButton(t("prev_page"))
        self.prev_btn.clicked.connect(self._prev_page)
        pagination_layout.addWidget(self.prev_btn)

        self.page_label = QLabel("1 / 1")
        self.page_label.setObjectName("pageLabel")
        self.page_label.setAlignment(Qt.AlignCenter)
        pagination_layout.addWidget(self.page_label, 1)

        self.next_btn = QPushButton(t("next_page"))
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
            t("confirm_delete"),
            t("delete_confirm_msg"),
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
        self.pin_btn.setToolTip(t("unpin_window") if is_pinned else t("pin_window"))

    def _minimize_window(self):
        """最小化窗口（完全隐藏）"""
        self.hide_window()

    def _show_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            settings = dialog.get_settings()
            need_restart = False

            # 语言变更
            new_language = settings["language"]
            if new_language != Config.get_language():
                Config.set_language(new_language)
                set_language(new_language)
                need_restart = True

            # 应用停靠边缘
            new_edge = settings["dock_edge"]
            if new_edge != Config.get_dock_edge():
                self.set_dock_edge(new_edge)

            # 热键变更
            new_hotkey = settings["hotkey"]
            if new_hotkey != Config.get_hotkey():
                Config.set_hotkey(new_hotkey)
                need_restart = True

            # 数据库类型变更
            new_db_type = settings["db_type"]
            if new_db_type != Config.get_db_type():
                Config.set_db_type(new_db_type)
                need_restart = True

            # SQLite 路径变更
            if new_db_type == "sqlite":
                new_db_path = settings["database_path"]
                if new_db_path != Config.get_database_path():
                    Config.set_database_path(new_db_path)
                    need_restart = True

            # MySQL 配置变更
            if new_db_type == "mysql":
                mysql_config = Config.get_mysql_config()
                if (settings["mysql_host"] != mysql_config["host"] or
                    settings["mysql_port"] != mysql_config["port"] or
                    settings["mysql_user"] != mysql_config["user"] or
                    settings["mysql_password"] != mysql_config["password"] or
                    settings["mysql_database"] != mysql_config["database"]):
                    Config.set_mysql_config(
                        settings["mysql_host"],
                        settings["mysql_port"],
                        settings["mysql_user"],
                        settings["mysql_password"],
                        settings["mysql_database"],
                    )
                    need_restart = True

            if need_restart:
                QMessageBox.information(
                    self,
                    t("need_restart"),
                    t("restart_msg"),
                )

    def _request_quit(self):
        """请求退出应用"""
        self.quit_requested.emit()
