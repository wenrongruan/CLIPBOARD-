"""云�� API 客户端，封装所有与云端服务器的 HTTP 通信"""

import json
import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import Config

logger = logging.getLogger(__name__)

# 连接 8s / 读取 15s / 写入 15s / 连接池 15s —— 避免默认 30s 导致登录卡太久
_DEFAULT_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=15.0, pool=15.0)


class CloudAPIError(Exception):
    """云端 API 异常"""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class CloudAPIClient:
    """云端 API 客户端，处理认证和所有 HTTP 请求"""

    # 允许下载图片的域名白名单（presigned URL 可能来自 CDN/S3）
    _ALLOWED_DOWNLOAD_DOMAINS = {
        "www.jlike.com",
        "api.jlike.com",
        "s3.amazonaws.com",
        "s3.us-east-1.amazonaws.com",
        "storage.googleapis.com",
        "aliyuncs.com",
        "oss-cn-hangzhou.aliyuncs.com",
        "oss-cn-shanghai.aliyuncs.com",
        "oss-cn-beijing.aliyuncs.com",
        "oss-cn-shenzhen.aliyuncs.com",
    }

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._access_token: Optional[str] = None
        self._refresh_token_str: Optional[str] = None
        self._client = httpx.Client(base_url=self._base_url, timeout=_DEFAULT_TIMEOUT, verify=True)

    # ========== Token 管理 ==========

    def set_tokens(self, access_token: str, refresh_token: str):
        """从外部设置 tokens（如从配置文件加载）"""
        self._access_token = access_token if access_token else None
        self._refresh_token_str = refresh_token if refresh_token else None

    def get_tokens(self) -> tuple:
        """返回 (access_token, refresh_token)"""
        return self._access_token or "", self._refresh_token_str or ""

    @property
    def is_authenticated(self) -> bool:
        """是否已认证（至少有 access_token）"""
        return bool(self._access_token)

    def _save_tokens(self, access_token: str, refresh_token: str):
        """持久化 tokens 到配置和 auth.json"""
        self._access_token = access_token
        self._refresh_token_str = refresh_token
        t0 = time.time()
        Config.set_cloud_access_token(access_token)
        Config.set_cloud_refresh_token(refresh_token)
        self._update_auth_json(access_token, refresh_token)
        logger.debug(f"[Login] token 持久化总耗时 {time.time()-t0:.2f}s")

    def _update_auth_json(self, access_token: str, refresh_token: str):
        """同步更新 ~/.shared_clipboard/auth.json，供 chat_image_gen 等外部工具复用登录态。"""
        try:
            auth_dir = Path.home() / ".shared_clipboard"
            auth_dir.mkdir(parents=True, exist_ok=True)
            auth_file = auth_dir / "auth.json"
            data = {
                "api_base_url": self._base_url,
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
            auth_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.warning("更新 auth.json 失败", exc_info=True)

    # ========== 统一请求方法 ==========

    def _request(self, method: str, path: str, auth_required: bool = True, **kwargs) -> httpx.Response:
        """
        统一请求方法，自动处理认证和 token 刷新。

        - 自动在 header 中加 Authorization
        - 收到 401 时自动刷新 token 重试一次
        - 网络错误抛出 CloudAPIError
        """
        if auth_required:
            self._ensure_auth()

        headers = kwargs.pop("headers", {})
        if auth_required and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException:
            raise CloudAPIError("请求超时，请检查网络连接")
        except httpx.ConnectError:
            raise CloudAPIError("无法连接到云端服务器，请检查网络")
        except httpx.HTTPError as e:
            raise CloudAPIError(f"网络请求失败: {e}")

        # 401 自动刷新 token 重试
        if response.status_code == 401 and auth_required and self._refresh_token_str:
            if self.refresh_token():
                headers["Authorization"] = f"Bearer {self._access_token}"
                try:
                    response = self._client.request(method, path, headers=headers, **kwargs)
                except httpx.TimeoutException:
                    raise CloudAPIError("请求超时，请检查网络连接")
                except httpx.ConnectError:
                    raise CloudAPIError("无法连接到云端服务器，请检查网络")
                except httpx.HTTPError as e:
                    raise CloudAPIError(f"网络请求失败: {e}")

        # 处理错误响应
        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("error", error_data.get("detail", f"服务器错误 ({response.status_code})"))
            except Exception:
                body_preview = response.text[:200] if response.text else ""
                message = f"服务器错误 ({response.status_code})"
                if body_preview:
                    logger.debug(f"错误响应体: {body_preview}")
            raise CloudAPIError(message, response.status_code)

        return response

    def _ensure_auth(self):
        """检查 token 有效性"""
        if not self._access_token:
            raise CloudAPIError("未登录，请先登录云端账户", 401)

    # ========== 认证接口 ==========

    def _handle_auth_response(self, data: dict, email: str):
        """从认证响应中提取并保存 tokens"""
        access = data.get("token") or data.get("access_token", "")
        refresh = data.get("refresh_token", "")
        if access and refresh:
            self._save_tokens(access, refresh)
            Config.set_cloud_user_email(email)
        else:
            logger.warning(f"认证响应中缺少 token: access={bool(access)}, refresh={bool(refresh)}")
            raise CloudAPIError("登录成功但服务端未返回有效 token，请重试")

    def register(self, email: str, password: str, display_name: str = None) -> dict:
        """注册新用户，返回用户信息和 tokens"""
        payload = {"email": email, "password": password}
        if display_name:
            payload["name"] = display_name

        response = self._request("POST", "/api/v1/auth/register", auth_required=False, json=payload)
        data = response.json()
        self._handle_auth_response(data, email)
        return data

    def login(self, email: str, password: str) -> dict:
        """登录，返回 tokens"""
        payload = {"email": email, "password": password}
        response = self._request("POST", "/api/v1/auth/login", auth_required=False, json=payload)
        data = response.json()
        self._handle_auth_response(data, email)
        return data

    def refresh_token(self) -> bool:
        """使用 refresh_token 刷新 access_token，成功返回 True。
        仅在服务端明确返回 401/403 时才清除本地 token；网络错误保留 token 以便下次重试。
        """
        if not self._refresh_token_str:
            return False

        try:
            response = self._client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": self._refresh_token_str},
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            logger.warning(f"Token 刷新网络失败（保留本地 token 待下次重试）: {e}")
            return False

        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError as e:
                logger.warning(f"Token 刷新响应解析失败: {e}")
                return False
            self._save_tokens(
                data.get("token") or data.get("access_token", self._access_token),
                data.get("refresh_token", self._refresh_token_str),
            )
            logger.info("Token 刷新成功")
            return True

        logger.warning(f"Token 刷新失败: {response.status_code}")
        if response.status_code in (401, 403):
            # refresh_token 已过期/失效，清除本地登录态使 UI 反映真实状态
            self._access_token = None
            self._refresh_token_str = None
            Config.set_cloud_access_token("")
            Config.set_cloud_refresh_token("")
            self._update_auth_json("", "")
            logger.info("Refresh token 已过期，已清除本地登录态")
        return False

    def logout(self):
        """退出登录，清除本地 tokens"""
        try:
            self._request("POST", "/api/v1/auth/logout", auth_required=True)
        except CloudAPIError as e:
            logger.warning(f"服务端 logout 失败（仍清除本地 token）: {e}")

        self._access_token = None
        self._refresh_token_str = None
        Config.set_cloud_access_token("")
        Config.set_cloud_refresh_token("")
        Config.set_cloud_user_email("")
        self._update_auth_json("", "")
        logger.info("已退出云端登录")

    # ========== 剪贴板操作 ==========

    def upload_items(self, items: list) -> list:
        """
        批量上传剪贴板条目，返回服务端创建的 items。
        items 为字典列表，每项包含: content_type, text_content, content_hash, preview, device_id, device_name, created_at, is_starred
        图片数据不在此接口上传（单独走 upload_image）。
        """
        response = self._request("POST", "/api/v1/clipboard/batch", json={"items": items})
        return response.json().get("items", [])

    def sync(self, since_id: int, device_id: str) -> dict:
        """
        拉取新记录。
        返回 {"items": [...], "has_more": bool}
        """
        params = {"since_id": since_id, "device_id": device_id, "limit": 100}
        response = self._request("GET", "/api/v1/clipboard/sync", params=params)
        return response.json()

    def delete_item(self, item_id: int) -> bool:
        """删除云端条目"""
        try:
            self._request("DELETE", f"/api/v1/clipboard/{item_id}")
            return True
        except CloudAPIError as e:
            logger.warning(f"删除云端条目失败 (id={item_id}): {e}")
            return False

    def toggle_star(self, item_id: int) -> bool:
        """切换云端条目收藏状态"""
        try:
            self._request("PUT", f"/api/v1/clipboard/{item_id}/star")
            return True
        except CloudAPIError as e:
            logger.warning(f"切换收藏状态失败 (id={item_id}): {e}")
            return False

    # ========== 图片接口 ==========

    def upload_image(self, item_id: int, image_data: bytes) -> bool:
        """上传图片数据到云端"""
        try:
            self._request(
                "POST",
                f"/api/v1/clipboard/{item_id}/image",
                content=image_data,
                headers={"Content-Type": "application/octet-stream"},
            )
            return True
        except CloudAPIError as e:
            logger.error(f"图片上传失败: {e}")
            return False

    def get_image_url(self, item_id: int) -> str:
        """获取图片下载 URL（presigned URL）"""
        response = self._request("GET", f"/api/v1/clipboard/{item_id}/image-url")
        return response.json().get("url", "")

    def download_image(self, item_id: int) -> Optional[bytes]:
        """下载图片数据：先获取 presigned URL，再下载���容"""
        url = self.get_image_url(item_id)
        if not url:
            return None
        # 校验下载 URL 的安全性，防止 SSRF
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            logger.warning(f"不安全的图片 URL scheme: {url}")
            return None
        hostname = parsed.hostname or ""
        # 允许 API 同域 + 已知 CDN/存储域名
        api_host = urlparse(self._base_url).hostname or ""
        allowed = self._ALLOWED_DOWNLOAD_DOMAINS | {api_host}
        if not any(hostname == d or hostname.endswith(f".{d}") for d in allowed):
            logger.warning(f"不允许的图片下载域名: {hostname}")
            return None
        try:
            resp = self._client.get(url, timeout=30.0)
            if resp.status_code == 200:
                return resp.content
        except httpx.HTTPError as e:
            logger.warning(f"图片下载失败 (item_id={item_id}): {e}")
        return None

    # ========== 订阅接口 ==========

    def get_subscription(self) -> dict:
        """获取当前用户的订阅信息"""
        response = self._request("GET", "/api/v1/subscription")
        return response.json()

    def create_checkout(self, plan: str) -> str:
        """创建支付 checkout，返回 checkout URL"""
        response = self._request("POST", "/api/v1/subscription/checkout", json={"plan": plan})
        return response.json().get("checkout_url", "")

    # ========== 积分/扣点接口 ==========

    def get_balance(self) -> dict:
        """获取当前用户的积分余额
        返回: {"balance": float, "frozen": float}
        """
        response = self._request("GET", "/api/v1/credits")
        return response.json()

    def deduct_credits(self, amount: float, reason: str, plugin_id: str = "", task_uuid: str = "") -> dict:
        """扣除积分
        返回: {"success": bool, "remaining": float, "transaction_id": str}
        """
        payload = {
            "amount": amount,
            "reason": reason,
            "plugin_id": plugin_id,
            "task_uuid": task_uuid,
        }
        response = self._request("POST", "/api/v1/credits/deduct", json=payload)
        return response.json()

    def check_credits(self, required: float) -> bool:
        """检查积分是否足够"""
        try:
            data = self.get_balance()
            available = data.get("balance", 0) - data.get("frozen", 0)
            return available >= required
        except CloudAPIError:
            return False

    # ========== AI 生图接口 ==========

    def ai_generate(self, provider: str, model: str, prompt: str, task_uuid: str,
                    size: str = "2K", aspect_ratio: str = "1:1", n: int = 1,
                    **extra) -> dict:
        """提交 AI 生图任务。Gemini 同步返回结果，万相返回 task_uuid 待轮询。"""
        payload = {
            "provider": provider, "model": model, "prompt": prompt,
            "task_uuid": task_uuid, "images": [], "size": size,
            "aspect_ratio": aspect_ratio, "n": n,
        }
        payload.update(extra)
        response = self._request("POST", "/api/v1/ai/generate", json=payload)
        return response.json()

    def ai_poll_task(self, task_uuid: str) -> dict:
        """查询 AI 生图任务状态（万相异步轮询用）。"""
        response = self._request("GET", f"/api/v1/ai/task/{task_uuid}")
        return response.json()

    def ai_cancel_task(self, task_uuid: str) -> dict:
        """取消 AI 生图任务。"""
        response = self._request("POST", f"/api/v1/ai/task/{task_uuid}/cancel")
        return response.json()

    # ========== 设备接口 ==========

    def register_device(self, device_id: str, device_name: str, platform: str) -> bool:
        """注册当前设备"""
        try:
            self._request(
                "POST",
                "/api/v1/devices",
                json={"device_id": device_id, "device_name": device_name, "platform": platform},
            )
            return True
        except CloudAPIError as e:
            logger.error(f"设备注册失败: {e}")
            return False

    def close(self):
        """关闭 HTTP 客户端"""
        try:
            self._client.close()
        except Exception:
            pass


# ========== 全局单例 ==========
# 为避免 main/MainWindow/SettingsDialog 各自 new CloudAPIClient 导致 token 不同步，
# 所有 UI/服务层都应通过 get_cloud_client() 访问。
_cloud_client_singleton: Optional[CloudAPIClient] = None


def get_cloud_client(create_if_missing: bool = True) -> Optional[CloudAPIClient]:
    """返回全局唯一的 CloudAPIClient，按需从已保存 token 恢复。
    create_if_missing=False 时仅查，不会自动创建空壳客户端。
    """
    global _cloud_client_singleton
    if _cloud_client_singleton is not None:
        return _cloud_client_singleton
    if not create_if_missing:
        return None
    access = Config.get_cloud_access_token()
    # 始终创建实例（即使未登录也需要提供登录表单用）
    client = CloudAPIClient(Config.get_cloud_api_url())
    if access:
        client.set_tokens(access, Config.get_cloud_refresh_token())
    _cloud_client_singleton = client
    return client


def reset_cloud_client():
    """关闭并清除单例（仅测试或完全退出时使用）"""
    global _cloud_client_singleton
    if _cloud_client_singleton is not None:
        _cloud_client_singleton.close()
        _cloud_client_singleton = None
