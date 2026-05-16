"""SyncClient：剪贴板条目（item）级接口 + 图片上传下载。

包含：
- 条目批量上传 / 增量拉取 / 删除 / 收藏切换
- 单张图片上传到云端 / 取 presigned URL / 下载

domain client 通过 facade._request 走 token / 重试 / 错误映射统一逻辑。
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

import httpx

from core.cloud.http import CloudAPIError, requires_plugin_permission

if TYPE_CHECKING:  # pragma: no cover
    from core.cloud_api import CloudAPIClient

logger = logging.getLogger(__name__)


class SyncClient:
    """条目同步 + 图片接口。"""

    def __init__(self, facade: "CloudAPIClient"):
        self._facade = facade
        self._http = facade._http

    # ========== 剪贴板操作 ==========

    @requires_plugin_permission("network")
    def upload_items(self, items: list) -> list:
        """
        批量上传剪贴板条目，返回服务端创建的 items。
        items 为字典列表，每项包含: content_type, text_content, content_hash, preview,
        device_id, device_name, created_at, is_starred，可选 space_id / source_app / source_title。
        图片数据不在此接口上传（单独走 upload_image）。
        """
        response = self._facade._request("POST", "/api/v1/clipboard/batch", json={"items": items})
        return response.json().get("items", [])

    # 别名：与任务书统一的命名，兼容调用方；内部仍走 upload_items。
    @requires_plugin_permission("network")
    def batch_create(self, items: list, device_id: Optional[str] = None) -> dict:
        """批量创建云端条目。items 每条可选带 space_id / source_app / source_title。
        返回 {"items": [...]}；device_id 保留参数位但默认不追加到 payload，
        因服务端通过 Authorization / item.device_id 识别。"""
        response = self._facade._request("POST", "/api/v1/clipboard/batch", json={"items": items})
        return response.json()

    @requires_plugin_permission("network")
    def sync(self, since_id: int, device_id: str, space_id: Optional[str] = None) -> dict:
        """
        拉取新记录。
        space_id=None 表示个人空间（URL 不附加 space_id 参数）；
        传 space_id 则过滤该团队空间。
        返回 {"items": [...], "has_more": bool}
        """
        params = {"since_id": since_id, "device_id": device_id, "limit": 100}
        if space_id:
            params["space_id"] = space_id
        response = self._facade._request("GET", "/api/v1/clipboard/sync", params=params)
        return response.json()

    @requires_plugin_permission("network")
    def delete_item(self, item_id: int) -> bool:
        """删除云端条目"""
        try:
            self._facade._request("DELETE", f"/api/v1/clipboard/{item_id}")
            return True
        except CloudAPIError as e:
            logger.warning(f"删除云端条目失败 (id={item_id}): {e}")
            return False

    @requires_plugin_permission("network")
    def toggle_star(self, item_id: int) -> bool:
        """切换云端条目收藏状态"""
        try:
            self._facade._request("PUT", f"/api/v1/clipboard/{item_id}/star")
            return True
        except CloudAPIError as e:
            logger.warning(f"切换收藏状态失败 (id={item_id}): {e}")
            return False

    # ========== 图片接口 ==========

    @requires_plugin_permission("network")
    def upload_image(self, item_id: int, image_data: bytes) -> bool:
        """上传图片数据到云端"""
        try:
            self._facade._request(
                "POST",
                f"/api/v1/clipboard/{item_id}/image",
                content=image_data,
                headers={"Content-Type": "application/octet-stream"},
            )
            return True
        except CloudAPIError as e:
            logger.error(f"图片上传失败: {e}")
            return False

    @requires_plugin_permission("network")
    def get_image_url(self, item_id: int) -> str:
        """获取图片下载 URL（presigned URL）"""
        response = self._facade._request("GET", f"/api/v1/clipboard/{item_id}/image-url")
        return response.json().get("url", "")

    @requires_plugin_permission("network")
    def download_image(self, item_id: int) -> Optional[bytes]:
        """下载图片数据：先获取 presigned URL，再下载内容"""
        url = self.get_image_url(item_id)
        if not url:
            return None
        if not self._http._validate_storage_url(url, self._http._ALLOWED_DOWNLOAD_DOMAINS):
            return None
        try:
            resp = self._http._client.get(url, timeout=30.0)
            if resp.status_code == 200:
                return resp.content
        except httpx.HTTPError as e:
            logger.warning(f"图片下载失败 (item_id={item_id}): {e}")
        return None
