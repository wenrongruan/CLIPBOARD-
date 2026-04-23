"""CloudSyncService / CloudAPIClient v3.4 space & share-link 扩展测试。

覆盖点：
1. CloudAPIClient 新增的 space / share-link 方法调用正确的 URL / payload
2. CloudAPIClient.sync 的 space_id 参数正确透传
3. CloudSyncService._sync_one_space 对个人空间与团队空间的 URL 参数分别处理
4. push 时按 space_id 分组
5. 订阅降级后 team space 不 push（但 pull 仍允许）

所有测试均使用 mock，不依赖真实 Qt 事件循环或 HTTP 网络。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.cloud_api import CloudAPIClient, CloudAPIError  # noqa: E402


# ---------------------------------------------------------------------------
# CloudAPIClient — Space 接口
# ---------------------------------------------------------------------------


def _make_client() -> CloudAPIClient:
    """新建一个带假 token 的 client；_request 会被 mock，不会真发 HTTP。"""
    c = CloudAPIClient("https://www.example.com")
    c.set_tokens("fake-access", "fake-refresh")
    return c


def _fake_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


class TestCloudAPISpaceMethods(unittest.TestCase):
    """Space 相关 API 走正确的 method + path + body。"""

    def test_list_spaces_dict_wrapper(self):
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"spaces": [{"id": "s1"}]}),
        ) as m:
            got = c.list_spaces()
            m.assert_called_once_with("GET", "/api/v1/spaces")
            self.assertEqual(got, [{"id": "s1"}])

    def test_list_spaces_direct_list(self):
        c = _make_client()
        with patch.object(c, "_request", return_value=_fake_response([{"id": "s1"}])):
            self.assertEqual(c.list_spaces(), [{"id": "s1"}])

    def test_create_space_posts_name_and_type(self):
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"id": "new"}),
        ) as m:
            got = c.create_space("My Team", "team")
            m.assert_called_once_with(
                "POST", "/api/v1/spaces", json={"name": "My Team", "type": "team"},
            )
            self.assertEqual(got, {"id": "new"})

    def test_update_space_patches_name(self):
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"id": "s1", "name": "X"}),
        ) as m:
            c.update_space("s1", "X")
            m.assert_called_once_with("PATCH", "/api/v1/spaces/s1", json={"name": "X"})

    def test_delete_space(self):
        c = _make_client()
        with patch.object(c, "_request", return_value=_fake_response({})) as m:
            c.delete_space("s1")
            m.assert_called_once_with("DELETE", "/api/v1/spaces/s1")

    def test_list_space_members(self):
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"members": [{"id": "u1"}]}),
        ) as m:
            got = c.list_space_members("s1")
            m.assert_called_once_with("GET", "/api/v1/spaces/s1/members")
            self.assertEqual(got, [{"id": "u1"}])

    def test_invite_space_member(self):
        c = _make_client()
        with patch.object(c, "_request", return_value=_fake_response({"ok": True})) as m:
            c.invite_space_member("s1", "a@b.com", "editor")
            m.assert_called_once_with(
                "POST", "/api/v1/spaces/s1/members",
                json={"email": "a@b.com", "role": "editor"},
            )

    def test_remove_space_member(self):
        c = _make_client()
        with patch.object(c, "_request", return_value=_fake_response({})) as m:
            c.remove_space_member("s1", "u1")
            m.assert_called_once_with("DELETE", "/api/v1/spaces/s1/members/u1")

    def test_leave_space(self):
        c = _make_client()
        with patch.object(c, "_request", return_value=_fake_response({})) as m:
            c.leave_space("s1")
            m.assert_called_once_with("POST", "/api/v1/spaces/s1/leave")


class TestCloudAPIShareLinks(unittest.TestCase):
    def test_list_share_links(self):
        c = _make_client()
        with patch.object(
            c, "_request",
            return_value=_fake_response({"share_links": [{"id": "a"}]}),
        ) as m:
            self.assertEqual(c.list_share_links(), [{"id": "a"}])
            m.assert_called_once_with("GET", "/api/v1/share-links")

    def test_create_share_link_with_space(self):
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"id": "x", "token": "t"}),
        ) as m:
            c.create_share_link("s1", [1, 2, 3], 3600)
            m.assert_called_once_with(
                "POST", "/api/v1/share-links",
                json={"item_ids": [1, 2, 3], "expires_in_seconds": 3600, "space_id": "s1"},
            )

    def test_create_share_link_without_space(self):
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"id": "x"}),
        ) as m:
            c.create_share_link(None, [1], 60)
            # 个人空间不应在 payload 中带 space_id
            (_, kwargs), = [(call.args, call.kwargs) for call in [m.call_args]]
            self.assertNotIn("space_id", kwargs["json"])

    def test_revoke_share_link(self):
        c = _make_client()
        with patch.object(c, "_request", return_value=_fake_response({})) as m:
            c.revoke_share_link("sid")
            m.assert_called_once_with("DELETE", "/api/v1/share-links/sid")


# ---------------------------------------------------------------------------
# CloudAPIClient.sync / batch_create — space_id 参数
# ---------------------------------------------------------------------------


class TestCloudAPISyncSpaceId(unittest.TestCase):
    def test_sync_without_space_id_omits_param(self):
        """个人空间：sync() 不应在 URL 上附加 space_id。"""
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"items": [], "has_more": False}),
        ) as m:
            c.sync(since_id=0, device_id="dev-1")
            args, kwargs = m.call_args
            self.assertEqual(args[0], "GET")
            self.assertEqual(args[1], "/api/v1/clipboard/sync")
            self.assertNotIn("space_id", kwargs["params"])
            self.assertEqual(kwargs["params"]["device_id"], "dev-1")

    def test_sync_with_space_id_attaches_param(self):
        """团队空间：sync() 应把 space_id 作为 query param 传给后端。"""
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"items": [], "has_more": False}),
        ) as m:
            c.sync(since_id=10, device_id="dev-1", space_id="team-abc")
            _, kwargs = m.call_args
            self.assertEqual(kwargs["params"]["space_id"], "team-abc")
            self.assertEqual(kwargs["params"]["since_id"], 10)

    def test_batch_create_calls_clipboard_batch(self):
        c = _make_client()
        with patch.object(
            c, "_request", return_value=_fake_response({"items": [{"id": 1}]}),
        ) as m:
            items = [
                {"content_type": "text", "text_content": "hi", "space_id": "s1"},
            ]
            got = c.batch_create(items, device_id="dev-1")
            m.assert_called_once_with(
                "POST", "/api/v1/clipboard/batch", json={"items": items},
            )
            self.assertEqual(got, {"items": [{"id": 1}]})


# ---------------------------------------------------------------------------
# CloudSyncService — space 维度行为
#
# 这些测试用 MagicMock 替换 Qt worker/thread 的副作用，只验证纯 Python 逻辑。
# ---------------------------------------------------------------------------


class TestCloudSyncServiceSpaceRouting(unittest.TestCase):
    """CloudSyncService 对 space 的路由与分组逻辑。"""

    def _make_service(self, entitlement=None):
        # 延迟 import 避免模块级 Qt 初始化影响其他测试
        from core.cloud_sync_service import CloudSyncService, CloudSyncState

        # QApplication 必须在构造 QObject 之前存在
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        _ = app  # 保留引用，防止 GC

        repo = MagicMock()
        repo.get_meta.return_value = None
        repo.set_meta.return_value = None
        cloud_api = MagicMock()
        cloud_api.sync.return_value = {"items": [], "has_more": False}

        svc = CloudSyncService(repo, cloud_api, entitlement_service=entitlement)
        svc._transition(CloudSyncState.RUNNING)
        return svc, repo, cloud_api

    def test_get_spaces_to_sync_defaults_to_personal_only(self):
        svc, _, _ = self._make_service()
        spaces = svc._get_spaces_to_sync()
        self.assertEqual(spaces, [None])
        svc.stop()

    def test_known_spaces_includes_team(self):
        svc, _, _ = self._make_service()
        svc._known_spaces = [None, "team-1", "team-2"]
        spaces = svc._get_spaces_to_sync()
        self.assertEqual(spaces, [None, "team-1", "team-2"])
        svc.stop()

    def test_pull_triggers_for_each_space(self):
        """_pull_from_cloud 应对每个 space 发一次 _trigger_pull。"""
        svc, _, _ = self._make_service()
        svc._known_spaces = [None, "team-1"]
        svc._space_cursors = {None: 5, "team-1": 100}

        fired = []
        svc._trigger_pull = MagicMock()
        svc._trigger_pull.emit = lambda k, c: fired.append((k, c))

        svc._pull_from_cloud()
        self.assertEqual(fired, [(None, 5), ("team-1", 100)])
        svc.stop()

    def test_push_groups_by_space_id(self):
        """_push_to_cloud 应按 item.space_id 分组分别 push。"""
        svc, _, _ = self._make_service()
        svc._retry_queue.clear()

        # 构造三条 item：两条属于 space_a，一条个人
        def _mk(id_, space):
            m = MagicMock()
            m.space_id = space
            m.id = id_
            return m

        svc._pending_upload_queue.extend([_mk(1, None), _mk(2, "space_a"), _mk(3, "space_a")])

        fired = []
        svc._trigger_push = MagicMock()
        svc._trigger_push.emit = lambda k, items: fired.append((k, [it.id for it in items]))

        svc._push_to_cloud()
        # 两组：personal / space_a
        keys = sorted(f[0] or "" for f in fired)
        self.assertEqual(keys, ["", "space_a"])
        # space_a 两条 id=[2,3]
        for k, ids in fired:
            if k == "space_a":
                self.assertEqual(sorted(ids), [2, 3])
            else:
                self.assertEqual(ids, [1])
        svc.stop()

    def test_subscription_downgrade_blocks_team_push(self):
        """订阅降级后不应 push team space，但个人空间仍推送。"""
        class _FakeEnt:
            # mimic Entitlement.plan.value
            class plan:
                value = "basic"  # 非 super/ultimate
            status = "active"

        ent_svc = MagicMock()
        ent_svc.current.return_value = _FakeEnt()

        svc, _, _ = self._make_service(entitlement=ent_svc)
        svc._retry_queue.clear()

        def _mk(id_, space):
            m = MagicMock()
            m.space_id = space
            m.id = id_
            return m

        svc._pending_upload_queue.extend([_mk(1, None), _mk(2, "team-1")])

        fired = []
        svc._trigger_push = MagicMock()
        svc._trigger_push.emit = lambda k, items: fired.append((k, [it.id for it in items]))

        svc._push_to_cloud()

        # team-1 应被跳过，只剩个人空间
        keys = [f[0] for f in fired]
        self.assertIn(None, keys)
        self.assertNotIn("team-1", keys)
        svc.stop()

    def test_subscription_team_plan_allows_team_push(self):
        class _FakeEnt:
            class plan:
                value = "super"
            status = "active"

        ent_svc = MagicMock()
        ent_svc.current.return_value = _FakeEnt()

        svc, _, _ = self._make_service(entitlement=ent_svc)
        svc._retry_queue.clear()

        m_item = MagicMock()
        m_item.space_id = "team-1"
        m_item.id = 42
        svc._pending_upload_queue.append(m_item)

        fired = []
        svc._trigger_push = MagicMock()
        svc._trigger_push.emit = lambda k, items: fired.append((k, [it.id for it in items]))

        svc._push_to_cloud()
        self.assertEqual(fired, [("team-1", [42])])
        svc.stop()

    def test_pull_still_allowed_after_downgrade(self):
        """降级后 team space 仍应允许 pull（只影响 push）。"""
        class _FakeEnt:
            class plan:
                value = "basic"
            status = "active"

        ent_svc = MagicMock()
        ent_svc.current.return_value = _FakeEnt()

        svc, _, _ = self._make_service(entitlement=ent_svc)
        svc._known_spaces = [None, "team-1"]
        svc._space_cursors = {None: 0, "team-1": 0}

        fired = []
        svc._trigger_pull = MagicMock()
        svc._trigger_pull.emit = lambda k, c: fired.append((k, c))

        svc._pull_from_cloud()
        keys = [f[0] for f in fired]
        self.assertIn(None, keys)
        self.assertIn("team-1", keys)  # pull 不受降级影响
        svc.stop()


class TestCloudSyncServiceCursorPerSpace(unittest.TestCase):
    """游标按 space 分开持久化。"""

    def test_cursor_meta_key_personal(self):
        from core.cloud_sync_service import CloudSyncService
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication(sys.argv)
        repo = MagicMock()
        repo.get_meta.return_value = None
        svc = CloudSyncService(repo, MagicMock())
        self.assertEqual(svc._cursor_meta_key(None), "cloud_sync_cursor:personal")
        self.assertEqual(svc._cursor_meta_key("abc"), "cloud_sync_cursor:abc")
        svc.stop()

    def test_persist_writes_per_space_keys(self):
        from core.cloud_sync_service import CloudSyncService
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication(sys.argv)
        repo = MagicMock()
        repo.get_meta.return_value = None
        svc = CloudSyncService(repo, MagicMock())
        svc._space_cursors = {None: 10, "team-1": 99}
        svc._persist_cursor()

        keys_written = [
            call.args[0] for call in repo.set_meta.call_args_list
        ]
        self.assertIn("cloud_sync_cursor:personal", keys_written)
        self.assertIn("cloud_sync_cursor:team-1", keys_written)
        # 兼容老 key 也要写
        self.assertIn("cloud_last_sync_id", keys_written)
        svc.stop()


if __name__ == "__main__":
    unittest.main()
