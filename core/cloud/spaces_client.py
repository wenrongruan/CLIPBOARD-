"""SpacesClient：团队空间（space）+ 分享链接（share-link）接口。

v3.4 新增：团队协作空间。None=个人空间不走这些 API；
返回结构以服务端为准（见 website/api），客户端按 dict 透传给 SpaceService。
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

import httpx

from core.cloud.http import CloudAPIError, requires_plugin_permission

if TYPE_CHECKING:  # pragma: no cover
    from core.cloud_api import CloudAPIClient

logger = logging.getLogger(__name__)


class SpacesClient:
    """团队空间 + 分享链接。"""

    def __init__(self, facade: "CloudAPIClient"):
        self._facade = facade
        self._http = facade._http

    # ========== Space（团队空间）接口 ==========

    @requires_plugin_permission("network")
    def list_spaces(self) -> list:
        """列出当前用户参与的所有 space（个人空间不在此列表内）。"""
        response = self._facade._request("GET", "/api/v1/spaces")
        data = response.json()
        # 服务端可能返回 {"spaces": [...]} 或直接数组；两种都兼容
        if isinstance(data, dict):
            return data.get("spaces", data.get("items", []))
        return data if isinstance(data, list) else []

    @requires_plugin_permission("network")
    def create_space(self, name: str, type_: str) -> dict:
        """创建 space。type_ 常见值：'team' / 'personal'（后者一般由服务端隐式创建）。"""
        payload = {"name": name, "type": type_}
        response = self._facade._request("POST", "/api/v1/spaces", json=payload)
        return response.json()

    @requires_plugin_permission("network")
    def update_space(self, space_id: str, name: str) -> dict:
        """改名。服务端只允许 owner 操作。"""
        response = self._facade._request(
            "PATCH", f"/api/v1/spaces/{space_id}", json={"name": name},
        )
        return response.json()

    @requires_plugin_permission("network")
    def delete_space(self, space_id: str) -> None:
        """删除 space（owner 操作，连带清除成员关系）。"""
        self._facade._request("DELETE", f"/api/v1/spaces/{space_id}")

    @requires_plugin_permission("network")
    def list_space_members(self, space_id: str) -> list:
        """返回 space 成员列表。"""
        response = self._facade._request("GET", f"/api/v1/spaces/{space_id}/members")
        data = response.json()
        if isinstance(data, dict):
            return data.get("members", data.get("items", []))
        return data if isinstance(data, list) else []

    @requires_plugin_permission("network")
    def invite_space_member(self, space_id: str, email: str, role: str) -> dict:
        """邀请成员。role 常见：'owner' / 'editor' / 'viewer'，具体以服务端为准。"""
        payload = {"email": email, "role": role}
        response = self._facade._request(
            "POST", f"/api/v1/spaces/{space_id}/members", json=payload,
        )
        return response.json()

    @requires_plugin_permission("network")
    def remove_space_member(self, space_id: str, user_id: str) -> None:
        """将成员移出 space（owner 操作）。"""
        self._facade._request("DELETE", f"/api/v1/spaces/{space_id}/members/{user_id}")

    @requires_plugin_permission("network")
    def leave_space(self, space_id: str) -> None:
        """当前用户主动退出 space。owner 需先转让或删除。"""
        self._facade._request("POST", f"/api/v1/spaces/{space_id}/leave")

    # ========== Share Link（分享链接）接口 ==========

    @requires_plugin_permission("network")
    def list_share_links(self) -> list:
        """列出当前用户创建的分享链接。"""
        response = self._facade._request("GET", "/api/v1/share-links")
        data = response.json()
        if isinstance(data, dict):
            return data.get("share_links", data.get("items", []))
        return data if isinstance(data, list) else []

    @requires_plugin_permission("network")
    def create_share_link(
        self, space_id: Optional[str], item_ids: list, expires_in_seconds: int,
    ) -> dict:
        """创建分享链接。
        space_id=None 表示分享个人空间条目（与服务端约定一致时可省略字段）。
        """
        payload: dict = {
            "item_ids": list(item_ids),
            "expires_in_seconds": int(expires_in_seconds),
        }
        if space_id:
            payload["space_id"] = space_id
        response = self._facade._request("POST", "/api/v1/share-links", json=payload)
        return response.json()

    @requires_plugin_permission("network")
    def revoke_share_link(self, share_id: str) -> None:
        """吊销分享链接。"""
        self._facade._request("DELETE", f"/api/v1/share-links/{share_id}")

    def view_share_link(self, token: str) -> dict:
        """公开只读视图——不鉴权。
        故意不走 _request（它会强制加 Authorization）；直接用底层 httpx client。
        """
        try:
            resp = self._http._client.get(f"/api/v1/share-links/view/{token}")
        except httpx.TimeoutException:
            raise CloudAPIError("请求超时，请检查网络连接")
        except httpx.ConnectError:
            raise CloudAPIError("无法连接到云端服务器，请检查网络")
        except httpx.HTTPError as e:
            raise CloudAPIError(f"网络请求失败: {e}")
        if resp.status_code >= 400:
            try:
                error_data = resp.json() or {}
                msg = error_data.get("error", error_data.get("detail", f"服务器错误 ({resp.status_code})"))
            except Exception:
                error_data, msg = {}, f"服务器错误 ({resp.status_code})"
            raise CloudAPIError(msg, resp.status_code, error_data)
        return resp.json()
