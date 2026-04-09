import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtGui import QAction, QCursor
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
    QScrollArea,
)
from PySide6.QtWidgets import QButtonGroup, QProgressDialog, QInputDialog

import logging

from core.models import ClipboardItem, ContentType
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.sync_service import SyncService
from core.plugin_api import PluginResult, PluginResultAction
from config import Config
from i18n import t, set_language, get_language, get_languages, SUPPORTED_LANGUAGES
from .edge_window import EdgeHiddenWindow
from .clipboard_item import ClipboardItemWidget
from .styles import MAIN_STYLE

logger = logging.getLogger(__name__)


def _restore_cloud_api_from_config():
    """从已保存的 token 恢复 CloudAPIClient，失败返回 None"""
    if not Config.get_cloud_access_token():
        return None
    try:
        from core.cloud_api import CloudAPIClient
        client = CloudAPIClient(Config.get_cloud_api_url())
        client.set_tokens(
            Config.get_cloud_access_token(),
            Config.get_cloud_refresh_token(),
        )
        return client
    except Exception:
        logger.warning("从已保存 token 恢复 CloudAPIClient 失败", exc_info=True)
        return None


class PluginConfigDialog(QDialog):
    """根据 config_schema 自动生成的插件配置对话框"""

    def __init__(self, plugin_name: str, schema: dict, current_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("plugin_config_title", name=plugin_name))
        self.setFixedWidth(420)
        self.setStyleSheet(MAIN_STYLE)
        self._schema = schema
        self._widgets = {}
        self._setup_ui(current_config)

    def _setup_ui(self, current_config: dict):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(10)

        for key, spec in self._schema.items():
            field_type = spec.get("type", "string")
            label_text = spec.get("label", key)
            if spec.get("required"):
                label_text += " *"
            description = spec.get("description", "")
            default = spec.get("default", "")
            value = current_config.get(key, default)

            if field_type == "string":
                widget = QLineEdit()
                widget.setText(str(value) if value is not None else "")
                widget.setPlaceholderText(description)
                if spec.get("secret"):
                    widget.setEchoMode(QLineEdit.Password)
                self._widgets[key] = widget
                form.addRow(label_text, widget)

            elif field_type == "number":
                widget = QSpinBox()
                widget.setRange(spec.get("min", 0), spec.get("max", 999999))
                widget.setSingleStep(spec.get("step", 1))
                widget.setValue(int(value) if value is not None else 0)
                self._widgets[key] = widget
                form.addRow(label_text, widget)

            elif field_type == "boolean":
                widget = QCheckBox()
                widget.setChecked(bool(value))
                self._widgets[key] = widget
                form.addRow(label_text, widget)

            elif field_type == "select":
                widget = QComboBox()
                options = spec.get("options", [])
                widget.addItems([str(o) for o in options])
                if value in options:
                    widget.setCurrentText(str(value))
                self._widgets[key] = widget
                form.addRow(label_text, widget)

        layout.addLayout(form)
        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton(t("plugin_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QPushButton(t("plugin_save"))
        save_btn.setObjectName("okButton")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _on_save(self):
        # 检查必填项
        for key, spec in self._schema.items():
            if spec.get("required"):
                widget = self._widgets.get(key)
                if widget is None:
                    continue
                empty = False
                if isinstance(widget, QLineEdit):
                    empty = not widget.text().strip()
                elif isinstance(widget, QComboBox):
                    empty = not widget.currentText()
                if empty:
                    QMessageBox.warning(self, "", t("plugin_config_required"))
                    return
        self.accept()

    def get_config(self) -> dict:
        config = {}
        for key, spec in self._schema.items():
            widget = self._widgets.get(key)
            if widget is None:
                continue
            field_type = spec.get("type", "string")
            if field_type == "string":
                config[key] = widget.text()
            elif field_type == "number":
                config[key] = widget.value()
            elif field_type == "boolean":
                config[key] = widget.isChecked()
            elif field_type == "select":
                config[key] = widget.currentText()
        return config


class SettingsDialog(QDialog):
    def __init__(self, parent=None, plugin_manager=None, cloud_api=None):
        super().__init__(parent)
        self._plugin_manager = plugin_manager
        self._cloud_api = cloud_api
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

        # ========== 插件选项卡 ==========
        self._setup_plugin_tab(tab_widget)

        # ========== 云端同步选项卡 ==========
        self._setup_cloud_tab(tab_widget)

        # ========== 关于选项卡 ==========
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setSpacing(16)
        about_layout.setContentsMargins(20, 20, 20, 20)

        # 应用名称和描述
        app_name_label = QLabel(t("app_name"))
        app_name_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        app_name_label.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(app_name_label)

        desc_label = QLabel(t("about_description"))
        desc_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        desc_label.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(desc_label)

        about_layout.addSpacing(10)

        # 链接信息
        link_style = "color: #58a6ff; text-decoration: none;"
        links_group = QGroupBox("")
        links_layout = QFormLayout(links_group)
        links_layout.setSpacing(12)

        website_label = QLabel(f'<a href="https://www.jlike.com" style="{link_style}">www.jlike.com</a>')
        website_label.setOpenExternalLinks(True)
        links_layout.addRow(t("official_website"), website_label)

        github_label = QLabel(f'<a href="https://github.com/wenrongruan/CLIPBOARD-" style="{link_style}">github.com/wenrongruan/CLIPBOARD-</a>')
        github_label.setOpenExternalLinks(True)
        links_layout.addRow(t("github_repo"), github_label)

        download_label = QLabel(f'<a href="https://github.com/wenrongruan/CLIPBOARD-/releases" style="{link_style}">GitHub Releases</a>')
        download_label.setOpenExternalLinks(True)
        links_layout.addRow(t("download_page"), download_label)

        about_layout.addWidget(links_group)
        about_layout.addStretch()

        tab_widget.addTab(about_tab, t("about"))

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

    def _setup_plugin_tab(self, tab_widget):
        """构建插件选项卡"""
        plugin_tab = QWidget()
        plugin_layout = QVBoxLayout(plugin_tab)
        plugin_layout.setSpacing(10)

        # 标题
        title = QLabel(t("installed_plugins"))
        title.setObjectName("sectionTitle")
        plugin_layout.addWidget(title)

        # 插件列表（滚动区域）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        self._plugin_list_layout = QVBoxLayout(scroll_content)
        self._plugin_list_layout.setSpacing(6)
        self._plugin_list_layout.setContentsMargins(0, 0, 0, 0)
        self._plugin_list_layout.addStretch()
        scroll.setWidget(scroll_content)
        plugin_layout.addWidget(scroll, 1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        open_dir_btn = QPushButton(t("open_plugins_dir"))
        open_dir_btn.clicked.connect(self._open_plugins_dir)
        btn_layout.addWidget(open_dir_btn)

        reload_btn = QPushButton(t("reload_plugins"))
        reload_btn.clicked.connect(self._reload_plugins)
        btn_layout.addWidget(reload_btn)

        logs_btn = QPushButton(t("view_plugin_logs"))
        logs_btn.clicked.connect(self._open_plugin_logs)
        btn_layout.addWidget(logs_btn)

        dev_docs_btn = QPushButton(t("plugin_dev_docs"))
        dev_docs_btn.clicked.connect(self._open_plugin_dev_docs)
        btn_layout.addWidget(dev_docs_btn)

        btn_layout.addStretch()
        plugin_layout.addLayout(btn_layout)

        tab_widget.addTab(plugin_tab, t("plugins"))

        # 填充插件列表
        self._refresh_plugin_list()

    def _refresh_plugin_list(self):
        """刷新插件列表 UI"""
        # 清空旧内容（保留 stretch）
        while self._plugin_list_layout.count() > 1:
            item = self._plugin_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not hasattr(self, '_plugin_manager') or self._plugin_manager is None:
            return

        plugins = self._plugin_manager.get_loaded_plugins()
        if not plugins:
            empty_label = QLabel("没有找到插件")
            empty_label.setStyleSheet("color: #888888; padding: 20px;")
            empty_label.setAlignment(Qt.AlignCenter)
            self._plugin_list_layout.insertWidget(0, empty_label)
            return

        for i, info in enumerate(plugins):
            row = self._create_plugin_row(info)
            self._plugin_list_layout.insertWidget(i, row)

    def _create_plugin_row(self, info: dict) -> QWidget:
        """创建单个插件行"""
        row = QWidget()
        row.setObjectName("pluginItem")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(10)

        # 启用复选框
        cb = QCheckBox()
        cb.setChecked(info["enabled"])
        plugin_id = info["id"]
        cb.toggled.connect(lambda checked, pid=plugin_id: self._toggle_plugin(pid, checked))
        row_layout.addWidget(cb)

        # 信息区域
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(f"{info['name']} v{info['version']}")
        name_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(name_label)

        desc_label = QLabel(info["description"])
        desc_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)

        # 状态信息
        status = info["status"]
        if status == "missing_deps":
            status_label = QLabel(t("plugin_missing_deps", deps=", ".join(info["missing_deps"])))
            status_label.setStyleSheet("color: #f0ad4e; font-size: 11px;")
            info_layout.addWidget(status_label)
        elif status == "incompatible":
            status_label = QLabel(t("plugin_incompatible"))
            status_label.setStyleSheet("color: #f87171; font-size: 11px;")
            info_layout.addWidget(status_label)
        elif status == "error":
            status_label = QLabel(f"{t('plugin_error')}: {info['status_message']}")
            status_label.setStyleSheet("color: #f87171; font-size: 11px;")
            info_layout.addWidget(status_label)

        # 权限标签
        perms = info.get("permissions", [])
        perm_map = {
            "network": t("plugin_perm_network"),
            "file_read": t("plugin_perm_file_read"),
            "file_write": t("plugin_perm_file_write"),
        }
        sensitive = [perm_map[p] for p in perms if p in perm_map]
        if sensitive:
            perm_label = QLabel("  ".join(f"⚠ {s}" for s in sensitive))
            perm_label.setObjectName("permissionTag")
            info_layout.addWidget(perm_label)

        row_layout.addLayout(info_layout, 1)

        # 设置按钮（仅有 config_schema 的插件）
        if info.get("has_config") and status == "loaded":
            config_btn = QPushButton(t("plugin_settings"))
            config_btn.setObjectName("pluginConfigBtn")
            config_btn.clicked.connect(
                lambda checked=False, pid=plugin_id: self._open_plugin_config(pid)
            )
            row_layout.addWidget(config_btn)

        return row

    def _toggle_plugin(self, plugin_id: str, enabled: bool):
        Config.set_plugin_enabled(plugin_id, enabled)

    def _open_plugins_dir(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Config.get_user_plugins_dir())))

    def _reload_plugins(self):
        if hasattr(self, '_plugin_manager') and self._plugin_manager:
            self._plugin_manager.reload_plugins()
            self._refresh_plugin_list()

    def _open_plugin_logs(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        log_dir = Config.get_config_dir() / "logs"
        log_dir.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _open_plugin_dev_docs(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("https://www.jlike.com#dev-docs"))

    def _open_plugin_config(self, plugin_id: str):
        schema = self._plugin_manager.get_config_schema(plugin_id)
        current_config = self._plugin_manager.get_plugin_config(plugin_id)
        plugin_name = self._plugin_manager.get_plugin_name(plugin_id)

        dialog = PluginConfigDialog(plugin_name, schema, current_config, self)
        if dialog.exec() == QDialog.Accepted:
            new_config = dialog.get_config()
            self._plugin_manager.save_plugin_config(plugin_id, new_config)

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

    def _setup_cloud_tab(self, tab_widget):
        """构建云端同步选项卡"""
        cloud_tab = QWidget()
        cloud_layout = QVBoxLayout(cloud_tab)
        cloud_layout.setSpacing(12)
        cloud_layout.setContentsMargins(20, 20, 20, 20)

        # 说明文案
        desc = QLabel(
            "云端同步为可选增强功能，无需登录也能正常使用本软件的所有核心功能。\n"
            "开启后，你的剪贴板记录将额外备份到云端（收藏 + 最新记录），\n"
            "方便在不同设备间快速访问。"
        )
        desc.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        desc.setWordWrap(True)
        cloud_layout.addWidget(desc)

        # 根据登录状态显示不同内容
        self._cloud_content_container = QWidget()
        self._cloud_content_layout = QVBoxLayout(self._cloud_content_container)
        self._cloud_content_layout.setContentsMargins(0, 0, 0, 0)
        cloud_layout.addWidget(self._cloud_content_container, 1)

        # 如果没有传入 cloud_api，但配置中有已保存的 token，则创建客户端
        if not self._cloud_api:
            self._cloud_api = _restore_cloud_api_from_config()

        if self._cloud_api and self._cloud_api.is_authenticated:
            # 确保已认证的 cloud_api 注入到 PluginManager
            if self._plugin_manager:
                self._plugin_manager.set_cloud_client(self._cloud_api)
            self._show_cloud_logged_in()
        else:
            self._show_cloud_login_form()

        tab_widget.addTab(cloud_tab, "云端同步")

    def _show_cloud_login_form(self):
        """显示云端登录表单"""
        from .cloud_login_widget import CloudLoginWidget
        from core.cloud_api import CloudAPIClient

        layout = self._cloud_content_layout

        form_group = QGroupBox("登录云端账户")
        group_layout = QVBoxLayout(form_group)

        if not self._cloud_api:
            self._cloud_api = CloudAPIClient(Config.get_cloud_api_url())

        self._cloud_login_widget = CloudLoginWidget(self._cloud_api)
        self._cloud_login_widget.login_succeeded.connect(self._on_cloud_login_success)
        group_layout.addWidget(self._cloud_login_widget)

        layout.addWidget(form_group)
        layout.addStretch()

    def _show_cloud_logged_in(self):
        """显示已登录的订阅状态"""
        from .subscription_widget import SubscriptionWidget
        widget = SubscriptionWidget(self._cloud_api)
        self._cloud_content_layout.addWidget(widget)

    def _on_cloud_login_success(self, result: dict):
        """云端登录成功回调"""
        self._cloud_login_widget.status_label.setText("登录成功！重启应用后启用云端同步。")
        # 将 cloud_api 注入到 PluginManager，使插件可以使用认证和扣点功能
        if self._plugin_manager and self._cloud_api:
            self._plugin_manager.set_cloud_client(self._cloud_api)
        self._save_clipboard_auth_file()

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

    def _save_clipboard_auth_file(self):
        """将当前 token 写入 ~/.shared_clipboard/auth.json，供 chat_image_gen 独立启动时复用登录态。"""
        if not self._cloud_api or not self._cloud_api.is_authenticated:
            return
        try:
            auth_dir = Path.home() / ".shared_clipboard"
            auth_dir.mkdir(parents=True, exist_ok=True)
            access_token, refresh_token = self._cloud_api.get_tokens()
            data = {
                "api_base_url": Config.get_cloud_api_url(),
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
            (auth_dir / "auth.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.warning("保存 auth.json 失败", exc_info=True)

    def get_cloud_api(self):
        """返回当前的云端 API 客户端（可能在对话框中登录后更新）"""
        return self._cloud_api

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
        plugin_manager=None,
        cloud_api=None,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.clipboard_monitor = clipboard_monitor
        self.sync_service = sync_service
        self.plugin_manager = plugin_manager
        self.cloud_api = cloud_api

        # 如果没有传入 cloud_api，但有已保存的 token，则创建客户端
        if not self.cloud_api:
            self.cloud_api = _restore_cloud_api_from_config()

        # 将 cloud_api 注入到 PluginManager，使插件可以复用登录态
        if self.plugin_manager and self.cloud_api:
            self.plugin_manager.set_cloud_client(self.cloud_api)

        self._current_page = 0
        self._total_pages = 1
        self._page_size = Config.PAGE_SIZE
        self._search_query = ""
        self._starred_only = False
        self._items: List[ClipboardItem] = []
        self._copy_executor = ThreadPoolExecutor(max_workers=1)
        self._cloud_executor = ThreadPoolExecutor(max_workers=1)

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
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
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

        # 插件信号
        if self.plugin_manager:
            self.plugin_manager.action_progress.connect(self._on_plugin_progress)
            self.plugin_manager.action_finished.connect(self._on_plugin_finished)
            self.plugin_manager.action_error.connect(self._on_plugin_error)

    def _toggle_starred_filter(self):
        self._starred_only = not self._starred_only
        self.star_filter_btn.setText("★" if self._starred_only else "☆")
        self._current_page = 0
        self._load_items()

    def _load_items(self):
        try:
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
        except Exception as e:
            logger.error(f"加载剪贴板条目失败: {e}")

    def _make_list_item(self, item: ClipboardItem):
        """创建 ClipboardItemWidget 和对应的 QListWidgetItem，连接信号"""
        widget = ClipboardItemWidget(item)
        widget.clicked.connect(self._on_item_clicked)
        widget.delete_clicked.connect(self._on_item_delete)
        widget.star_clicked.connect(self._on_item_star)
        widget.save_clicked.connect(self._on_item_save)
        widget.cloud_delete_clicked.connect(self._on_cloud_delete)

        list_item = QListWidgetItem()
        hint = widget.sizeHint()
        min_h = 92 if item.is_image else 76
        list_item.setSizeHint(QSize(hint.width(), max(hint.height(), min_h)))
        return list_item, widget

    def _update_list(self):
        self.list_widget.clear()

        for item in self._items:
            list_item, widget = self._make_list_item(item)
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

    def _show_copy_feedback(self, success: bool):
        """显示复制结果反馈"""
        if success:
            self.copy_feedback_label.setText(t("copied_to_clipboard"))
            self.copy_feedback_label.setObjectName("copyFeedbackSuccess")
        else:
            self.copy_feedback_label.setText(t("copy_failed"))
            self.copy_feedback_label.setObjectName("copyFeedbackError")
        self.copy_feedback_label.style().polish(self.copy_feedback_label)
        self.copy_feedback_label.show()
        self._feedback_timer.start(2000)

    def _on_item_clicked(self, item: ClipboardItem):
        # 图片需要从数据库获取完整数据 — 异步加载避免阻塞主线程
        if item.is_image:
            self.copy_feedback_label.setText("正在加载图片...")
            self.copy_feedback_label.setObjectName("copyFeedbackSuccess")
            self.copy_feedback_label.style().polish(self.copy_feedback_label)
            self.copy_feedback_label.show()

            future = self._copy_executor.submit(self.repository.get_item_by_id, item.id)

            def _on_loaded(f):
                try:
                    full_item = f.result()
                    success = self.clipboard_monitor.copy_to_clipboard(full_item) if full_item else False
                except Exception as e:
                    logger.error(f"加载图片失败: {e}")
                    success = False
                self._show_copy_feedback(success)

            future.add_done_callback(lambda f: QTimer.singleShot(0, lambda: _on_loaded(f)))
            return

        success = self.clipboard_monitor.copy_to_clipboard(item)
        self._show_copy_feedback(success)

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

    def _on_cloud_delete(self, item: ClipboardItem):
        """删除条目的云端副本"""
        if not item.cloud_id or not self.cloud_api:
            return
        reply = QMessageBox.question(
            self,
            "删除云端副本",
            "确定删除该条目的云端副本？\n本地记录不受影响。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        cloud_id = item.cloud_id
        item_id = item.id
        api = self.cloud_api

        future = self._cloud_executor.submit(api.delete_item, cloud_id)

        def _on_done(f):
            try:
                f.result()
                self.repository.clear_cloud_id(item_id)
                item.cloud_id = None
                self._load_items()
            except Exception as e:
                logger.warning(f"删除云端副本失败: {e}")

        future.add_done_callback(lambda f: QTimer.singleShot(0, lambda: _on_done(f)))

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

    def _prepend_item(self, item: ClipboardItem):
        """在列表顶部插入单个新条目，避免全量重建"""
        list_item, widget = self._make_list_item(item)

        self.list_widget.insertItem(0, list_item)
        self.list_widget.setItemWidget(list_item, widget)
        self._items.insert(0, item)

        # 超出每页大小时移除末尾
        if self.list_widget.count() > self._page_size:
            self.list_widget.takeItem(self.list_widget.count() - 1)
            if len(self._items) > self._page_size:
                self._items.pop()

    def _on_item_added(self, item: ClipboardItem):
        if self._current_page == 0 and not self._search_query and not self._starred_only:
            self._prepend_item(item)
        elif self._current_page == 0 and not self._search_query:
            self._load_items()

    def _on_new_items(self, items: List[ClipboardItem]):
        # 来自其他设备的新记录
        if self._current_page == 0 and not self._search_query:
            self._load_items()

    def _toggle_pin(self):
        is_pinned = self.toggle_pin()
        # 取消固定时若处于悬浮模式，吸附回最近边缘
        if not is_pinned and self._is_floating:
            self._snap_to_nearest_edge()
        self.pin_btn.setText("📍" if is_pinned else "📌")
        self.pin_btn.setToolTip(t("unpin_window") if is_pinned else t("pin_window"))

    def _minimize_window(self):
        """最小化窗口（完全隐藏）"""
        self.hide_window()

    def _show_settings(self):
        dialog = SettingsDialog(self, plugin_manager=self.plugin_manager, cloud_api=self.cloud_api)
        result = dialog.exec()
        # 无论确认还是取消，都同步登录状态（用户可能在对话框中登录了云端）
        dialog_cloud_api = dialog.get_cloud_api()
        if dialog_cloud_api and dialog_cloud_api.is_authenticated:
            self.cloud_api = dialog_cloud_api
            if self.plugin_manager:
                self.plugin_manager.set_cloud_client(self.cloud_api)
        if result == QDialog.Accepted:
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

    # ========== 右键菜单 ==========

    def _show_context_menu(self, pos):
        """显示右键上下文菜单"""
        list_item = self.list_widget.itemAt(pos)
        if not list_item:
            return
        row = self.list_widget.row(list_item)
        if row < 0 or row >= len(self._items):
            return

        item = self._items[row]
        menu = QMenu(self)

        # 内置操作
        copy_action = menu.addAction(f"📋 {t('ctx_copy')}")
        copy_action.triggered.connect(lambda: self._on_item_clicked(item))

        if item.is_starred:
            star_action = menu.addAction(f"★ {t('ctx_unstar')}")
        else:
            star_action = menu.addAction(f"☆ {t('ctx_star')}")
        star_action.triggered.connect(lambda: self._on_item_star(item))

        delete_action = menu.addAction(f"🗑 {t('ctx_delete')}")
        delete_action.triggered.connect(lambda: self._on_item_delete(item))

        # 插件操作
        if self.plugin_manager:
            groups = self.plugin_manager.get_plugin_actions_grouped(item)
            if groups:
                menu.addSeparator()
                for group in groups:
                    actions = group["actions"]
                    if len(actions) == 1:
                        # 单动作插件直接作为菜单项
                        a = actions[0]
                        act = menu.addAction(f"{a.icon} {a.label}")
                        act.triggered.connect(
                            lambda checked=False, pid=group["plugin_id"], aid=a.action_id:
                                self._run_plugin_action(pid, aid, item)
                        )
                    else:
                        # 多动作插件使用子菜单
                        sub = menu.addMenu(f"{actions[0].icon} {group['plugin_name']}")
                        for a in actions:
                            act = sub.addAction(a.label)
                            act.triggered.connect(
                                lambda checked=False, pid=group["plugin_id"], aid=a.action_id:
                                    self._run_plugin_action(pid, aid, item)
                            )

        menu.exec(self.list_widget.mapToGlobal(pos))

    # ========== 插件执行 ==========

    def _run_plugin_action(self, plugin_id: str, action_id: str, item: ClipboardItem):
        """执行插件动作"""
        # 获取完整数据（图片需要从数据库加载）
        if item.is_image:
            full_item = self.repository.get_item_by_id(item.id)
            if full_item and full_item.image_data:
                item = full_item
            else:
                self._show_plugin_feedback("❌ " + t("plugin_error"), "copyFeedbackError")
                return

        if not self.plugin_manager.run_action(plugin_id, action_id, item):
            return  # 被拒绝（已有任务在执行）

        # 显示进度
        plugin_name = self.plugin_manager.get_plugin_name(plugin_id)
        self._show_plugin_feedback(
            t("plugin_executing", name=plugin_name, percent=0),
            "pluginProgress",
            show_cancel=True,
        )

    def _on_plugin_progress(self, percent: int, message: str):
        text = message if message else f"{percent}%"
        self._show_plugin_feedback(text, "pluginProgress", show_cancel=True)

    def _on_plugin_finished(self, result: PluginResult, original_item: ClipboardItem):
        if not result.success:
            if result.cancelled:
                self.copy_feedback_label.hide()
                return
            self._show_plugin_feedback(
                f"❌ {result.error_message or t('plugin_exec_failed')}", "copyFeedbackError"
            )
            return

        # 根据 action 处理结果
        if result.action == PluginResultAction.NONE:
            self.copy_feedback_label.hide()
            return

        if result.action == PluginResultAction.COPY:
            # 复制到剪贴板
            temp_item = ClipboardItem(
                content_type=result.content_type,
                text_content=result.text_content,
                image_data=result.image_data,
            )
            self.clipboard_monitor.copy_to_clipboard(temp_item)
            self._show_plugin_feedback(t("copied_to_clipboard"), "copyFeedbackSuccess")

        elif result.action == PluginResultAction.SAVE:
            # 保存为新条目
            from utils.hash_utils import compute_content_hash
            hash_content = result.text_content or result.image_data
            if not hash_content:
                self._show_plugin_feedback("❌ 插件返回空内容", "copyFeedbackError")
                return
            new_item = ClipboardItem(
                content_type=result.content_type,
                text_content=result.text_content,
                image_data=result.image_data,
                content_hash=compute_content_hash(hash_content),
                preview=(result.text_content or "")[:100],
                device_id=Config.get_device_id(),
                device_name=Config.get_device_name(),
            )
            self.repository.add_item(new_item)
            self._load_items()
            self._show_plugin_feedback(t("plugin_saved_entry"), "copyFeedbackSuccess")

        elif result.action == PluginResultAction.REPLACE:
            # 替换原条目
            if original_item and original_item.id:
                success = self.repository.update_item_content(
                    original_item.id,
                    text_content=result.text_content,
                    image_data=result.image_data,
                    content_type=result.content_type.value if result.content_type else None,
                )
                if success:
                    self._load_items()
                    self._show_plugin_feedback(t("plugin_replaced_entry"), "copyFeedbackSuccess")
                else:
                    self._show_plugin_feedback("❌ " + t("plugin_error"), "copyFeedbackError")

    def _on_plugin_error(self, message: str):
        self._show_plugin_feedback(f"❌ {message}", "copyFeedbackError")

    def _show_plugin_feedback(self, text: str, object_name: str, show_cancel: bool = False):
        """显示插件反馈信息"""
        if show_cancel:
            self.copy_feedback_label.setText(f"{text}  [✕]")
            self.copy_feedback_label.mousePressEvent = lambda e: self._cancel_plugin()
        else:
            self.copy_feedback_label.setText(text)
            self.copy_feedback_label.mousePressEvent = lambda e: None
            self._feedback_timer.start(3000)
        self.copy_feedback_label.setObjectName(object_name)
        self.copy_feedback_label.style().polish(self.copy_feedback_label)
        self.copy_feedback_label.show()

    def _cancel_plugin(self):
        if self.plugin_manager:
            self.plugin_manager.cancel_action()
        self.copy_feedback_label.hide()

    def _request_quit(self):
        """请求退出应用"""
        self.quit_requested.emit()
