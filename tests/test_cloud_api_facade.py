"""CloudAPIClient facade delegation 测试。

验证 facade 把 public 方法正确分发到 auth / sync / files / spaces 四个
domain client；token / _client 等关键属性能通过 facade 双向读写。
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.cloud_api import CloudAPIClient


def _make_client() -> CloudAPIClient:
    return CloudAPIClient("https://www.example.com")


def test_login_delegates_to_auth_client():
    client = _make_client()
    try:
        with patch.object(client.auth, "login", return_value={"ok": True}) as m:
            result = client.login("a@b", "pw")
            m.assert_called_once_with("a@b", "pw")
            assert result == {"ok": True}
    finally:
        client.close()


def test_upload_items_delegates_to_sync_client():
    client = _make_client()
    try:
        with patch.object(client.sync_client, "upload_items", return_value=[{"id": 1}]) as m:
            result = client.upload_items([{"text": "x"}])
            m.assert_called_once_with([{"text": "x"}])
            assert result == [{"id": 1}]
    finally:
        client.close()


def test_files_request_upload_delegates_to_files_client():
    client = _make_client()
    try:
        with patch.object(client.files, "files_request_upload", return_value={"upload_mode": "exists"}) as m:
            result = client.files_request_upload({"size": 10, "name": "a", "sha256": "x"})
            m.assert_called_once()
            assert result == {"upload_mode": "exists"}
    finally:
        client.close()


def test_list_spaces_delegates_to_spaces_client():
    client = _make_client()
    try:
        with patch.object(client.spaces, "list_spaces", return_value=[{"id": "s1"}]) as m:
            result = client.list_spaces()
            m.assert_called_once_with()
            assert result == [{"id": "s1"}]
    finally:
        client.close()


def test_set_tokens_writes_through_to_http():
    client = _make_client()
    try:
        client.set_tokens("acc-1", "ref-1")
        assert client._access_token == "acc-1"
        assert client._refresh_token_str == "ref-1"
        assert client.get_tokens() == ("acc-1", "ref-1")
        assert client.is_authenticated is True
    finally:
        client.close()


def test_base_url_property_forwards_to_http():
    client = _make_client()
    try:
        assert client.base_url == "https://www.example.com"
        assert client._base_url == "https://www.example.com"
    finally:
        client.close()


def test_underscore_client_attribute_readable_and_writable():
    """test_file_upload_flow 用 client._client = MockTransport() 替换 httpx 客户端,
    facade 必须保持该属性可读写。"""
    client = _make_client()
    try:
        original = client._client
        sentinel = object()
        client._client = sentinel  # type: ignore[assignment]
        assert client._client is sentinel
        client._client = original  # 还原以便 close
    finally:
        try:
            client.close()
        except Exception:
            pass


def test_patch_request_intercepts_delegated_calls():
    """关键回归:既有测试用 patch.object(c, "_request") mock 网络;
    经 facade 调用 domain client 后,_request 仍应是被拦截的 mock。"""
    client = _make_client()
    client.set_tokens("fake", "fake-r")
    try:
        with patch.object(
            client, "_request",
            return_value=type("R", (), {"json": lambda self: {"spaces": [{"id": "s1"}]}, "status_code": 200})(),
        ) as m:
            got = client.list_spaces()
            m.assert_called_once_with("GET", "/api/v1/spaces")
            assert got == [{"id": "s1"}]
    finally:
        client.close()
