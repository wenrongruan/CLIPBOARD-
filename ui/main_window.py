from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QTimer, QSize
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
    QCheckBox,
)
from PySide6.QtWidgets import QButtonGroup, QProgressDialog, QInputDialog

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
        self.setFixedSize(580, 560)
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

        # Profile 选择
        profile_layout = QHBoxLayout()
        profile_layout.setSpacing(8)
        profile_label = QLabel(t("db_profile"))
        profile_layout.addWidget(profile_label)

        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        profiles = Config.get_db_profiles()
        active = Config.get_active_profile()
        for name in profiles:
            self.profile_combo.addItem(name)
        if active in profiles:
            self.profile_combo.setCurrentText(active)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        profile_layout.addWidget(self.profile_combo)

        add_profile_btn = QPushButton(t("add_profile"))
        add_profile_btn.clicked.connect(self._add_profile)
        profile_layout.addWidget(add_profile_btn)

        del_profile_btn = QPushButton(t("delete_profile"))
        del_profile_btn.clicked.connect(self._delete_profile)
        profile_layout.addWidget(del_profile_btn)

        db_layout.addLayout(profile_layout)

        # 数据库类型选择
        db_type_label = QLabel(t("db_type"))
        db_type_label.setObjectName("sectionTitle")
        db_layout.addWidget(db_type_label)

        db_card_layout = QHBoxLayout()
        db_card_layout.setSpacing(12)

        self.sqlite_card = QPushButton(t("db_sqlite"))
        self.sqlite_card.setObjectName("dbTypeCard")
        self.sqlite_card.setCheckable(True)
        self.sqlite_card.setMinimumHeight(48)
        db_card_layout.addWidget(self.sqlite_card)

        self.mysql_card = QPushButton(t("db_mysql"))
        self.mysql_card.setObjectName("dbTypeCard")
        self.mysql_card.setCheckable(True)
        self.mysql_card.setMinimumHeight(48)
        db_card_layout.addWidget(self.mysql_card)

        self.db_type_group = QButtonGroup(self)
        self.db_type_group.setExclusive(True)
        self.db_type_group.addButton(self.sqlite_card, 0)
        self.db_type_group.addButton(self.mysql_card, 1)

        current_db_index = 0 if Config.get_db_type() == "sqlite" else 1
        self.db_type_group.button(current_db_index).setChecked(True)
        self.db_type_group.idClicked.connect(self._on_db_type_changed)

        db_layout.addLayout(db_card_layout)

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
        self._on_db_type_changed(self.db_type_group.checkedId())

        # ========== 过滤与存储选项卡 ==========
        filter_tab = QWidget()
        filter_layout = QVBoxLayout(filter_tab)
        filter_layout.setSpacing(12)

        # 内容过滤组
        filter_group = QGroupBox(t("content_filter"))
        filter_group_layout = QFormLayout(filter_group)
        filter_group_layout.setSpacing(8)

        self.save_text_check = QCheckBox(t("save_text"))
        self.save_text_check.setChecked(Config.get_save_text())
        filter_group_layout.addRow(self.save_text_check)

        self.save_images_check = QCheckBox(t("save_images"))
        self.save_images_check.setChecked(Config.get_save_images())
        filter_group_layout.addRow(self.save_images_check)

        self.max_text_length_spin = QSpinBox()
        self.max_text_length_spin.setRange(0, 10000000)
        self.max_text_length_spin.setValue(Config.get_max_text_length())
        self.max_text_length_spin.setSpecialValueText(t("unlimited"))
        self.max_text_length_spin.setSuffix(f" {t('characters')}")
        filter_group_layout.addRow(t("max_text_length"), self.max_text_length_spin)

        self.max_image_size_spin = QSpinBox()
        self.max_image_size_spin.setRange(0, 102400)
        self.max_image_size_spin.setValue(Config.get_max_image_size_kb())
        self.max_image_size_spin.setSpecialValueText(t("unlimited"))
        self.max_image_size_spin.setSuffix(" KB")
        filter_group_layout.addRow(t("max_image_size"), self.max_image_size_spin)

        filter_layout.addWidget(filter_group)

        # 存储管理组
        storage_group = QGroupBox(t("storage_management"))
        storage_group_layout = QFormLayout(storage_group)
        storage_group_layout.setSpacing(8)

        self.max_items_spin = QSpinBox()
        self.max_items_spin.setRange(100, 100000)
        self.max_items_spin.setValue(Config.get_max_items())
        storage_group_layout.addRow(t("max_items"), self.max_items_spin)

        self.retention_days_spin = QSpinBox()
        self.retention_days_spin.setRange(0, 3650)
        self.retention_days_spin.setValue(Config.get_retention_days())
        self.retention_days_spin.setSpecialValueText(t("never_cleanup"))
        self.retention_days_spin.setSuffix(f" {t('days')}")
        storage_group_layout.addRow(t("retention_days"), self.retention_days_spin)

        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(100, 5000)
        self.poll_interval_spin.setSingleStep(100)
        self.poll_interval_spin.setValue(Config.get_poll_interval_ms())
        self.poll_interval_spin.setSuffix(" ms")
        storage_group_layout.addRow(t("poll_interval"), self.poll_interval_spin)

        filter_layout.addWidget(storage_group)
        filter_layout.addStretch()

        tab_widget.addTab(filter_tab, t("filter_storage"))

        # ========== 按钮 ==========
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok_btn = button_box.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setObjectName("okButton")
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

    def _on_profile_changed(self, name: str):
        """切换 profile 时自动填充对应配置"""
        profiles = Config.get_db_profiles()
        profile = profiles.get(name)
        if not profile:
            return
        # 填充 UI
        db_type = profile.get("db_type", "sqlite")
        self.db_type_group.button(0 if db_type == "sqlite" else 1).setChecked(True)
        self._on_db_type_changed(0 if db_type == "sqlite" else 1)
        self.db_path_edit.setText(profile.get("database_path", ""))
        self.mysql_host_edit.setText(profile.get("mysql_host", "localhost"))
        self.mysql_port_spin.setValue(profile.get("mysql_port", 3306))
        self.mysql_user_edit.setText(profile.get("mysql_user", ""))
        self.mysql_password_edit.setText(profile.get("mysql_password", ""))
        self.mysql_database_edit.setText(profile.get("mysql_database", "clipboard"))

    def _add_profile(self):
        """添加新 profile"""
        name, ok = QInputDialog.getText(self, t("profile_name"), t("enter_profile_name"))
        if not ok or not name.strip():
            return
        name = name.strip()
        profiles = Config.get_db_profiles()
        if name in profiles:
            QMessageBox.warning(self, t("warning"), t("profile_exists"))
            return
        # 用当前 UI 值作为新 profile 的初始配置
        profiles[name] = self._current_db_settings()
        Config.set_db_profiles(profiles)
        self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(name)

    def _delete_profile(self):
        """删除当前选中的 profile"""
        name = self.profile_combo.currentText()
        profiles = Config.get_db_profiles()
        if len(profiles) <= 1:
            return
        if name == Config.get_active_profile():
            QMessageBox.warning(self, t("warning"), t("cannot_delete_active"))
            return
        reply = QMessageBox.question(
            self, t("confirm_delete"), t("confirm_delete_profile", name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            del profiles[name]
            Config.set_db_profiles(profiles)
            self.profile_combo.removeItem(self.profile_combo.currentIndex())

    def _current_db_settings(self) -> dict:
        """从 UI 中读取当前数据库配置"""
        db_type = "sqlite" if self.db_type_group.checkedId() == 0 else "mysql"
        return {
            "db_type": db_type,
            "database_path": self.db_path_edit.text(),
            "mysql_host": self.mysql_host_edit.text() or "localhost",
            "mysql_port": self.mysql_port_spin.value(),
            "mysql_user": self.mysql_user_edit.text(),
            "mysql_password": self.mysql_password_edit.text(),
            "mysql_database": self.mysql_database_edit.text() or "clipboard",
        }

    def _on_accept(self):
        """确认保存设置前进行验证"""
        # 如果选择了 MySQL，验证连接
        if self.db_type_group.checkedId() == 1:
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
        db_settings = self._current_db_settings()
        language = self._language_codes[self.language_combo.currentIndex()]

        # 保存当前 profile
        profile_name = self.profile_combo.currentText()
        profiles = Config.get_db_profiles()
        profiles[profile_name] = db_settings
        Config.set_db_profiles(profiles)

        result = {
            "language": language,
            "dock_edge": edge_map[self.dock_combo.currentIndex()],
            "hotkey": self.hotkey_edit.text(),
            "active_profile": profile_name,
            "save_text": self.save_text_check.isChecked(),
            "save_images": self.save_images_check.isChecked(),
            "max_text_length": self.max_text_length_spin.value(),
            "max_image_size_kb": self.max_image_size_spin.value(),
            "max_items": self.max_items_spin.value(),
            "retention_days": self.retention_days_spin.value(),
            "poll_interval_ms": self.poll_interval_spin.value(),
        }
        result.update(db_settings)
        return result


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
        self._starred_only = False
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

        self.star_filter_btn = QPushButton("☆")
        self.star_filter_btn.setToolTip(t("show_starred_only"))
        self.star_filter_btn.setFixedSize(28, 28)
        self.star_filter_btn.clicked.connect(self._toggle_starred_filter)
        header_layout.addWidget(self.star_filter_btn)

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
        self.list_widget.setSpacing(1)
        layout.addWidget(self.list_widget, 1)

        # 复制反馈标签
        self.copy_feedback_label = QLabel()
        self.copy_feedback_label.setAlignment(Qt.AlignCenter)
        self.copy_feedback_label.hide()
        layout.addWidget(self.copy_feedback_label)

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

        # 复制反馈定时器（复用同一个避免快速复制时提前隐藏）
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self.copy_feedback_label.hide)

    def _connect_signals(self):
        # 剪贴板监控信号
        self.clipboard_monitor.item_added.connect(self._on_item_added)

        # 同步服务信号
        self.sync_service.new_items_available.connect(self._on_new_items)

    def _toggle_starred_filter(self):
        self._starred_only = not self._starred_only
        self.star_filter_btn.setText("★" if self._starred_only else "☆")
        self._current_page = 0
        self._load_items()

    def _load_items(self):
        if self._search_query:
            items, total = self.repository.search(
                self._search_query, self._current_page, self._page_size,
                starred_only=self._starred_only
            )
        else:
            items, total = self.repository.get_items(
                self._current_page, self._page_size,
                starred_only=self._starred_only
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
            widget.save_clicked.connect(self._on_item_save)

            list_item = QListWidgetItem(self.list_widget)
            hint = widget.sizeHint()
            min_h = 92 if item.is_image else 76
            list_item.setSizeHint(QSize(hint.width(), max(hint.height(), min_h)))
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

        success = self.clipboard_monitor.copy_to_clipboard(item)
        if success:
            self.copy_feedback_label.setText(t("copied_to_clipboard"))
            self.copy_feedback_label.setObjectName("copyFeedbackSuccess")
        else:
            self.copy_feedback_label.setText(t("copy_failed"))
            self.copy_feedback_label.setObjectName("copyFeedbackError")
        self.copy_feedback_label.style().polish(self.copy_feedback_label)
        self.copy_feedback_label.show()
        self._feedback_timer.start(2000)

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

    def _on_item_save(self, item: ClipboardItem):
        """保存图片到本地文件"""
        full_item = self.repository.get_item_by_id(item.id)
        if not full_item or not full_item.image_data:
            QMessageBox.warning(self, t("error"), t("image_load_failed"))
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            t("save_image"),
            "",
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
        )
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(full_item.image_data)
            except Exception as e:
                QMessageBox.critical(self, t("error"), t("save_failed", error=str(e)))

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

            # 过滤与存储设置（批量更新，只写一次磁盘）
            new_poll_interval = settings["poll_interval_ms"]
            poll_changed = new_poll_interval != Config.get_poll_interval_ms()

            current_settings = Config.load_settings()
            for key in ("save_text", "save_images", "max_text_length",
                        "max_image_size_kb", "max_items", "retention_days",
                        "poll_interval_ms"):
                current_settings[key] = settings[key]
            Config.save_settings(current_settings)

            if poll_changed:
                self.clipboard_monitor.update_poll_interval(new_poll_interval)

            # Profile / 数据库变更检测
            new_profile = settings.get("active_profile", "")
            new_db_type = settings["db_type"]
            db_changed = False

            if new_profile != Config.get_active_profile():
                db_changed = True
            elif new_db_type != Config.get_db_type():
                db_changed = True
            elif new_db_type == "sqlite" and settings["database_path"] != Config.get_database_path():
                db_changed = True
            elif new_db_type == "mysql":
                mysql_config = Config.get_mysql_config()
                if (settings["mysql_host"] != mysql_config["host"] or
                    settings["mysql_port"] != mysql_config["port"] or
                    settings["mysql_user"] != mysql_config["user"] or
                    settings["mysql_password"] != mysql_config["password"] or
                    settings["mysql_database"] != mysql_config["database"]):
                    db_changed = True

            if db_changed:
                # 询问是否迁移数据
                migrate = QMessageBox.question(
                    self,
                    t("migrate_data"),
                    t("migrate_data_confirm"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                ) == QMessageBox.Yes

                # 应用 profile 并保存配置
                Config.apply_profile(new_profile)

                if migrate:
                    self._do_migration()

                need_restart = True

            if need_restart:
                QMessageBox.information(
                    self,
                    t("need_restart"),
                    t("restart_msg"),
                )

    def _do_migration(self):
        """在工作线程中执行数据库迁移，避免阻塞 UI"""
        from core.migration import DatabaseMigrator
        from core.database import DatabaseManager
        from core.repository import ClipboardRepository
        from PySide6.QtCore import QThread, Signal as QSignal

        # 创建目标库连接
        try:
            db_type = Config.get_db_type()
            if db_type == "sqlite":
                target_db = DatabaseManager(Config.get_database_path())
                target_repo = ClipboardRepository(target_db)
            else:
                from core.mysql_database import MySQLDatabaseManager
                mysql_config = Config.get_mysql_config()
                target_db = MySQLDatabaseManager(
                    mysql_config["host"], mysql_config["port"],
                    mysql_config["user"], mysql_config["password"],
                    mysql_config["database"],
                )
                target_repo = ClipboardRepository(target_db)
        except Exception as e:
            QMessageBox.critical(
                self, t("error"), t("migration_failed", error=str(e))
            )
            return

        class MigrationWorker(QThread):
            progress = QSignal(int, int)
            finished_ok = QSignal(int)
            finished_err = QSignal(str)

            def __init__(self, migrator):
                super().__init__()
                self._migrator = migrator

            def run(self):
                try:
                    count = self._migrator.migrate(
                        progress_callback=lambda cur, tot: self.progress.emit(cur, tot)
                    )
                    self.finished_ok.emit(count)
                except Exception as e:
                    self.finished_err.emit(str(e))

        migrator = DatabaseMigrator(self.repository, target_repo)

        progress_dlg = QProgressDialog(t("migrating"), None, 0, 100, self)
        progress_dlg.setWindowTitle(t("migrate_data"))
        progress_dlg.setMinimumDuration(0)
        progress_dlg.setStyleSheet(MAIN_STYLE)

        worker = MigrationWorker(migrator)

        def on_progress(current, total):
            if total > 0:
                progress_dlg.setValue(int(current * 100 / total))

        def on_success(count):
            progress_dlg.close()
            QMessageBox.information(
                self, t("success"), t("migration_complete", count=count)
            )

        def on_error(err):
            progress_dlg.close()
            QMessageBox.critical(
                self, t("error"), t("migration_failed", error=err)
            )

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_success)
        worker.finished_err.connect(on_error)
        # 防止 worker 被 GC 回收
        self._migration_worker = worker
        worker.start()

    def _request_quit(self):
        """请求退出应用"""
        self.quit_requested.emit()
