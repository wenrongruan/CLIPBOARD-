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
    pm.load_plugins()
    assert pm._plugins == {}


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
