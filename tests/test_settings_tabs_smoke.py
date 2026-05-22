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


def test_show_settings_dialog_full_chain_propagates_cloud_api(qapp, ctx):
    """端到端复现 user-reported "未登录" bug 的完整链路：

    main_window 上有 cloud_api/ctx → show_settings_dialog 调 SettingsDialog →
    SettingsDialog 把 cloud_api 转发给 TeamTab → 点邀请时 _resolve_cloud_api
    应该能拿到 cloud_api, 而不是 None。
    """
    from PySide6.QtWidgets import QWidget
    from ui.main_window_helpers import show_settings_dialog
    from ui.settings.team_tab import TeamTab

    # 用 Mock 让 cloud_tab._build_ui 读 is_authenticated 时不炸。
    # 比 object() 实用：is_authenticated=False 走"未登录视图"分支不发网络请求。
    from unittest.mock import Mock
    sentinel_cloud_api = Mock(name="cloud_api", is_authenticated=False)
    ctx.cloud_api = sentinel_cloud_api

    # show_settings_dialog 把 window 当作 QDialog 的 parent，Qt 要求是 QWidget。
    # 用 QWidget 子类挂上 main_window 暴露给 helper 的字段。
    class _FakeMainWindow(QWidget):
        pass

    fake_window = _FakeMainWindow()
    fake_window.cloud_api = sentinel_cloud_api
    fake_window.plugin_manager = None
    fake_window.space_service = ctx.space_service
    fake_window.entitlement_service = ctx.entitlement_service
    fake_window.ctx = ctx
    fake_window.cloud_controller = Mock(name="cloud_controller")

    captured: dict = {}
    original_exec = None
    try:
        from ui.settings.settings_dialog import SettingsDialog
        original_exec = SettingsDialog.exec

        def fake_exec(self):
            captured["dialog"] = self
            return 0  # Rejected, 跳过 _on_accept 落盘逻辑

        SettingsDialog.exec = fake_exec
        show_settings_dialog(fake_window)
    finally:
        if original_exec is not None:
            SettingsDialog.exec = original_exec
        ctx.cloud_api = None
        fake_window.deleteLater()

    dlg = captured.get("dialog")
    assert dlg is not None, "fake_exec 没被调到, show_settings_dialog 没构造 SettingsDialog"
    team_tab = dlg.team_tab
    assert isinstance(team_tab, TeamTab)
    # 关键断言：链路应该把 cloud_api 一路送到 TeamTab
    assert team_tab._resolve_cloud_api() is sentinel_cloud_api, (
        f"cloud_api 没穿到 TeamTab：tab._cloud_api={team_tab._cloud_api!r}, "
        f"tab.ctx={team_tab.ctx!r}"
    )
    dlg.close()


def test_team_tab_resolves_cloud_api_lazily(qapp, ctx):
    """复现并验证修复：team_tab 构造时 ctx.cloud_api 为 None，
    用户随后在云端 tab 登录把 client 写回 ctx 后，团队 tab 仍能拿到。

    Why: 之前 team_tab 在 __init__ 里把 ctx.cloud_api 缓存到 self._cloud_api，
    构造时 ctx 还没 cloud_api 就永久卡在 None，邀请按钮一直误报"未登录"。
    """
    from ui.settings.team_tab import TeamTab

    # 模拟"未登录"场景：手动把 ctx.cloud_api 清空
    # （test_settings_tabs_smoke 的 ctx fixture 不像 test_app_context 那样
    # monkeypatch 了 keyring，开发机有真实 token 时 bootstrap 会装配 cloud_api）
    original_cloud_api = ctx.cloud_api
    ctx.cloud_api = None
    tab = TeamTab(ctx=ctx)
    try:
        assert tab._resolve_cloud_api() is None

        # 模拟"用户在云端 tab 登录"——把一个假 client 写回 ctx
        sentinel = object()
        ctx.cloud_api = sentinel
        assert tab._resolve_cloud_api() is sentinel
    finally:
        tab.close()
        ctx.cloud_api = original_cloud_api
