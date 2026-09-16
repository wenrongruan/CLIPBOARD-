"""2026-09-16 代码审查修复的回归测试。

覆盖报告中的 P0 修复：
- P0-A 迁移列数与 to_db_tuple 一致，写入真实生效
- P0-B 配置文件字段类型异常不崩溃、回退默认值
- P0-7 file_storage 沙盒路径拒绝非法 sha
- P0-5 插件权限代理默认拒绝（_real / get_tokens / 未标注方法）
- 文件同步游标：解析失败不推进游标；字段名 sha256 兼容
- LIKE 转义：搜 "100%" 不被通配符污染
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.repository import ClipboardRepository
from core.models import TextClipboardItem
from core.migration import DatabaseMigrator
from core import file_storage


# ---------------------------------------------------------------- P0-A 迁移

@pytest.fixture
def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    repository = ClipboardRepository(db)
    yield repository
    db.close()


def _make_item(text="hello", suffix=""):
    return TextClipboardItem(
        text_content=text,
        content_hash=f"hash_{text}_{suffix}",
        preview=text[:50],
        device_id="dev1",
        device_name="TestPC",
        created_at=1000,
    )


class TestMigrationWritesAllColumns:
    def test_migrate_actually_writes_items(self, repo, tmp_path):
        """修复前 _INSERT_SQL 只有 10 列而 to_db_tuple 返回 13 值，
        异常被吞后返回 0 却报"迁移完成"。此用例锁定"迁移真的写入"。"""
        for i in range(5):
            it = _make_item(f"item{i}", suffix=str(i))
            repo.add_item(it)

        target_db = DatabaseManager(str(tmp_path / "target.db"))
        target_repo = ClipboardRepository(target_db)
        try:
            migrator = DatabaseMigrator(repo, target_repo)
            migrated = migrator.migrate()
            assert migrated == 5
            items, total = target_repo.get_items_full(0, 100)
            assert total == 5
        finally:
            target_db.close()

    def test_migrate_failure_raises(self, repo, tmp_path):
        """批量失败必须上抛，不允许静默返回假成功计数。"""
        class BrokenTarget:
            """模拟目标库写入失败"""
            def __init__(self, real):
                self._real = real
                self.db = real.db

            def __getattr__(self, name):
                return getattr(self._real, name)

        target_db = DatabaseManager(str(tmp_path / "target2.db"))
        target_repo = ClipboardRepository(target_db)

        # 把 target 的 execute_many 换成抛错
        orig = target_repo.db.execute_many
        def boom(*a, **kw):
            raise RuntimeError("simulated disk failure")
        target_repo.db.execute_many = boom

        try:
            repo.add_item(_make_item("x1", suffix="a"))
            migrator = DatabaseMigrator(repo, target_repo)
            with pytest.raises(RuntimeError):
                migrator.migrate()
        finally:
            target_repo.db.execute_many = orig
            target_db.close()


# ---------------------------------------------------------------- P0-B 配置容错

class TestConfigTypeTolerance:
    def _load_config(self, tmp_path, monkeypatch, payload):
        cfg = tmp_path / "settings.json"
        cfg.write_text(json.dumps(payload), encoding="utf-8")
        from config import SettingsStore
        mgr = SettingsStore(cfg)
        return mgr

    def test_null_int_field_falls_back_to_default(self, tmp_path):
        """mysql_port=null 修复前抛 TypeError 导致启动即崩溃且不可自愈。"""
        mgr = self._load_config(tmp_path, None, {"mysql_port": None})
        s = mgr.snapshot()
        assert s.mysql.port == 3306

    def test_string_int_field_falls_back(self, tmp_path):
        mgr = self._load_config(tmp_path, None, {"max_items": "abc"})
        s = mgr.snapshot()
        assert s.max_items == 10000

    def test_non_dict_top_level_falls_back(self, tmp_path):
        cfg = tmp_path / "settings.json"
        cfg.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        from config import SettingsStore
        mgr = SettingsStore(cfg)
        s = mgr.snapshot()
        assert s.max_items == 10000


# ---------------------------------------------------------------- P0-7 路径穿越

class TestSandboxPathValidation:
    def test_valid_sha_returns_container_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.get_files_local_dir", lambda: str(tmp_path / "files"))
        sha = "a" * 64
        p = file_storage.sandbox_path_for(sha)
        assert str(p).startswith(str(tmp_path / "files" / "aa"))

    def test_traversal_sha_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.get_files_local_dir", lambda: str(tmp_path / "files"))
        with pytest.raises(ValueError):
            file_storage.sandbox_path_for("../../Users/x/.ssh/authorized_keys")

    def test_short_sha_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.get_files_local_dir", lambda: str(tmp_path / "files"))
        with pytest.raises(ValueError):
            file_storage.sandbox_path_for("abcd")


# ---------------------------------------------------------------- P0-5 插件代理

class TestPluginCloudProxyDefaultDeny:
    def _make_proxy(self):
        from core.plugin_manager import _make_plugin_cloud_client_proxy
        from core.cloud_api import CloudAPIClient

        client = CloudAPIClient("https://example.invalid")
        return _make_plugin_cloud_client_proxy(client, ["network", "credits"]), client

    def test_private_attr_access_denied(self):
        """修复前 proxy._real 直接返回真实客户端，权限模型一行即被绕过。"""
        proxy, _ = self._make_proxy()
        with pytest.raises(PermissionError):
            _ = proxy._real

    def test_token_methods_denied(self):
        proxy, _ = self._make_proxy()
        with pytest.raises(PermissionError):
            _ = proxy.get_tokens()
        with pytest.raises(PermissionError):
            proxy.set_tokens("a", "b")

    def test_undeclared_public_method_denied_without_permission(self):
        """未声明 credits 权限时 get_balance 应被拒；声明后可访问。"""
        from core.plugin_manager import _make_plugin_cloud_client_proxy
        from core.cloud_api import CloudAPIClient

        client = CloudAPIClient("https://example.invalid")
        p_none = _make_plugin_cloud_client_proxy(client, [])
        with pytest.raises(PermissionError):
            _ = p_none.get_balance

        p_credits = _make_plugin_cloud_client_proxy(client, ["credits"])
        assert callable(getattr(p_credits, "get_balance"))

    def test_declared_network_method_allowed(self):
        proxy, _ = self._make_proxy()
        # sync() 标注了 network 权限，代理应返回可调用对象
        assert callable(getattr(proxy, "sync"))

    def test_write_denied(self):
        proxy, _ = self._make_proxy()
        with pytest.raises(PermissionError):
            proxy.anything = 1


class TestPluginDomainProxyCompat:
    """client.<domain>.<method>() 这一老写法必须继续可用。

    Why 单独回归：旧实现的 __getattr__ 是 `getattr(self._real, name)` 直通，
    client.auth 返回的是**未代理的真实 AuthClient** —— 所以
    client.auth.ai_generate() 是插件作者实际在用的写法
    （core/plugin_api.py:get_cloud_client 的文档也只说"返回 CloudAPIClient 实例"）。
    改成默认拒绝时若只放行 facade 上的扁平方法名，按文档写的老插件会立刻
    PermissionError。domain 层必须是"同样默认拒绝的子代理"，而不是直接放行。
    """

    def _make_proxy(self, permissions=("network", "credits")):
        from core.plugin_manager import _make_plugin_cloud_client_proxy
        from core.cloud_api import CloudAPIClient

        client = CloudAPIClient("https://example.invalid")
        return _make_plugin_cloud_client_proxy(client, list(permissions)), client

    def test_domain_access_returns_proxy_not_real_client(self):
        """client.auth 不得再是真实 AuthClient，否则 _http.get_tokens() 可直达凭据。"""
        proxy, client = self._make_proxy()
        auth = proxy.auth
        assert auth is not client.auth
        with pytest.raises(PermissionError):
            _ = auth._http
        with pytest.raises(PermissionError):
            _ = auth._facade

    def test_domain_annotated_method_allowed_when_declared(self):
        """老写法 client.auth.ai_generate(...)（network）声明后仍可用。"""
        proxy, _ = self._make_proxy()
        assert callable(proxy.auth.ai_generate)

    def test_domain_credits_method_gated_by_permission(self):
        from core.plugin_manager import _make_plugin_cloud_client_proxy
        from core.cloud_api import CloudAPIClient

        client = CloudAPIClient("https://example.invalid")
        no_credits = _make_plugin_cloud_client_proxy(client, ["network"])
        with pytest.raises(PermissionError):
            _ = no_credits.auth.get_balance

        with_credits = _make_plugin_cloud_client_proxy(client, ["credits"])
        assert callable(with_credits.auth.get_balance)

    def test_domain_unregistered_method_denied(self):
        """domain 子代理同样默认拒绝：未标注权限的方法一律不可达。"""
        proxy, _ = self._make_proxy()
        with pytest.raises(PermissionError):
            _ = proxy.auth.not_a_registered_api
        with pytest.raises(PermissionError):
            _ = proxy.sync_client.get_tokens

    def test_domain_write_denied(self):
        proxy, _ = self._make_proxy()
        with pytest.raises(PermissionError):
            proxy.auth.anything = 1

    def test_public_attr_still_readable(self):
        """内置插件 ai_image_gen 只用 base_url，必须继续可读。"""
        proxy, _ = self._make_proxy()
        assert proxy.base_url == "https://example.invalid"

    def test_private_attr_still_denied_on_facade(self):
        proxy, _ = self._make_proxy()
        with pytest.raises(PermissionError):
            _ = proxy._real


# ---------------------------------------------------------------- 文件同步游标

class TestFileSyncCursorSafety:
    def _make_service(self, tmp_path):
        from core.file_sync_service import _FileSyncWorker as FileSyncWorker
        from core.database import DatabaseManager
        from core.file_repository import CloudFileRepository
        from core.cloud_api import CloudAPIClient

        db = DatabaseManager(str(tmp_path / "files.db"))
        repo = CloudFileRepository(db)
        api = CloudAPIClient("https://example.invalid")
        # 不触发 settings() 对设备字段的依赖
        svc = FileSyncWorker.__new__(FileSyncWorker)
        svc.cloud_api = api
        svc.repo = repo
        svc.entitlement = None
        svc._pull_skip = {}
        return svc, repo, db

    def test_invalid_sha_does_not_advance_cursor(self, tmp_path):
        """解析失败的条目不得推进游标，否则数据永久丢失。"""
        svc, _, db = self._make_service(tmp_path)
        items = [{"id": 5, "sha256": "bad-value"}]
        parsed, cursor = svc._process_page(items, 100)
        assert parsed == []
        assert cursor == 100  # 未推进
        db.close()

    def test_sha256_field_name_accepted(self, tmp_path):
        """后端返回键名是 sha256；客户端必须兼容（旧代码读 content_sha256 恒为空）。"""
        svc, repo, db = self._make_service(tmp_path)
        sha = "a" * 64
        items = [{
            "id": 7, "sha256": sha, "name": "f.txt", "size_bytes": 10,
            "device_id": "d", "created_at": 1,
        }]
        parsed, cursor = svc._process_page(items, 0)
        assert cursor == 7
        assert len(parsed) == 1
        assert parsed[0].content_sha256 == sha
        db.close()

    def test_skip_counter_gives_up_after_max(self, tmp_path):
        """连续失败达到上限后放弃并推进游标，避免一条坏数据永久卡住同步。"""
        svc, _, db = self._make_service(tmp_path)
        items = [{"id": 109, "sha256": "garbage"}]
        cursor = 100
        for _ in range(svc._MAX_PULL_SKIP - 1):
            _, cursor = svc._process_page(items, cursor)
            assert cursor == 100  # 未放弃前游标不动
        _, cursor = svc._process_page(items, cursor)
        assert cursor == 109  # 放弃后推进
        db.close()


# ---------------------------------------------------------------- 拉取落库带 space

class TestServerItemSpaceId:
    """修复前 _server_item_to_local 不写 space_id：团队条目以 NULL 落库，
    与 (space_id, content_hash) 去重不配套，重拉时整批重复插入。"""

    def _make_worker(self):
        from core.cloud_sync_service import _SyncWorker
        from core.cloud_api import CloudAPIClient
        w = _SyncWorker.__new__(_SyncWorker)
        w.cloud_api = CloudAPIClient("https://example.invalid")
        return w

    def test_server_space_id_wins(self):
        w = self._make_worker()
        item = w._server_item_to_local({
            "content_type": "text", "text_content": "hi",
            "content_hash": "h1", "space_id": "team-1",
        })
        assert item.space_id == "team-1"

    def test_fallback_to_space_key(self):
        w = self._make_worker()
        item = w._server_item_to_local({
            "content_type": "text", "text_content": "hi",
            "content_hash": "h2",
        }, space_key="team-2")
        assert item.space_id == "team-2"

    def test_personal_is_none(self):
        w = self._make_worker()
        item = w._server_item_to_local({
            "content_type": "text", "text_content": "hi",
            "content_hash": "h3",
        }, space_key=None)
        assert item.space_id is None


# ---------------------------------------------------------------- LIKE 转义

class TestLikeEscaping:
    def test_escape_like(self):
        from core.db.clipboard_query import ClipboardQuery
        assert ClipboardQuery._escape_like("100%") == "100!%"
        assert ClipboardQuery._escape_like("a_b") == "a!_b"
        assert ClipboardQuery._escape_like("a!b") == "a!!b"


# ---------------------------------------------------------------- i18n

class TestSetLanguageFallback:
    def test_legacy_alias_normalized(self):
        import i18n
        original = i18n.get_language()
        try:
            assert i18n.set_language("zh-CN") is True
            assert i18n.get_language() == "zh_CN"
            assert i18n.set_language("xx_XX") is False
            assert i18n.get_language() == "zh_CN"
        finally:
            i18n.set_language(original)
