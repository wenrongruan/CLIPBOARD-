"""SpacesClient v3.5 邀请相关方法的单元测试。

覆盖：
- invite_space_member 解析 added / invite_pending 两种返回值
- list_space_invitations / list_incoming_invitations 字典 vs 列表兼容
- revoke_space_invitation 调用正确 path
- accept_invitation 返回 dict
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.cloud_api import CloudAPIClient


def _make_client() -> CloudAPIClient:
    return CloudAPIClient("https://www.example.com")


def _resp(json_body):
    r = MagicMock()
    r.json.return_value = json_body
    r.status_code = 200
    return r


def test_invite_returns_added():
    client = _make_client()
    try:
        with patch.object(client, "_request", return_value=_resp({
            "success": True,
            "status": "added",
            "member": {"user_id": "u1", "email": "x@y.com", "role": "editor"},
            "invitation_url": "https://www.example.com/invite.html?token=abc",
        })) as m:
            data = client.invite_space_member(
                "11111111-2222-3333-4444-555555555555", "x@y.com", "editor",
            )
            assert data["status"] == "added"
            assert data["member"]["email"] == "x@y.com"
            assert data["invitation_url"].startswith("https://")
            call = m.call_args
            assert call.args[0] == "POST"
            assert "/members" in call.args[1]
            assert call.kwargs["json"] == {"email": "x@y.com", "role": "editor"}
    finally:
        client.close()


def test_invite_returns_pending():
    client = _make_client()
    try:
        with patch.object(client, "_request", return_value=_resp({
            "success": True,
            "status": "invite_pending",
            "email": "y@z.com",
            "token": "tok-1",
            "invitation_url": "https://www.example.com/invite.html?token=tok-1",
        })):
            data = client.invite_space_member(
                "11111111-2222-3333-4444-555555555555", "y@z.com", "viewer",
            )
            assert data["status"] == "invite_pending"
            assert data["invitation_url"]
            assert data["token"] == "tok-1"
    finally:
        client.close()


def test_list_space_invitations_extracts_array():
    client = _make_client()
    try:
        with patch.object(client, "_request", return_value=_resp({
            "success": True,
            "invitations": [{"token": "t1", "email": "a@b"}],
        })):
            rows = client.list_space_invitations("space-1")
            assert isinstance(rows, list) and len(rows) == 1
            assert rows[0]["email"] == "a@b"
    finally:
        client.close()


def test_list_space_invitations_accepts_raw_array():
    client = _make_client()
    try:
        # 后端如果直接返回数组也兼容
        with patch.object(client, "_request", return_value=_resp([{"token": "t2"}])):
            rows = client.list_space_invitations("space-1")
            assert rows == [{"token": "t2"}]
    finally:
        client.close()


def test_list_incoming_invitations():
    client = _make_client()
    try:
        with patch.object(client, "_request", return_value=_resp({
            "success": True,
            "invitations": [
                {"token": "tA", "space_name": "team-1", "role": "editor"},
            ],
        })) as m:
            rows = client.list_incoming_invitations()
            assert rows[0]["space_name"] == "team-1"
            call = m.call_args
            assert call.args[0] == "GET"
            assert call.args[1] == "/api/v1/invitations/incoming"
    finally:
        client.close()


def test_revoke_space_invitation_calls_delete():
    client = _make_client()
    try:
        with patch.object(client, "_request", return_value=_resp({"success": True})) as m:
            client.revoke_space_invitation("space-1", "tok-9")
            call = m.call_args
            assert call.args[0] == "DELETE"
            assert call.args[1].endswith("/invitations/tok-9")
    finally:
        client.close()


def test_accept_invitation_returns_space():
    client = _make_client()
    try:
        with patch.object(client, "_request", return_value=_resp({
            "success": True,
            "space": {"id": "s1", "name": "team-1", "role": "editor"},
        })) as m:
            data = client.accept_invitation("tok-X")
            assert data["space"]["id"] == "s1"
            call = m.call_args
            assert call.args[0] == "POST"
            assert call.args[1].endswith("/invitations/tok-X/accept")
    finally:
        client.close()


def test_facade_delegates_new_methods():
    """CloudAPIClient facade 应当暴露 4 个新 public 方法。"""
    client = _make_client()
    try:
        for name in (
            "list_space_invitations",
            "revoke_space_invitation",
            "list_incoming_invitations",
            "accept_invitation",
        ):
            assert hasattr(client, name), f"facade 缺少方法 {name}"
    finally:
        client.close()
