"""Phase 5: ui/settings 拆分冒烟测试。

不验证业务逻辑，只验证：
1. SettingsDialog 在 AppContext 注入下能正常构造。
2. 每个 Tab 都能单独构造（保证模块加载、依赖、layout 不出错）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """与 tests/test_app_context.py 相同的 config 重定向方式。"""
    import config

    def _fake_dir() -> Path:
        return tmp_path

    def _fake_file() -> Path:
        return tmp_path / "settings.json"

    def _fake_plugins_dir() -> Path:
        p = tmp_path / "plugins"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _fake_files_dir() -> Path:
        p = tmp_path / "files"
        p.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr(config, "get_config_dir", _fake_dir)
    monkeypatch.setattr(config, "get_config_file", _fake_file)
    monkeypatch.setattr(config, "get_user_plugins_dir", _fake_plugins_dir)
    monkeypatch.setattr(config, "get_files_local_dir", _fake_files_dir)

    store = config.get_store()
    store._path = None
    store._snapshot = None
    store._extras = {}
    store._dirty = False

    from core.app_context import AppContext

    AppContext._instance = None
    c = AppContext.bootstrap()
    yield c
    c.shutdown()
    AppContext._instance = None


def test_settings_dialog_constructs(qapp, ctx):
    from ui.settings import SettingsDialog
    dlg = SettingsDialog(ctx=ctx, auto_load_store=False)
    assert dlg is not None
    dlg.close()


def test_settings_dialog_shim_works(qapp, ctx):
    """旧路径 from ui.settings_dialog 必须仍可用，且是同一个类。"""
    from ui.settings import SettingsDialog as NewDialog
    from ui.settings_dialog import SettingsDialog as ShimDialog
    assert NewDialog is ShimDialog


def test_each_tab_constructs(qapp, ctx):
    from ui.settings.about_tab import AboutTab
    from ui.settings.cloud_tab import CloudTab
    from ui.settings.database_tab import DatabaseTab
    from ui.settings.filter_tab import FilterTab
    from ui.settings.general_tab import GeneralTab
    from ui.settings.plugins_tab import PluginsTab
    from ui.settings.team_tab import TeamTab

    for cls in (GeneralTab, DatabaseTab, FilterTab, CloudTab, TeamTab, AboutTab):
        w = cls(ctx=ctx)
        assert w is not None
        w.close()

    w = PluginsTab(ctx=ctx, auto_load_store=False)
    assert w is not None
    w.close()
