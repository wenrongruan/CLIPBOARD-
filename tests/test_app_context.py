"""AppContext (ServiceRegistry) tests.

config.get_config_dir() 在 Windows 下读 APPDATA，在 macOS/Linux 走 ~/Library 或 ~/.config，
没有专用的 SHARED_CLIPBOARD_CONFIG_DIR 环境变量。这里直接 monkeypatch
config.get_config_dir，让所有依赖 config_dir 的服务都用 tmp_path。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _redirect_config_dir(monkeypatch, tmp_path):
    """每个测试自动隔离：

    1) config 模块所有 *_dir / *_file 重定向到 tmp_path，避免污染真实 APPDATA。
    2) 清空 AppContext._instance，确保 bootstrap 从空状态开始。
    """
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

    # 关键：把 cloud token 取值固定成空串。
    # config.get_cloud_access_token 会先查系统 keyring，再 fallback 读 ~/.shared_clipboard/auth.json，
    # 两条路径都不受 tmp_path 隔离影响——开发者本机如果登录过云端，
    # bootstrap 就会装配 cloud_api，导致 "cloud_api is None" 这类断言偶发失败。
    monkeypatch.setattr(config, "get_cloud_access_token", lambda: "")
    monkeypatch.setattr(config, "get_cloud_refresh_token", lambda: "")

    # SettingsStore 已经持有 _path 缓存的情况下需要重置，让它走新的 tmp_path
    store = config.get_store()
    store._path = None
    store._snapshot = None
    store._extras = {}
    store._dirty = False

    # 重置 AppContext 单例，避免上一个测试遗留
    from core.app_context import AppContext

    AppContext._instance = None
    yield
    AppContext._instance = None


def test_bootstrap_returns_context_with_all_services():
    """bootstrap 后所有声明的 service 字段都不为 None。"""
    from core.app_context import AppContext

    ctx = AppContext.bootstrap()
    try:
        assert ctx.db is not None
        assert ctx.repository is not None
        assert ctx.clipboard_monitor is not None
        assert ctx.sync_service is not None
        # 未登录时不构造 cloud_api；打开云端登录页时再懒加载。
        assert ctx.cloud_api is None
        # 未登录时云端业务服务保持 None；登录态下才装配
        # 这里只断言字段存在
        assert hasattr(ctx, "cloud_sync_service")
        assert hasattr(ctx, "file_sync_service")
        assert hasattr(ctx, "entitlement_service")
        assert ctx.space_service is not None
        assert ctx.tag_service is not None
        assert ctx.share_service is not None
        assert ctx.plugin_manager is not None
    finally:
        ctx.shutdown()


def test_current_returns_bootstrapped_context():
    from core.app_context import AppContext

    ctx = AppContext.bootstrap()
    try:
        assert AppContext.current() is ctx
    finally:
        ctx.shutdown()


def test_current_raises_before_bootstrap():
    from core.app_context import AppContext

    with pytest.raises(RuntimeError):
        AppContext.current()


def test_shutdown_clears_current():
    from core.app_context import AppContext

    ctx = AppContext.bootstrap()
    ctx.shutdown()
    assert AppContext._instance is None


def test_bootstrap_is_idempotent():
    """重复调用 bootstrap() 应返回同一实例，不重新装配。"""
    from core.app_context import AppContext

    ctx1 = AppContext.bootstrap()
    try:
        ctx2 = AppContext.bootstrap()
        assert ctx1 is ctx2
    finally:
        ctx1.shutdown()


def test_cloud_api_is_created_lazily_and_written_back():
    from core.app_context import AppContext
    from core.cloud_api import get_cloud_client

    ctx = AppContext.bootstrap()
    try:
        assert ctx.cloud_api is None
        client = get_cloud_client()
        assert client is not None
        assert ctx.cloud_api is client
    finally:
        ctx.shutdown()


def test_reset_cloud_client_clears_context_reference():
    from core.app_context import AppContext
    from core.cloud_api import get_cloud_client, reset_cloud_client

    ctx = AppContext.bootstrap()
    try:
        client = get_cloud_client()
        assert ctx.cloud_api is client
        reset_cloud_client()
        assert ctx.cloud_api is None
    finally:
        ctx.shutdown()


def test_logged_in_bootstrap_defers_file_sync_worker(monkeypatch):
    import config
    import core.cloud_api as cloud_api_mod
    from core.app_context import AppContext

    class FakeCloudClient:
        is_authenticated = True

    monkeypatch.setattr(config, "get_cloud_access_token", lambda: "token")
    monkeypatch.setattr(cloud_api_mod, "get_cloud_client", lambda: FakeCloudClient())

    ctx = AppContext.bootstrap()
    try:
        assert ctx.cloud_api is not None
        assert ctx.cloud_sync_service is not None
        assert ctx.file_repository is not None
        assert ctx.entitlement_service is None
        assert ctx.file_sync_service is None
    finally:
        ctx.shutdown()


def test_shutdown_handles_partial_init():
    """部分初始化的 ctx 也应能安全 shutdown,不抛异常。"""
    from core.app_context import AppContext

    ctx = AppContext()  # 不走 bootstrap
    ctx.shutdown()  # 不该抛
