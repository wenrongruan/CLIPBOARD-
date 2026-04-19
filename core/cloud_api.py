"""云�� API 客户端，封装所有与云端服务器的 HTTP 通信"""

import getpass
import json
import logging
import os
import platform
import stat
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import (
    settings,
    update_settings,
    get_cloud_access_token,
    set_cloud_access_token,
    get_cloud_refresh_token,
    set_cloud_refresh_token,
)

logger = logging.getLogger(__name__)

# 连接 8s / 读取 15s / 写入 15s / 连接池 15s —— 避免默认 30s 导致登录卡太久
_DEFAULT_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=15.0, pool=15.0)


class CloudAPIError(Exception):
    """云端 API 异常。

    payload 保存服务端返回的原始 JSON（>=400 场景下），供调用方读取除 error
    外的字段——例如 `/credits/deduct` 返回 402 时 body 里还带 remaining/required。
    """

    def __init__(self, message: str, status_code: int = 0, payload: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def requires_plugin_permission(name: str):
    """标注该 API 方法需要插件声明某个 manifest 权限。

    Why: 权限白名单原本硬编码在 PluginManager 的 frozenset 里，新增方法要
    同步修改两处；改为把权限作为属性挂在方法对象上，PluginCloudClientProxy
    读 `func._plugin_permission` 就能直接判断，避免清单漂移。
    """

    def decorator(func):
        func._plugin_permission = name
        return func

    return decorator


class CreditCheckStatus(Enum):
    """积分检查结果状态"""
    SUFFICIENT = "sufficient"         # 余额充足
    INSUFFICIENT = "insufficient"     # 余额不足
    QUERY_FAILED = "query_failed"     # 查询失败（网络/认证等）


@dataclass
class CreditCheckResult:
    """积分检查结果（三态）

    - status: SUFFICIENT / INSUFFICIENT / QUERY_FAILED
    - available: 查询成功时的可用余额；查询失败为 0
    - reason: 查询失败时的原因描述（网络错误、认证失败等）
    - status_code: 查询失败时的 HTTP 状态码（0 表示网络层错误）
    """
    status: CreditCheckStatus
    available: float = 0.0
    reason: str = ""
    status_code: int = 0

    @property
    def ok(self) -> bool:
        """兼容旧布尔契约：仅 SUFFICIENT 为 True"""
        return self.status == CreditCheckStatus.SUFFICIENT

    def __bool__(self) -> bool:
        return self.ok


class CloudAPIClient:
    """云端 API 客户端，处理认证和所有 HTTP 请求"""

    # 允许下载图片的域名白名单（presigned URL 可能来自 CDN/S3）
    # Why: aliyuncs.com 是阿里云公共父域，任何租户可注册子域，作为父域匹配会被绕过。
    # 此处只保留精确 region 级 OSS 域名；若需自有 bucket 另行通过子域匹配（bucket.region.aliyuncs.com）。
    _ALLOWED_DOWNLOAD_DOMAINS = {
        "www.jlike.com",
        "s3.amazonaws.com",
        "s3.us-east-1.amazonaws.com",
        "storage.googleapis.com",
        "oss-cn-hangzhou.aliyuncs.com",
        "oss-cn-shanghai.aliyuncs.com",
        "oss-cn-beijing.aliyuncs.com",
        "oss-cn-shenzhen.aliyuncs.com",
    }
    # 文件上传只允许 OSS（严禁走应用服务器中转）；与下载白名单等价，但语义独立。
    _ALLOWED_UPLOAD_DOMAINS = {
        "s3.amazonaws.com",
        "s3.us-east-1.amazonaws.com",
        "storage.googleapis.com",
        "oss-cn-hangzhou.aliyuncs.com",
        "oss-cn-shanghai.aliyuncs.com",
        "oss-cn-beijing.aliyuncs.com",
        "oss-cn-shenzhen.aliyuncs.com",
    }

    # 文件单体硬上限（客户端先拦截一次；服务端会二次校验）
    FILE_SIZE_HARD_LIMIT = 1 << 30  # 1 GB
    # 分片阈值：超过 32 MB 走 multipart
    FILE_MULTIPART_THRESHOLD = 32 * (1 << 20)
    FILE_PART_SIZE = 16 * (1 << 20)

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._access_token: Optional[str] = None
        self._refresh_token_str: Optional[str] = None
        self._client = httpx.Client(base_url=self._base_url, timeout=_DEFAULT_TIMEOUT, verify=True)

    @property
    def base_url(self) -> str:
        """公开的只读 base_url，供插件通过 CloudClientProxy 读取。
        Why: 插件代理禁止访问下划线开头的私有属性（_base_url 会抛 PermissionError），
        因此需要显式公开 getter。
        """
        return self._base_url

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
        set_cloud_access_token(access_token)
        set_cloud_refresh_token(refresh_token)
        self._update_auth_json(access_token, refresh_token)
        logger.debug(f"[Login] token 持久化总耗时 {time.time()-t0:.2f}s")

    def _update_auth_json(self, access_token: str, refresh_token: str):
        """同步更新 ~/.shared_clipboard/auth.json，供 chat_image_gen 等外部工具复用登录态。

        auth.json 含有有效的 access/refresh token，同机其他用户账号或进程读取即可
        直接以当前用户身份访问云端 API。写入流程：
          1. 先 atomic-write 到 .tmp，再 os.replace 到最终文件（避免写入中途被读到半文件）
          2. 非 Windows 平台显式 chmod 0600，确保文件仅属主可读写
          3. Windows 平台通过 icacls 移除继承，仅授予当前用户 Full Control；
             ACL 失败不阻断登录流程（仅记日志），默认 NTFS 继承作为兜底。
        """
        try:
            auth_dir = Path.home() / ".shared_clipboard"
            auth_dir.mkdir(parents=True, exist_ok=True)
            auth_file = auth_dir / "auth.json"
            tmp_file = auth_dir / "auth.json.tmp"
            data = {
                "api_base_url": self._base_url,
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
            serialized = json.dumps(data, ensure_ascii=False, indent=2)

            # 非 Windows 平台：先以 0600 权限创建 tmp 文件再写入
            if platform.system() != "Windows":
                flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                fd = os.open(str(tmp_file), flags, 0o600)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(serialized)
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
                try:
                    os.chmod(tmp_file, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
            else:
                tmp_file.write_text(serialized, encoding="utf-8")

            os.replace(tmp_file, auth_file)

            if platform.system() != "Windows":
                try:
                    os.chmod(auth_file, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
            else:
                # Windows：用 icacls 移除继承并仅授予当前用户 Full Control。
                # Why: NTFS 默认 ACL 在某些组策略/共享目录下可能被覆盖，显式收紧更稳。
                # 失败不阻断登录（仅降级日志），auth.json 已写入本地默认 ACL 兜底。
                self._apply_windows_acl(auth_file)
        except Exception:
            logger.warning("更新 auth.json 失败", exc_info=True)

    @staticmethod
    def _apply_windows_acl(path: Path) -> None:
        """Windows 下对指定文件应用收紧的 ACL：移除继承，仅当前用户完全控制。"""
        try:
            user = getpass.getuser()
            if not user:
                logger.debug("icacls: 无法获取当前用户名，跳过 ACL 收紧")
                return
            # /inheritance:r 移除继承，/grant:r 替换（非追加）user:F 完全控制
            result = subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{user}:F",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                logger.debug(
                    "icacls 收紧 ACL 失败 rc=%s stderr=%s",
                    result.returncode,
                    (result.stderr or "").strip()[:200],
                )
        except FileNotFoundError:
            logger.debug("icacls 不可用（非 Windows 或 PATH 未包含），跳过 ACL 收紧")
        except subprocess.TimeoutExpired:
            logger.debug("icacls 执行超时，跳过 ACL 收紧")
        except Exception as e:
            logger.debug("icacls 执行异常，跳过 ACL 收紧: %s", e)

    # ========== 统一请求方法 ==========

    def _request(
        self,
        method: str,
        path: str,
        auth_required: bool = True,
        **kwargs,
    ) -> httpx.Response:
        """
        统一请求方法，自动处理认证和 token 刷新。

        - 自动在 header 中加 Authorization
        - 收到 401 时自动刷新 token 重试一次
        - 网络/>=400 错误抛出 CloudAPIError；调用方需关心具体状态码时
          用 `except CloudAPIError as e: if e.status_code == XXX`。
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
            error_data: dict = {}
            try:
                error_data = response.json() or {}
                message = error_data.get("error", error_data.get("detail", f"服务器错误 ({response.status_code})"))
            except Exception:
                body_preview = response.text[:200] if response.text else ""
                message = f"服务器错误 ({response.status_code})"
                if body_preview:
                    logger.debug(f"错误响应体: {body_preview}")
            raise CloudAPIError(message, response.status_code, error_data)

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
            update_settings(cloud_user_email=email)
        else:
            logger.warning(f"认证响应中缺少 token: access={bool(access)}, refresh={bool(refresh)}")
            raise CloudAPIError("登录成功但服务端未返回有效 token，请重试")

    @requires_plugin_permission("network")
    def register(self, email: str, password: str, display_name: str = None) -> dict:
        """注册新用户，返回用户信息和 tokens"""
        payload = {"email": email, "password": password}
        if display_name:
            payload["name"] = display_name

        response = self._request("POST", "/api/v1/auth/register", auth_required=False, json=payload)
        data = response.json()
        self._handle_auth_response(data, email)
        return data

    @requires_plugin_permission("network")
    def login(self, email: str, password: str) -> dict:
        """登录，返回 tokens"""
        payload = {"email": email, "password": password}
        response = self._request("POST", "/api/v1/auth/login", auth_required=False, json=payload)
        data = response.json()
        self._handle_auth_response(data, email)
        return data

    @requires_plugin_permission("network")
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
            set_cloud_access_token("")
            set_cloud_refresh_token("")
            self._update_auth_json("", "")
            logger.info("Refresh token 已过期，已清除本地登录态")
        return False

    @requires_plugin_permission("network")
    def logout(self):
        """退出登录，清除本地 tokens"""
        try:
            self._request("POST", "/api/v1/auth/logout", auth_required=True)
        except CloudAPIError as e:
            logger.warning(f"服务端 logout 失败（仍清除本地 token）: {e}")

        self._access_token = None
        self._refresh_token_str = None
        set_cloud_access_token("")
        set_cloud_refresh_token("")
        update_settings(cloud_user_email="")
        self._update_auth_json("", "")
        logger.info("已退出云端登录")

    # ========== 剪贴板操作 ==========

    @requires_plugin_permission("network")
    def upload_items(self, items: list) -> list:
        """
        批量上传剪贴板条目，返回服务端创建的 items。
        items 为字典列表，每项包含: content_type, text_content, content_hash, preview, device_id, device_name, created_at, is_starred
        图片数据不在此接口上传（单独走 upload_image）。
        """
        response = self._request("POST", "/api/v1/clipboard/batch", json={"items": items})
        return response.json().get("items", [])

    @requires_plugin_permission("network")
    def sync(self, since_id: int, device_id: str) -> dict:
        """
        拉取新记录。
        返回 {"items": [...], "has_more": bool}
        """
        params = {"since_id": since_id, "device_id": device_id, "limit": 100}
        response = self._request("GET", "/api/v1/clipboard/sync", params=params)
        return response.json()

    @requires_plugin_permission("network")
    def delete_item(self, item_id: int) -> bool:
        """删除云端条目"""
        try:
            self._request("DELETE", f"/api/v1/clipboard/{item_id}")
            return True
        except CloudAPIError as e:
            logger.warning(f"删除云端条目失败 (id={item_id}): {e}")
            return False

    @requires_plugin_permission("network")
    def toggle_star(self, item_id: int) -> bool:
        """切换云端条目收藏状态"""
        try:
            self._request("PUT", f"/api/v1/clipboard/{item_id}/star")
            return True
        except CloudAPIError as e:
            logger.warning(f"切换收藏状态失败 (id={item_id}): {e}")
            return False

    # ========== 图片接口 ==========

    @requires_plugin_permission("network")
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

    @requires_plugin_permission("network")
    def get_image_url(self, item_id: int) -> str:
        """获取图片下载 URL（presigned URL）"""
        response = self._request("GET", f"/api/v1/clipboard/{item_id}/image-url")
        return response.json().get("url", "")

    @requires_plugin_permission("network")
    def download_image(self, item_id: int) -> Optional[bytes]:
        """下载图片数据：先获取 presigned URL，再下载内容"""
        url = self.get_image_url(item_id)
        if not url:
            return None
        if not self._validate_storage_url(url, self._ALLOWED_DOWNLOAD_DOMAINS):
            return None
        try:
            resp = self._client.get(url, timeout=30.0)
            if resp.status_code == 200:
                return resp.content
        except httpx.HTTPError as e:
            logger.warning(f"图片下载失败 (item_id={item_id}): {e}")
        return None

    # ========== 文件接口（付费用户专用，仅走 OSS） ==========

    def _validate_storage_url(self, url: str, domains: set) -> bool:
        """校验 presigned URL 的 scheme 与域名；与 get_image_url 一致但可自定义白名单。"""
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            logger.warning(f"不安全的存储 URL scheme: {url}")
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        api_host = (urlparse(self._base_url).hostname or "").lower()
        allowed = domains | {api_host}
        return any(host == d or host.endswith(f".{d}") for d in allowed)

    def files_list(self, since_id: int, device_id: str, limit: int = 100) -> dict:
        """增量拉取文件列表，返回 {items: [...], has_more: bool}。"""
        response = self._request(
            "GET", "/api/v1/files/sync",
            params={"since_id": since_id, "device_id": device_id, "limit": limit},
        )
        return response.json()

    def files_get_quota(self) -> dict:
        """返回 {plan, quota_bytes, used_bytes, max_file_size_bytes}"""
        response = self._request("GET", "/api/v1/files/quota")
        return response.json()

    def files_request_upload(self, meta: dict) -> dict:
        """请求上传位点。服务端按 size 决定单段 / multipart，并返回 presigned URL（仅 OSS）。
        meta 必须包含 name / size / sha256；可选 mime_type / device_id / device_name。
        返回示例（单段）:
          {"file_id": 123, "cloud_id": 123, "upload_mode": "single",
           "upload_url": "...", "expires_at": 1712345678}
        multipart:
          {"file_id": 123, "cloud_id": 123, "upload_mode": "multipart",
           "parts": [{"part_number": 1, "url": "..."}, ...],
           "complete_url": "...", "expires_at": ...}
        """
        if int(meta.get("size", 0)) > self.FILE_SIZE_HARD_LIMIT:
            raise CloudAPIError("单文件不能超过 1 GB", 413)
        response = self._request("POST", "/api/v1/files/upload", json=meta)
        return response.json()

    def files_complete_upload(self, cloud_id: int, etags: list) -> dict:
        """multipart 完成：上报每一段 etag，服务端确认并落 meta。"""
        response = self._request(
            "POST", f"/api/v1/files/{cloud_id}/complete", json={"parts": etags},
        )
        return response.json()

    def files_get_download_url(self, cloud_id: int) -> str:
        response = self._request("GET", f"/api/v1/files/{cloud_id}/download-url")
        return response.json().get("url", "")

    def files_update_meta(self, cloud_id: int, patch: dict) -> dict:
        response = self._request("PATCH", f"/api/v1/files/{cloud_id}", json=patch)
        return response.json()

    def files_delete(self, cloud_id: int) -> bool:
        try:
            self._request("DELETE", f"/api/v1/files/{cloud_id}")
            return True
        except CloudAPIError as e:
            logger.warning(f"删除云端文件失败 (cloud_id={cloud_id}): {e}")
            return False

    def upload_file_to_url(
        self,
        url: str,
        file_path: str,
        part_offset: int = 0,
        part_size: Optional[int] = None,
        progress_cb=None,
    ) -> str:
        """向 OSS presigned URL 发 PUT（支持分片）。

        - part_offset / part_size: multipart 切片位置；None 表示整个文件
        - progress_cb(sent_in_this_call, total_in_this_call): 每约 200 ms 或 1 MB 调用一次
        返回响应 header 的 ETag（去引号）；非 2xx 抛 CloudAPIError。
        """
        if not self._validate_storage_url(url, self._ALLOWED_UPLOAD_DOMAINS):
            raise CloudAPIError(f"上传域名被拒绝: {url}", 0)

        size = os.path.getsize(file_path) if part_size is None else int(part_size)

        import time as _time
        sent = 0
        last_emit_ts = 0.0
        last_emit_sent = 0

        def _iter():
            nonlocal sent, last_emit_ts, last_emit_sent
            remaining = size
            chunk_bytes = 1 << 20  # 1 MB
            with open(file_path, "rb") as fp:
                if part_offset:
                    fp.seek(int(part_offset))
                while remaining > 0:
                    want = min(chunk_bytes, remaining)
                    data = fp.read(want)
                    if not data:
                        break
                    remaining -= len(data)
                    sent += len(data)
                    now = _time.monotonic()
                    if progress_cb is not None and (
                        now - last_emit_ts >= 0.2 or sent - last_emit_sent >= chunk_bytes
                    ):
                        try:
                            progress_cb(sent, size)
                        except Exception:
                            pass
                        last_emit_ts = now
                        last_emit_sent = sent
                    yield data

        try:
            resp = self._client.put(
                url,
                content=_iter(),
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                },
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=300.0, pool=300.0),
            )
        except httpx.HTTPError as e:
            raise CloudAPIError(f"OSS 上传失败: {e}", 0)

        if resp.status_code >= 400:
            raise CloudAPIError(
                f"OSS 上传返回 {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )
        # 发完最后一次进度，确保 UI 走到 100%
        if progress_cb is not None:
            try:
                progress_cb(size, size)
            except Exception:
                pass
        etag = resp.headers.get("ETag") or resp.headers.get("etag") or ""
        return etag.strip('"')

    def download_file_to(
        self, url: str, dest_path: str, progress_cb=None,
    ) -> int:
        """从 presigned URL 流式下载到本地文件；返回字节数。"""
        if not self._validate_storage_url(url, self._ALLOWED_DOWNLOAD_DOMAINS):
            raise CloudAPIError(f"下载域名被拒绝: {url}", 0)

        import time as _time
        total_bytes = 0
        expected = 0
        last_emit_ts = 0.0
        last_emit = 0
        tmp_path = dest_path + ".part"
        try:
            with self._client.stream(
                "GET", url,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=300.0),
            ) as resp:
                if resp.status_code >= 400:
                    raise CloudAPIError(
                        f"OSS 下载返回 {resp.status_code}", resp.status_code,
                    )
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    expected = int(cl)
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(1 << 20):
                        if not chunk:
                            continue
                        f.write(chunk)
                        total_bytes += len(chunk)
                        now = _time.monotonic()
                        if progress_cb is not None and (
                            now - last_emit_ts >= 0.2
                            or total_bytes - last_emit >= (1 << 20)
                        ):
                            try:
                                progress_cb(total_bytes, expected or total_bytes)
                            except Exception:
                                pass
                            last_emit_ts = now
                            last_emit = total_bytes
            os.replace(tmp_path, dest_path)
        except httpx.HTTPError as e:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise CloudAPIError(f"OSS 下载网络错误: {e}", 0)
        if progress_cb is not None:
            try:
                progress_cb(total_bytes, expected or total_bytes)
            except Exception:
                pass
        return total_bytes

    # ========== 订阅接口 ==========

    @requires_plugin_permission("credits")
    def get_subscription(self) -> dict:
        """获取当前用户的订阅信息"""
        response = self._request("GET", "/api/v1/subscription")
        return response.json()

    @requires_plugin_permission("credits")
    def create_checkout(self, plan: str) -> str:
        """创建支付 checkout，返回 checkout URL"""
        response = self._request("POST", "/api/v1/subscription/checkout", json={"plan": plan})
        return response.json().get("checkout_url", "")

    # ========== 积分/扣点接口 ==========

    @requires_plugin_permission("credits")
    def get_balance(self) -> dict:
        """获取当前用户的积分余额
        返回: {"balance": float, "frozen": float}
        """
        response = self._request("GET", "/api/v1/credits")
        return response.json()

    # NOTE: 已移除 CloudAPIClient.deduct_credits（原 /api/v1/credits/deduct）。
    # 服务端 CreditController::deduct 要求 X-Internal-Service-Secret（仅内部服务调用），
    # 任何桌面客户端 HTTP 请求必然 403。扣点应由服务端在 AI 生图等任务完成后内部扣除，
    # 不应由客户端主动调用。PluginBase.deduct_credits 也已同步移除。

    @requires_plugin_permission("credits")
    def check_credits(self, required: float) -> CreditCheckResult:
        """检查积分是否足够（三态返回）

        返回 CreditCheckResult：
          - SUFFICIENT: 余额充足
          - INSUFFICIENT: 余额不足（真的不够）
          - QUERY_FAILED: 查询失败（网络/认证等异常），调用方应提示"查询失败"而非"不足"

        注意：CreditCheckResult 支持 bool() 兼容旧契约（仅 SUFFICIENT 为 True），
        但调用方应显式检查 .status 以区分"不足"与"查询失败"。
        """
        try:
            data = self.get_balance()
            available = float(data.get("balance", 0)) - float(data.get("frozen", 0))
            if available >= required:
                return CreditCheckResult(
                    status=CreditCheckStatus.SUFFICIENT, available=available
                )
            return CreditCheckResult(
                status=CreditCheckStatus.INSUFFICIENT, available=available
            )
        except CloudAPIError as e:
            logger.warning(f"积分查询失败: {e}")
            return CreditCheckResult(
                status=CreditCheckStatus.QUERY_FAILED,
                reason=str(e),
                status_code=e.status_code,
            )
        except Exception as e:
            logger.warning(f"积分查询异常: {e}")
            return CreditCheckResult(
                status=CreditCheckStatus.QUERY_FAILED,
                reason=str(e),
                status_code=0,
            )

    # ========== AI 生图接口 ==========

    @requires_plugin_permission("network")
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

    @requires_plugin_permission("network")
    def ai_poll_task(self, task_uuid: str) -> dict:
        """查询 AI 生图任务状态（万相异步轮询用）。"""
        response = self._request("GET", f"/api/v1/ai/task/{task_uuid}")
        return response.json()

    @requires_plugin_permission("network")
    def ai_cancel_task(self, task_uuid: str) -> dict:
        """取消 AI 生图任务。"""
        response = self._request("POST", f"/api/v1/ai/task/{task_uuid}/cancel")
        return response.json()

    # ========== 设备接口 ==========

    @requires_plugin_permission("network")
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
    access = get_cloud_access_token()
    # 始终创建实例（即使未登录也需要提供登录表单用）
    client = CloudAPIClient(settings().cloud_api_url)
    if access:
        client.set_tokens(access, get_cloud_refresh_token())
    _cloud_client_singleton = client
    return client


def reset_cloud_client():
    """关闭并清除单例（仅测试或完全退出时使用）"""
    global _cloud_client_singleton
    if _cloud_client_singleton is not None:
        _cloud_client_singleton.close()
        _cloud_client_singleton = None
