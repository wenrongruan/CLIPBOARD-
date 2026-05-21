"""插件管理 Tab：已安装列表 + 插件商店（非 App Store 构建）。"""

import logging
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config import (
    IS_APPSTORE_BUILD, get_config_dir, get_user_plugins_dir,
    set_plugin_enabled, settings,
)
from i18n import t
from ui.plugin_config_dialog import PluginConfigDialog

logger = logging.getLogger(__name__)


# 与旧 settings_dialog.py 共享同一份线程引用集合，避免 GC abort。
_ACTIVE_THREADS: set = set()


def _track_thread(thread: QThread) -> None:
    """保持 QThread 的 Python 强引用直到 finished, 避免 dialog 先销毁
    导致 QThread 在 isRunning() 状态被 Python GC 析构触发 qFatal → abort。"""
    _ACTIVE_THREADS.add(thread)
    thread.finished.connect(lambda: _ACTIVE_THREADS.discard(thread))


class _StoreLoadThread(QThread):
    """后台加载插件商店列表。"""
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
    """后台下载并安装插件。"""
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


class PluginsTab(QWidget):
    """对应旧 SettingsDialog._setup_plugin_tab。"""

    def __init__(
        self,
        ctx=None,
        parent=None,
        plugin_manager=None,
        auto_load_store: bool = True,
        **_legacy_kwargs,
    ):
        super().__init__(parent)
        self.ctx = ctx
        # ctx 优先，没有时回退到旧的显式参数
        self._plugin_manager = plugin_manager
        if self._plugin_manager is None and ctx is not None:
            self._plugin_manager = getattr(ctx, "plugin_manager", None)
        self._store_thread = None
        self._install_threads = {}
        self._build_ui()
        if self._plugin_manager is not None and hasattr(self._plugin_manager, "plugins_changed"):
            self._plugin_manager.plugins_changed.connect(self._refresh_plugin_list)
        self._refresh_plugin_list()
        if auto_load_store and not IS_APPSTORE_BUILD:
            self._load_store_plugins()

    def _build_ui(self):
        plugin_layout = QVBoxLayout(self)
        plugin_layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(6)
        content_layout.setContentsMargins(0, 0, 0, 0)

        desc = QLabel(
            "插件是可选自动化增强；插件加载、商店或执行失败不会影响本地剪贴板历史、搜索和热键。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa; font-size: 12px; padding: 0 0 8px 0;")
        content_layout.addWidget(desc)

        # 已安装插件
        installed_title = QLabel(t("installed_plugins"))
        installed_title.setObjectName("sectionTitle")
        content_layout.addWidget(installed_title)

        self._plugin_list_layout = QVBoxLayout()
        self._plugin_list_layout.setSpacing(6)
        content_layout.addLayout(self._plugin_list_layout)

        # App Store / 沙盒构建下隐藏插件商店与外部目录按钮（App Review 2.5.2 禁止
        # 应用下载或加载可执行代码；卸载/打开插件目录也一并隐藏避免误导）。
        self._store_list_layout = None
        self._store_refresh_btn = None

        if not IS_APPSTORE_BUILD:
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setStyleSheet("color: #555555; margin: 8px 0;")
            content_layout.addWidget(separator)

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

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        if not IS_APPSTORE_BUILD:
            open_dir_btn = QPushButton(t("open_plugins_dir"))
            open_dir_btn.clicked.connect(self._open_plugins_dir)
            btn_layout.addWidget(open_dir_btn)

            reload_btn = QPushButton(t("reload_plugins"))
            reload_btn.clicked.connect(self._reload_plugins)
            btn_layout.addWidget(reload_btn)

        logs_btn = QPushButton(t("view_plugin_logs"))
        logs_btn.clicked.connect(self._open_plugin_logs)
        btn_layout.addWidget(logs_btn)

        if not IS_APPSTORE_BUILD:
            dev_docs_btn = QPushButton(t("plugin_dev_docs"))
            dev_docs_btn.clicked.connect(self._open_plugin_dev_docs)
            btn_layout.addWidget(dev_docs_btn)

        btn_layout.addStretch()
        plugin_layout.addLayout(btn_layout)

    # ---- 已安装插件 ----

    def _refresh_plugin_list(self):
        self._clear_layout(self._plugin_list_layout)

        if self._plugin_manager is None:
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

        if not IS_APPSTORE_BUILD:
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
        if self._plugin_manager is None:
            return
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

    # ---- 插件商店 ----

    def _load_store_plugins(self):
        if self._store_list_layout is None or self._store_refresh_btn is None:
            return
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

        # 过滤对当前 APP_VERSION 不兼容的插件
        from config import APP_VERSION

        def _ver_tuple(v: str):
            try:
                return tuple(int(x) for x in (v or "").split("."))
            except (ValueError, AttributeError):
                return ()

        app_v = _ver_tuple(APP_VERSION)
        available: list = []
        incompatible: list = []
        for p in plugins:
            if p.get("id") in installed_ids:
                continue
            min_ver = p.get("min_app_version") or ""
            min_v = _ver_tuple(min_ver)
            if min_v and app_v and app_v < min_v:
                incompatible.append((p, min_ver))
                continue
            available.append(p)

        if not available and not incompatible:
            label = QLabel(t("plugin_store_empty"))
            label.setStyleSheet("color: #888888; padding: 10px;")
            label.setAlignment(Qt.AlignCenter)
            self._store_list_layout.addWidget(label)
            return

        for info in available:
            row = self._create_store_plugin_row(info)
            self._store_list_layout.addWidget(row)

        if incompatible:
            hint = QLabel(
                f"另有 {len(incompatible)} 个插件需要更高版本（当前 {APP_VERSION}），"
                "请升级 SharedClipboard 后再查看。"
            )
            hint.setStyleSheet("color:#aaa;font-size:11px;padding:8px 4px;")
            hint.setWordWrap(True)
            self._store_list_layout.addWidget(hint)

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

    # ---- 通用 ----

    def _open_plugins_dir(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_user_plugins_dir())))

    def _reload_plugins(self):
        if self._plugin_manager:
            self._plugin_manager.reload_plugins()
            self._refresh_plugin_list()
            self._load_store_plugins()

    def _open_plugin_logs(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        log_dir = get_config_dir() / "logs"
        log_dir.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _open_plugin_dev_docs(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://www.jlike.com#dev-docs"))

    def _open_plugin_config(self, plugin_id: str):
        if self._plugin_manager is None:
            return
        schema = self._plugin_manager.get_config_schema(plugin_id)
        current_config = self._plugin_manager.get_plugin_config(plugin_id)
        plugin_name = self._plugin_manager.get_plugin_name(plugin_id)
        try:
            permissions = self._plugin_manager.get_plugin_permissions(plugin_id)
        except Exception:
            permissions = []

        dialog = PluginConfigDialog(
            plugin_name, schema, current_config, self, permissions=permissions
        )
        if dialog.exec() == QDialog.Accepted:
            new_config = dialog.get_config()
            self._plugin_manager.save_plugin_config(plugin_id, new_config)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
