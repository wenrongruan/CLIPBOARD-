"""应用设置对话框 — 通用/数据库/过滤/插件/云端/关于六个选项卡"""

import logging
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from config import (
    APP_VERSION,
    settings,
    update_settings,
    get_cloud_access_token,
    get_effective_hotkey,
    get_effective_database_path,
    get_mysql_config,
    set_mysql_config,
    set_plugin_enabled,
    get_user_plugins_dir,
    get_config_dir,
)
from i18n import t, get_languages
from .plugin_config_dialog import PluginConfigDialog
from .styles import MAIN_STYLE

logger = logging.getLogger(__name__)


_ACTIVE_THREADS: set = set()


def _track_thread(thread: QThread) -> None:
    """保持 QThread 的 Python 强引用直到 finished, 避免 dialog 先销毁
    导致 QThread 在 isRunning() 状态被 Python GC 析构触发 qFatal → abort。"""
    _ACTIVE_THREADS.add(thread)
    thread.finished.connect(lambda: _ACTIVE_THREADS.discard(thread))


class _StoreLoadThread(QThread):
    """后台加载插件商店列表"""
    loaded = Signal(list)
    error = Signal(str)

    def __init__(self, api_url: str):
        super().__init__()
        self._api_url = api_url.rstrip("/")

    def run(self):
        import httpx
        try:
            resp = httpx.get(
                f"{self._api_url}/api/plugins/store",
                timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=10.0),
            )
            if resp.status_code == 200:
                self.loaded.emit(resp.json().get("plugins", []))
            else:
                self.error.emit(f"HTTP {resp.status_code}")
        except Exception as e:
            self.error.emit(str(e))


class _PluginInstallThread(QThread):
    """后台下载并安装插件"""
    installed = Signal(str)
    error = Signal(str, str)

    def __init__(self, api_url: str, plugin_id: str, download_url: str, target_dir: str):
        super().__init__()
        self._api_url = api_url.rstrip("/")
        self._plugin_id = plugin_id
        self._download_url = download_url
        self._target_dir = Path(target_dir)

    def run(self):
        import httpx
        import tempfile
        import zipfile

        try:
            url = self._download_url if self._download_url.startswith("http") \
                else f"{self._api_url}{self._download_url}"
            resp = httpx.get(
                url,
                timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=10.0),
                follow_redirects=True,
            )
            if resp.status_code != 200:
                self.error.emit(self._plugin_id, f"HTTP {resp.status_code}")
                return

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            try:
                with zipfile.ZipFile(tmp_path) as zf:
                    resolved_target = self._target_dir.resolve()
                    for member in zf.namelist():
                        member_path = (self._target_dir / member).resolve()
                        if not member_path.is_relative_to(resolved_target):
                            self.error.emit(self._plugin_id, f"安全检查失败: {member}")
                            shutil.rmtree(self._target_dir, ignore_errors=True)
                            return
                    zf.extractall(self._target_dir)
            except Exception:
                shutil.rmtree(self._target_dir, ignore_errors=True)
                raise
            finally:
                os.unlink(tmp_path)

            self.installed.emit(self._plugin_id)
        except Exception as e:
            self.error.emit(self._plugin_id, str(e))


def _restore_cloud_api_from_config():
    """返回全局 CloudAPIClient（仅在已登录时返回非 None）。"""
    if not get_cloud_access_token():
        return None
    try:
        from core.cloud_api import get_cloud_client
        return get_cloud_client()
    except Exception:
        logger.warning("恢复 CloudAPIClient 失败", exc_info=True)
        return None


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

        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        self._build_general_tab(tab_widget)
        self._build_database_tab(tab_widget)
        self._build_filter_tab(tab_widget)
        self._setup_plugin_tab(tab_widget)
        self._setup_cloud_tab(tab_widget)
        self._build_about_tab(tab_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = button_box.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setObjectName("okButton")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # ========== 通用 ==========

    def _build_general_tab(self, tab_widget):
        general_tab = QWidget()
        general_layout = QFormLayout(general_tab)
        general_layout.setSpacing(12)

        self.language_combo = QComboBox()
        languages = get_languages()
        self._language_codes = list(languages.keys())
        self.language_combo.addItems(list(languages.values()))
        current_lang = settings().language
        if current_lang in self._language_codes:
            self.language_combo.setCurrentIndex(self._language_codes.index(current_lang))
        general_layout.addRow(t("language"), self.language_combo)

        self.dock_combo = QComboBox()
        self.dock_combo.addItems([t("dock_right"), t("dock_left"), t("dock_top"), t("dock_bottom")])
        edge_map = {"right": 0, "left": 1, "top": 2, "bottom": 3}
        current_edge = settings().dock_edge
        self.dock_combo.setCurrentIndex(edge_map.get(current_edge, 0))
        general_layout.addRow(t("dock_position"), self.dock_combo)

        hotkey_layout = QHBoxLayout()
        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setText(get_effective_hotkey())
        self.hotkey_edit.setPlaceholderText(t("hotkey_placeholder"))
        hotkey_layout.addWidget(self.hotkey_edit)

        hotkey_help = QLabel("?")
        hotkey_help.setToolTip(t("hotkey_help"))
        hotkey_help.setStyleSheet("color: #888; font-weight: bold;")
        hotkey_layout.addWidget(hotkey_help)
        general_layout.addRow(t("global_hotkey"), hotkey_layout)

        tab_widget.addTab(general_tab, t("general"))

    # ========== 数据库 ==========

    def _build_database_tab(self, tab_widget):
        db_tab = QWidget()
        db_layout = QVBoxLayout(db_tab)
        db_layout.setSpacing(12)

        profile_layout = QHBoxLayout()
        profile_layout.setSpacing(8)
        profile_layout.addWidget(QLabel(t("db_profile")))

        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        profiles = dict(settings().db_profiles)
        active = settings().active_profile
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

        current_db_index = 0 if settings().db_type == "sqlite" else 1
        self.db_type_group.button(current_db_index).setChecked(True)
        self.db_type_group.idClicked.connect(self._on_db_type_changed)

        db_layout.addLayout(db_card_layout)

        self.sqlite_group = QGroupBox(t("sqlite_config"))
        sqlite_layout = QFormLayout(self.sqlite_group)

        path_layout = QHBoxLayout()
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setText(get_effective_database_path())
        self.db_path_edit.setPlaceholderText(t("path_placeholder"))
        path_layout.addWidget(self.db_path_edit)

        browse_btn = QPushButton(t("browse"))
        browse_btn.clicked.connect(self._browse_db_path)
        path_layout.addWidget(browse_btn)
        sqlite_layout.addRow(t("db_path"), path_layout)

        db_layout.addWidget(self.sqlite_group)

        self.mysql_group = QGroupBox(t("mysql_config"))
        mysql_layout = QFormLayout(self.mysql_group)

        mysql_config = get_mysql_config()

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
        self.mysql_password_edit.setEchoMode(QLineEdit.Password)
        # Why: 预填已保存密码,避免重开对话框时字段为空导致 OK 按钮用空密码测试认证失败。
        # Password echo 模式下视觉仍是点点,不会泄露明文。
        self.mysql_password_edit.setText(mysql_config.get("password", ""))
        self.mysql_password_edit.setPlaceholderText(t("password"))
        mysql_layout.addRow(t("password"), self.mysql_password_edit)

        self.mysql_database_edit = QLineEdit()
        self.mysql_database_edit.setText(mysql_config["database"])
        self.mysql_database_edit.setPlaceholderText("clipboard")
        mysql_layout.addRow(t("db_name"), self.mysql_database_edit)

        test_btn_layout = QHBoxLayout()
        self.test_connection_btn = QPushButton(t("test_connection"))
        self.test_connection_btn.clicked.connect(self._test_mysql_connection)
        test_btn_layout.addWidget(self.test_connection_btn)
        test_btn_layout.addStretch()
        mysql_layout.addRow("", test_btn_layout)

        db_layout.addWidget(self.mysql_group)
        db_layout.addStretch()

        tab_widget.addTab(db_tab, t("database"))

        self._on_db_type_changed(self.db_type_group.checkedId())

    # ========== 过滤/存储 ==========

    def _build_filter_tab(self, tab_widget):
        filter_tab = QWidget()
        filter_layout = QVBoxLayout(filter_tab)
        filter_layout.setSpacing(12)

        filter_group = QGroupBox(t("content_filter"))
        filter_group_layout = QFormLayout(filter_group)
        filter_group_layout.setSpacing(8)

        self.save_text_check = QCheckBox(t("save_text"))
        self.save_text_check.setChecked(settings().save_text)
        filter_group_layout.addRow(self.save_text_check)

        self.save_images_check = QCheckBox(t("save_images"))
        self.save_images_check.setChecked(settings().save_images)
        filter_group_layout.addRow(self.save_images_check)

        self.max_text_length_spin = QSpinBox()
        self.max_text_length_spin.setRange(0, 10000000)
        self.max_text_length_spin.setValue(settings().max_text_length)
        self.max_text_length_spin.setSpecialValueText(t("unlimited"))
        self.max_text_length_spin.setSuffix(f" {t('characters')}")
        filter_group_layout.addRow(t("max_text_length"), self.max_text_length_spin)

        self.max_image_size_spin = QSpinBox()
        self.max_image_size_spin.setRange(0, 102400)
        self.max_image_size_spin.setValue(settings().max_image_size_kb)
        self.max_image_size_spin.setSpecialValueText(t("unlimited"))
        self.max_image_size_spin.setSuffix(" KB")
        filter_group_layout.addRow(t("max_image_size"), self.max_image_size_spin)

        filter_layout.addWidget(filter_group)

        storage_group = QGroupBox(t("storage_management"))
        storage_group_layout = QFormLayout(storage_group)
        storage_group_layout.setSpacing(8)

        self.max_items_spin = QSpinBox()
        self.max_items_spin.setRange(100, 100000)
        self.max_items_spin.setValue(settings().max_items)
        storage_group_layout.addRow(t("max_items"), self.max_items_spin)

        self.retention_days_spin = QSpinBox()
        self.retention_days_spin.setRange(0, 3650)
        self.retention_days_spin.setValue(settings().retention_days)
        self.retention_days_spin.setSpecialValueText(t("never_cleanup"))
        self.retention_days_spin.setSuffix(f" {t('days')}")
        storage_group_layout.addRow(t("retention_days"), self.retention_days_spin)

        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(100, 5000)
        self.poll_interval_spin.setSingleStep(100)
        self.poll_interval_spin.setValue(settings().poll_interval_ms)
        self.poll_interval_spin.setSuffix(" ms")
        storage_group_layout.addRow(t("poll_interval"), self.poll_interval_spin)

        filter_layout.addWidget(storage_group)
        filter_layout.addStretch()

        tab_widget.addTab(filter_tab, t("filter_storage"))

    # ========== 关于 ==========

    def _build_about_tab(self, tab_widget):
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setSpacing(16)
        about_layout.setContentsMargins(20, 20, 20, 20)

        app_name_label = QLabel(t("app_name"))
        app_name_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        app_name_label.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(app_name_label)

        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet("color: #888888; font-size: 13px;")
        version_label.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(version_label)

        desc_label = QLabel(t("about_description"))
        desc_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        desc_label.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(desc_label)

        about_layout.addSpacing(10)

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

    # ========== 插件 ==========

    def _setup_plugin_tab(self, tab_widget):
        plugin_tab = QWidget()
        plugin_layout = QVBoxLayout(plugin_tab)
        plugin_layout.setSpacing(10)

        self._store_thread = None
        self._install_threads = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(6)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # -- 已安装插件 --
        installed_title = QLabel(t("installed_plugins"))
        installed_title.setObjectName("sectionTitle")
        content_layout.addWidget(installed_title)

        self._plugin_list_layout = QVBoxLayout()
        self._plugin_list_layout.setSpacing(6)
        content_layout.addLayout(self._plugin_list_layout)

        # -- 分隔线 --
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #555555; margin: 8px 0;")
        content_layout.addWidget(separator)

        # -- 插件商店 --
        store_header = QHBoxLayout()
        store_title = QLabel(t("plugin_store"))
        store_title.setObjectName("sectionTitle")
        store_header.addWidget(store_title)
        store_header.addStretch()
        self._store_refresh_btn = QPushButton(t("refresh"))
        self._store_refresh_btn.clicked.connect(self._load_store_plugins)
        store_header.addWidget(self._store_refresh_btn)
        content_layout.addLayout(store_header)

        self._store_list_layout = QVBoxLayout()
        self._store_list_layout.setSpacing(6)
        content_layout.addLayout(self._store_list_layout)

        content_layout.addStretch()
        scroll.setWidget(scroll_content)
        plugin_layout.addWidget(scroll, 1)

        # -- 底部按钮 --
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

        self._refresh_plugin_list()
        self._load_store_plugins()

    # -- 已安装插件 --

    def _refresh_plugin_list(self):
        self._clear_layout(self._plugin_list_layout)

        if not hasattr(self, '_plugin_manager') or self._plugin_manager is None:
            return

        plugins = self._plugin_manager.get_loaded_plugins()
        if not plugins:
            empty_label = QLabel(t("plugin_no_installed"))
            empty_label.setStyleSheet("color: #888888; padding: 10px;")
            empty_label.setAlignment(Qt.AlignCenter)
            self._plugin_list_layout.addWidget(empty_label)
            return

        for info in plugins:
            row = self._create_plugin_row(info)
            self._plugin_list_layout.addWidget(row)

    def _create_plugin_row(self, info: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("pluginItem")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(10)

        cb = QCheckBox()
        cb.setChecked(info["enabled"])
        plugin_id = info["id"]
        cb.toggled.connect(lambda checked, pid=plugin_id: self._toggle_plugin(pid, checked))
        row_layout.addWidget(cb)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(f"{info['name']} v{info['version']}")
        name_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(name_label)

        desc_label = QLabel(info["description"])
        desc_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)

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

        row_layout.addLayout(info_layout, 1)

        btn_box = QVBoxLayout()
        btn_box.setSpacing(4)

        if info.get("has_config") and status == "loaded":
            config_btn = QPushButton(t("plugin_settings"))
            config_btn.setObjectName("pluginConfigBtn")
            config_btn.clicked.connect(
                lambda checked=False, pid=plugin_id: self._open_plugin_config(pid)
            )
            btn_box.addWidget(config_btn)

        uninstall_btn = QPushButton(t("plugin_uninstall"))
        uninstall_btn.setStyleSheet(
            "QPushButton { color: #f87171; border: 1px solid #f87171; padding: 2px 8px; }"
            "QPushButton:hover { background: #f87171; color: white; }"
        )
        uninstall_btn.clicked.connect(
            lambda checked=False, pid=plugin_id: self._uninstall_plugin(pid)
        )
        btn_box.addWidget(uninstall_btn)

        row_layout.addLayout(btn_box)
        return row

    def _toggle_plugin(self, plugin_id: str, enabled: bool):
        set_plugin_enabled(plugin_id, enabled)

    def _uninstall_plugin(self, plugin_id: str):
        reply = QMessageBox.question(
            self,
            t("plugin_uninstall_confirm_title"),
            t("plugin_uninstall_confirm", name=self._plugin_manager.get_plugin_name(plugin_id)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if self._plugin_manager.uninstall_plugin(plugin_id):
            self._plugin_manager.reload_plugins()
            self._refresh_plugin_list()
            self._load_store_plugins()
        else:
            QMessageBox.warning(self, t("plugin_uninstall_failed"), t("plugin_uninstall_failed"))

    # -- 插件商店 --

    def _load_store_plugins(self):
        self._store_refresh_btn.setEnabled(False)
        self._clear_layout(self._store_list_layout)

        loading_label = QLabel(t("plugin_store_loading"))
        loading_label.setStyleSheet("color: #888888; padding: 10px;")
        loading_label.setAlignment(Qt.AlignCenter)
        self._store_list_layout.addWidget(loading_label)

        thread = _StoreLoadThread(settings().cloud_api_url)
        thread.loaded.connect(self._on_store_loaded)
        thread.error.connect(self._on_store_error)
        thread.finished.connect(thread.deleteLater)
        _track_thread(thread)
        self._store_thread = thread
        thread.start()

    def _on_store_loaded(self, plugins: list):
        self._store_refresh_btn.setEnabled(True)
        self._clear_layout(self._store_list_layout)

        installed_ids = set()
        if self._plugin_manager:
            installed_ids = {p["id"] for p in self._plugin_manager.get_loaded_plugins()}

        available = [p for p in plugins if p.get("id") not in installed_ids]

        if not available:
            label = QLabel(t("plugin_store_empty"))
            label.setStyleSheet("color: #888888; padding: 10px;")
            label.setAlignment(Qt.AlignCenter)
            self._store_list_layout.addWidget(label)
            return

        for info in available:
            row = self._create_store_plugin_row(info)
            self._store_list_layout.addWidget(row)

    def _on_store_error(self, error_msg: str):
        self._store_refresh_btn.setEnabled(True)
        self._clear_layout(self._store_list_layout)

        label = QLabel(t("plugin_store_error"))
        label.setStyleSheet("color: #f87171; padding: 10px;")
        label.setAlignment(Qt.AlignCenter)
        self._store_list_layout.addWidget(label)

    def _create_store_plugin_row(self, info: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("pluginItem")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(10)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(f"{info.get('name', info['id'])} v{info.get('version', '?')}")
        name_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(name_label)

        desc = info.get("description", "")
        if desc:
            desc_label = QLabel(desc)
            desc_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
            desc_label.setWordWrap(True)
            info_layout.addWidget(desc_label)

        row_layout.addLayout(info_layout, 1)

        install_btn = QPushButton(t("plugin_install"))
        install_btn.setStyleSheet(
            "QPushButton { color: #4fc3f7; border: 1px solid #4fc3f7; padding: 4px 16px; }"
            "QPushButton:hover { background: #4fc3f7; color: white; }"
            "QPushButton:disabled { color: #888888; border-color: #888888; }"
        )
        plugin_id = info["id"]
        download_url = info.get("download_url", f"/api/plugins/download/{plugin_id}")
        install_btn.clicked.connect(
            lambda checked=False, pid=plugin_id, url=download_url, btn=install_btn:
                self._install_plugin(pid, url, btn)
        )
        row_layout.addWidget(install_btn)

        return row

    def _install_plugin(self, plugin_id: str, download_url: str, btn: QPushButton):
        btn.setEnabled(False)
        btn.setText(t("plugin_installing"))

        thread = _PluginInstallThread(
            settings().cloud_api_url, plugin_id, download_url, str(get_user_plugins_dir()),
        )
        thread.installed.connect(lambda pid: self._on_install_finished(pid, btn))
        thread.error.connect(lambda pid, err: self._on_install_error(pid, err, btn))
        thread.finished.connect(thread.deleteLater)
        _track_thread(thread)
        self._install_threads[plugin_id] = thread
        thread.start()

    def _on_install_finished(self, plugin_id: str, btn: QPushButton):
        self._install_threads.pop(plugin_id, None)
        btn.setText(t("plugin_installed_tag"))
        if self._plugin_manager:
            self._plugin_manager.reload_plugins()
        self._refresh_plugin_list()
        self._load_store_plugins()

    def _on_install_error(self, plugin_id: str, error_msg: str, btn: QPushButton):
        self._install_threads.pop(plugin_id, None)
        btn.setEnabled(True)
        btn.setText(t("plugin_install"))
        QMessageBox.warning(self, t("plugin_install_failed"), error_msg)

    # -- 插件通用 --

    def _open_plugins_dir(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_user_plugins_dir())))

    def _reload_plugins(self):
        if hasattr(self, '_plugin_manager') and self._plugin_manager:
            self._plugin_manager.reload_plugins()
            self._refresh_plugin_list()
            self._load_store_plugins()

    def _open_plugin_logs(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        log_dir = get_config_dir() / "logs"
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

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ========== 数据库回调 ==========

    def _on_db_type_changed(self, index: int):
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
            start_dir = get_effective_database_path()

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
                QMessageBox.information(self, f"MySQL — {t('connection_success')}", message)
            else:
                QMessageBox.warning(self, f"MySQL — {t('connection_failed')}", message)
        except ImportError:
            QMessageBox.warning(
                self, t("missing_dependency"),
                t("pymysql_required")
            )
        except Exception as e:
            QMessageBox.critical(self, f"MySQL — {t('error')}", f"{str(e)}")

    def _on_profile_changed(self, name: str):
        profiles = settings().db_profiles
        profile = profiles.get(name)
        if not profile:
            return
        db_type = profile.get("db_type", "sqlite")
        self.db_type_group.button(0 if db_type == "sqlite" else 1).setChecked(True)
        self._on_db_type_changed(0 if db_type == "sqlite" else 1)
        self.db_path_edit.setText(profile.get("database_path", ""))
        self.mysql_host_edit.setText(profile.get("mysql_host", "localhost"))
        self.mysql_port_spin.setValue(profile.get("mysql_port", 3306))
        self.mysql_user_edit.setText(profile.get("mysql_user", ""))
        # Why: profile 不持久化密码(只走 keyring),切换时用 keyring 值预填避免字段变空。
        self.mysql_password_edit.setText(get_mysql_config().get("password", ""))
        self.mysql_database_edit.setText(profile.get("mysql_database", "clipboard"))

    def _add_profile(self):
        name, ok = QInputDialog.getText(self, t("profile_name"), t("enter_profile_name"))
        if not ok or not name.strip():
            return
        name = name.strip()
        profiles = dict(settings().db_profiles)
        if name in profiles:
            QMessageBox.warning(self, t("warning"), t("profile_exists"))
            return
        # Why: profile 持久化到 settings.json，绝不能带明文密码（密码走 keyring）。
        profile_settings = self._current_db_settings()
        profile_settings["mysql_password"] = ""
        profiles[name] = profile_settings
        update_settings(db_profiles=profiles)
        self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(name)

    def _delete_profile(self):
        name = self.profile_combo.currentText()
        profiles = dict(settings().db_profiles)
        if len(profiles) <= 1:
            return
        if name == settings().active_profile:
            QMessageBox.warning(self, t("warning"), t("cannot_delete_active"))
            return
        reply = QMessageBox.question(
            self, t("confirm_delete"), t("confirm_delete_profile", name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            del profiles[name]
            update_settings(db_profiles=profiles)
            self.profile_combo.removeItem(self.profile_combo.currentIndex())

    def _current_db_settings(self) -> dict:
        """从 UI 中读取当前数据库配置（纯读取，无副作用）。
        Why: 原实现在这里直接写 keyring，但该函数会被 _add_profile /
        get_settings 等多个路径调用，包括 Cancel 前的探测；只读保证幂等。
        密码持久化统一搬到 _on_accept 一次完成。
        """
        db_type = "sqlite" if self.db_type_group.checkedId() == 0 else "mysql"
        return {
            "db_type": db_type,
            "database_path": self.db_path_edit.text(),
            "mysql_host": self.mysql_host_edit.text() or "localhost",
            "mysql_port": self.mysql_port_spin.value(),
            "mysql_user": self.mysql_user_edit.text(),
            # 明文密码随 dict 返回，调用方（_on_accept）负责写入安全存储
            "mysql_password": self.mysql_password_edit.text(),
            "mysql_database": self.mysql_database_edit.text() or "clipboard",
        }

    # ========== 云端同步 ==========

    def _setup_cloud_tab(self, tab_widget):
        cloud_tab = QWidget()
        cloud_layout = QVBoxLayout(cloud_tab)
        cloud_layout.setSpacing(12)
        cloud_layout.setContentsMargins(20, 20, 20, 20)

        desc = QLabel(
            "云端同步为可选增强功能，无需登录也能正常使用本软件的所有核心功能。\n"
            "开启后，你的剪贴板记录将额外备份到云端（收藏 + 最新记录），\n"
            "方便在不同设备间快速访问。"
        )
        desc.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        desc.setWordWrap(True)
        cloud_layout.addWidget(desc)

        self._cloud_content_container = QWidget()
        self._cloud_content_layout = QVBoxLayout(self._cloud_content_container)
        self._cloud_content_layout.setContentsMargins(0, 0, 0, 0)
        cloud_layout.addWidget(self._cloud_content_container, 1)

        if not self._cloud_api:
            self._cloud_api = _restore_cloud_api_from_config()

        if self._cloud_api and self._cloud_api.is_authenticated:
            if self._plugin_manager:
                self._plugin_manager.set_cloud_client(self._cloud_api)
            self._show_cloud_logged_in()
        else:
            self._show_cloud_login_form()

        tab_widget.addTab(cloud_tab, "云端同步")

    def _show_cloud_login_form(self):
        from .cloud_login_widget import CloudLoginWidget
        from core.cloud_api import get_cloud_client

        layout = self._cloud_content_layout

        form_group = QGroupBox("登录云端账户")
        group_layout = QVBoxLayout(form_group)

        if not self._cloud_api:
            self._cloud_api = get_cloud_client()

        self._cloud_login_widget = CloudLoginWidget(self._cloud_api)
        self._cloud_login_widget.login_succeeded.connect(self._on_cloud_login_success)
        group_layout.addWidget(self._cloud_login_widget)

        layout.addWidget(form_group)
        layout.addStretch()

    def _show_cloud_logged_in(self):
        from .subscription_widget import SubscriptionWidget
        widget = SubscriptionWidget(self._cloud_api)
        self._cloud_content_layout.addWidget(widget)

    def _on_cloud_login_success(self, result: dict):
        self._cloud_login_widget.status_label.setText("登录成功！重启应用后启用云端同步。")
        if self._plugin_manager and self._cloud_api:
            self._plugin_manager.set_cloud_client(self._cloud_api)

    # ========== 保存 ==========

    def _on_accept(self):
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
                        f"MySQL — {t('connection_failed')}",
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

            try:
                set_mysql_config(
                    host=host, port=port, user=user,
                    password=password, database=database,
                )
            except Exception as e:
                logger.warning(f"保存 MySQL 配置到安全存储失败: {e}")

        self.accept()

    def get_cloud_api(self):
        return self._cloud_api

    def get_settings(self) -> dict:
        """返回纯 dict（含明文 mysql_password 字段）。
        Why: 旧实现把 keyring 写入藏在这里，违反"读"的语义。当前函数只做数据汇总，
        由调用方决定如何持久化；mysql_password 的 keyring 写入已挪到 _on_accept。
        """
        edge_map = {0: "right", 1: "left", 2: "top", 3: "bottom"}
        db_settings = self._current_db_settings()
        language = self._language_codes[self.language_combo.currentIndex()]

        # profile 持久化时剥掉明文密码——密码只通过 keyring 保存。
        profile_snapshot = dict(db_settings)
        profile_snapshot["mysql_password"] = ""

        profile_name = self.profile_combo.currentText()
        profiles = dict(settings().db_profiles)
        profiles[profile_name] = profile_snapshot
        update_settings(db_profiles=profiles)

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
