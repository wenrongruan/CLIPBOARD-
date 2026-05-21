"""主链路 smoke test。

Why: 原有测试只覆盖数据层/模型层，无法检测 `main.py` 装配回归、
`PluginManager.load_plugins()` 崩溃、`MainWindow.__init__()` 初始化异常等整链路问题。

本测试：
1. 用 offscreen Qt 平台，避免需要真实显示器。
2. 用临时 SQLite DB + 临时配置目录，避免污染用户环境。
3. 确认 import main 成功、PluginManager 能加载空插件目录、
   MainWindow 能构造（不触发托盘/热键等副作用）。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def tmp_config_env(tmp_path, monkeypatch):
    """把 config 目录重定向到临时目录，避免真机数据被改动。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    import config
    monkeypatch.setattr(config, "get_config_dir", lambda: cfg_dir, raising=False)
    yield cfg_dir


def test_import_main_module():
    """main.py 能 import 不报错（构建时即暴露装配错误）。"""
    import main
    assert hasattr(main, "get_app_icon")


def test_plugin_manager_load_empty(qapp, tmp_path, monkeypatch):
    """PluginManager 能在空插件目录下安全加载不崩溃。"""
    empty_plugins = tmp_path / "plugins"
    empty_plugins.mkdir()
    user_plugins = tmp_path / "user_plugins"
    user_plugins.mkdir()

    from core import plugin_manager as pm_mod
    monkeypatch.setattr(
        pm_mod.PluginManager, "_get_plugin_dirs",
        lambda self: [empty_plugins, user_plugins],
    )

    pm = pm_mod.PluginManager()
    changed_events = []
    pm.plugins_changed.connect(lambda: changed_events.append(True))
    pm.load_plugins()
    assert pm._plugins == {}
    assert changed_events == [True]


def test_deferred_plugin_loader_calls_load_plugins():
    import main

    class FakePluginManager:
        def __init__(self):
            self.loaded = False

        def load_plugins(self):
            self.loaded = True

    app = main.ClipboardApp.__new__(main.ClipboardApp)
    app.plugin_manager = FakePluginManager()

    app._load_plugins_deferred()

    assert app.plugin_manager.loaded is True


def test_deferred_plugin_loader_reports_failure():
    import main

    class BrokenPluginManager:
        def load_plugins(self):
            raise RuntimeError("boom")

    app = main.ClipboardApp.__new__(main.ClipboardApp)
    app.plugin_manager = BrokenPluginManager()
    warnings = []
    app._on_runtime_health_warning = lambda component, message: warnings.append(
        (component, message)
    )

    app._load_plugins_deferred()

    assert warnings == [("plugin_manager", "插件加载失败，基础剪贴板功能仍可使用。")]


def test_deferred_cloud_sync_start_reports_failure(monkeypatch):
    import main

    class BrokenCloudSync:
        def start(self):
            raise RuntimeError("cloud boom")

    app = main.ClipboardApp.__new__(main.ClipboardApp)
    app.cloud_sync_service = BrokenCloudSync()
    warnings = []
    app._on_runtime_health_warning = lambda component, message: warnings.append(
        (component, message)
    )

    app._start_cloud_sync_deferred()

    assert warnings == [("cloud_sync", "云端同步启动失败，已降级到本地剪贴板历史。")]


def test_deferred_file_sync_start_reports_failure():
    import main

    class BrokenFileSync:
        def start(self):
            raise RuntimeError("file boom")

    app = main.ClipboardApp.__new__(main.ClipboardApp)
    app.file_sync_service = BrokenFileSync()
    warnings = []
    app._on_runtime_health_warning = lambda component, message: warnings.append(
        (component, message)
    )

    app._start_file_sync_deferred()

    assert warnings == [("file_sync", "文件云同步启动失败，剪贴板文本和图片历史仍可继续使用。")]


def test_deferred_sync_start_registers_atexit_once(monkeypatch):
    import main

    class FakeSync:
        def __init__(self):
            self.started = 0

        def start(self):
            self.started += 1

    registered = []
    monkeypatch.setattr(main.atexit, "register", lambda callback: registered.append(callback))

    app = main.ClipboardApp.__new__(main.ClipboardApp)
    app.cloud_sync_service = FakeSync()
    app.file_sync_service = FakeSync()

    app._start_cloud_sync_deferred()
    app._start_cloud_sync_deferred()
    app._start_file_sync_deferred()
    app._start_file_sync_deferred()

    assert app.cloud_sync_service.started == 2
    assert app.file_sync_service.started == 2
    assert registered == [app._atexit_persist_cloud_cursor, app._atexit_persist_file_cursor]


def test_deferred_file_sync_builds_services_on_demand(monkeypatch):
    import main
    import core.entitlement_service as ent_mod
    import core.file_sync_service as file_sync_mod

    class FakeEntitlement:
        def __init__(self):
            self.refreshed = 0
            self.cloud_api = None

        def refresh_async(self):
            self.refreshed += 1

        def set_cloud_api(self, cloud_api):
            self.cloud_api = cloud_api

    class FakeFileSync:
        def __init__(self, file_repo, cloud_api, entitlement, repository):
            self.file_repo = file_repo
            self.cloud_api = cloud_api
            self.entitlement = entitlement
            self.repository = repository
            self.started = 0

        def start(self):
            self.started += 1

    entitlement = FakeEntitlement()
    monkeypatch.setattr(
        ent_mod,
        "get_entitlement_service",
        lambda cloud_api=None, repository=None: entitlement,
    )
    monkeypatch.setattr(file_sync_mod, "FileCloudSyncService", FakeFileSync)
    registered = []
    monkeypatch.setattr(main.atexit, "register", lambda callback: registered.append(callback))

    app = main.ClipboardApp.__new__(main.ClipboardApp)
    app.cloud_api = object()
    app.repository = object()
    app.file_repository = object()
    app.file_sync_service = None
    app.entitlement_service = None
    app.ctx = type("Ctx", (), {})()
    app.main_window = type("Window", (), {})()

    app._start_file_sync_deferred()

    assert isinstance(app.file_sync_service, FakeFileSync)
    assert app.file_sync_service.started == 1
    assert entitlement.refreshed == 1
    assert app.ctx.file_sync_service is app.file_sync_service
    assert app.main_window.file_sync_service is app.file_sync_service
    assert registered == [app._atexit_persist_file_cursor]


def test_main_window_construct(qapp, tmp_config_env):
    """MainWindow 可用真实仓储 + monitor + sync 构造，不触发托盘/热键副作用。"""
    from core.database import DatabaseManager
    from core.repository import ClipboardRepository
    from core.clipboard_monitor import ClipboardMonitor
    from core.sync_service import SyncService
    from core.plugin_manager import PluginManager
    from ui.main_window import MainWindow

    db_path = tmp_config_env / "smoke.db"
    db = DatabaseManager(str(db_path))
    repo = ClipboardRepository(db)
    monitor = ClipboardMonitor(repo)
    sync = SyncService(repo)
    pm = PluginManager()

    try:
        window = MainWindow(
            repository=repo,
            clipboard_monitor=monitor,
            sync_service=sync,
            plugin_manager=pm,
            cloud_api=None,
            cloud_sync_service=None,
        )
        assert window is not None
        assert window.repository is repo
        window.close()
        window.deleteLater()
    finally:
        db.close()


def test_main_window_close_requests_quit_on_macos(qapp, tmp_config_env, monkeypatch):
    """macOS close should request app quit instead of silently hiding the window."""
    from core.database import DatabaseManager
    from core.repository import ClipboardRepository
    from core.clipboard_monitor import ClipboardMonitor
    from core.sync_service import SyncService
    from core.plugin_manager import PluginManager
    import ui.main_window as main_window_mod

    db_path = tmp_config_env / "smoke-macos-close.db"
    db = DatabaseManager(str(db_path))
    repo = ClipboardRepository(db)
    monitor = ClipboardMonitor(repo)
    sync = SyncService(repo)
    pm = PluginManager()

    monkeypatch.setattr(main_window_mod, "IS_MACOS", True)

    try:
        window = main_window_mod.MainWindow(
            repository=repo,
            clipboard_monitor=monitor,
            sync_service=sync,
            plugin_manager=pm,
            cloud_api=None,
            cloud_sync_service=None,
        )
        quit_events = []
        window.quit_requested.connect(lambda: quit_events.append(True))

        window.close()

        assert quit_events == [True]
        window.deleteLater()
    finally:
        db.close()
