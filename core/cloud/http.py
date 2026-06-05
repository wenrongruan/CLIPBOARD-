"""HttpClient：所有 domain client 共享的网络底盘。

负责：
- base_url / httpx.Client 持有
- access_token / refresh_token 状态 + 持久化（auth.json + secure_store）
- 统一 _request 入口（自动鉴权、401 自动刷新 token、错误映射为 CloudAPIError）
- presigned URL 域名白名单校验
- 文件相关常量（大小上限 / 分片阈值 / 分片大小）

domain client（auth/sync/files/spaces）通过持有 HttpClient 引用,
统一调用 self._http._request(...)；token 状态以 HttpClient 为单一来源。
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import platform
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import (
    IS_APPSTORE_BUILD,
    IS_MACOS,
    set_cloud_access_token,
    set_cloud_refresh_token,
    update_settings,
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


class HttpClient:
    """HTTP 底盘：base_url + httpx.Client + token 状态 + 统一 _request。"""

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
        # 刷新串行化：服务端 refresh token 单次使用（用完即焚），多个后台线程
        # 共用本 HttpClient，access token 到期时会集体撞 401 并发刷新。无锁时第二个
        # 线程拿已被消费的旧 token 撞 401 会误清登录态 → 用户"自动掉线"。
        self._refresh_lock = threading.Lock()
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
          4. macOS 上额外打 com.apple.metadata:com_apple_backup_excludeItem
             扩展属性，把文件踢出 Time Machine / iCloud Backup，避免 token
             流入备份。

        App Store 构建不打包 ai_image_gen，没有外部进程会读 auth.json；
        为避免 token 落进沙盒 container 又随备份外泄，直接跳过写入。
        """
        if IS_APPSTORE_BUILD:
            return
        try:
            auth_dir = Path.home() / ".shared_clipboard"
            # 兜底：若同名路径意外是个文件（极端污染场景），删掉再建目录
            if auth_dir.exists() and not auth_dir.is_dir():
                try:
                    auth_dir.unlink()
                except OSError as e:
                    logger.warning(f"~/.shared_clipboard 不是目录且无法删除: {e}")
                    return
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

            # 防御性二次检查：在 os.replace 前确保 tmp 和目标目录都存在。
            # 此前真机观察到 os.replace 报 ENOENT，怀疑是上层目录在某些时机被清理。
            # Why: os.replace 失败会丢失 tmp 文件且不可恢复，这里宁可多花一次 stat。
            if not tmp_file.exists():
                logger.warning(f"auth.json.tmp 在写入后丢失，跳过 replace: {tmp_file}")
                return
            if not auth_dir.is_dir():
                auth_dir.mkdir(parents=True, exist_ok=True)
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

            if IS_MACOS:
                # 把 auth.json 从 Time Machine / iCloud Backup 中排除。
                # 注意：xattr 的 plist value 必须是 binary plist 头，否则 macOS
                # 不识别。这里走 NSURL 资源属性 API（Foundation），失败则降级
                # 用 `xattr -wx` 写裸字节，再失败就 silently 跳过——文件本身已
                # chmod 0600，最坏情况只是会被备份。
                self._exclude_from_backup_macos(auth_file)
        except Exception:
            logger.warning("更新 auth.json 失败", exc_info=True)

    @staticmethod
    def _exclude_from_backup_macos(path: Path) -> None:
        """macOS: 给文件打 NSURLIsExcludedFromBackupKey，使其不进 Time Machine。"""
        try:
            from Foundation import NSURL  # type: ignore[import-not-found]
            url = NSURL.fileURLWithPath_(str(path))
            ok, err = url.setResourceValue_forKey_error_(True, "NSURLIsExcludedFromBackupKey", None)
            if not ok:
                logger.debug(f"NSURL excludeFromBackup 失败: {err}")
        except Exception as e:
            logger.debug(f"NSURL 方式排除备份失败，尝试 xattr 兜底: {e}")
            try:
                subprocess.run(
                    ["xattr", "-wx", "com.apple.metadata:com_apple_backup_excludeItem",
                     "62706c6973743030093103090a", str(path)],
                    check=False, capture_output=True, timeout=2,
                )
            except Exception as e2:
                logger.debug(f"xattr 兜底也失败（忽略）: {e2}")

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

    def _handle_auth_response(self, data: dict, email: str):
        """从认证响应中提取并保存 tokens。AuthClient.login/register 调用。"""
        access = data.get("token") or data.get("access_token", "")
        refresh = data.get("refresh_token", "")
        if access and refresh:
            self._save_tokens(access, refresh)
            update_settings(cloud_user_email=email)
        else:
            logger.warning(f"认证响应中缺少 token: access={bool(access)}, refresh={bool(refresh)}")
            raise CloudAPIError("登录成功但服务端未返回有效 token，请重试")

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
            body_preview = ""
            try:
                error_data = response.json() or {}
                message = error_data.get("error", error_data.get("detail", f"服务器错误 ({response.status_code})"))
            except Exception:
                body_preview = response.text[:500] if response.text else ""
                message = f"服务器错误 ({response.status_code})"
            # 5xx 或服务端带 debug/sqlstate 时常态打 warning，避免用户只看到"internal error"却无上下文
            if response.status_code >= 500 or error_data.get("debug") or error_data.get("sqlstate"):
                logger.warning(
                    "云端 %s %s 失败: status=%s error=%r debug=%r sqlstate=%r body=%r",
                    method, path, response.status_code, message,
                    error_data.get("debug"), error_data.get("sqlstate"), body_preview,
                )
            elif body_preview:
                logger.debug(f"错误响应体: {body_preview}")
            raise CloudAPIError(message, response.status_code, error_data)

        return response

    def _ensure_auth(self):
        """检查 token 有效性"""
        if not self._access_token:
            raise CloudAPIError("未登录，请先登录云端账户", 401)

    def refresh_token(self) -> bool:
        """使用 refresh_token 刷新 access_token，成功返回 True。
        仅在服务端明确返回 401/403 时才清除本地 token；网络错误保留 token 以便下次重试。

        放在 HttpClient 上是因为 _request 的 401 自动重试需要直接调用它,
        避免 HttpClient 反向依赖 AuthClient。AuthClient.refresh_token 直接转发。

        并发安全：服务端 refresh token 单次使用（换一次即作废），多个后台线程共用
        同一 HttpClient，access token 到期时会并发进入本方法。用 _refresh_lock 串行化，
        并在拿到锁后做"双重检查"——若等锁期间已有其他线程换到新 access_token，直接
        复用，绝不再拿已被消费的旧 refresh token 去换（那必然撞 401 → 误清登录态）。
        """
        if not self._refresh_token_str:
            return False

        # 锁前快照当前 access_token：用于在拿到锁后判断"是否已被别的线程刷新过"。
        access_before = self._access_token

        with self._refresh_lock:
            # 双重检查：等锁期间若 access_token 已被其他线程换新，说明刷新已成功，
            # 直接复用，不重复消费旧 refresh token。
            if self._access_token and self._access_token != access_before:
                return True

            refresh_str = self._refresh_token_str
            if not refresh_str:
                return False

            try:
                response = self._client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": refresh_str},
                    timeout=15.0,
                )
            except httpx.HTTPError as e:
                logger.warning(f"Token 刷新网络失败（保留本地 token 待下次重试）: {e}")
                return False

            return self._apply_refresh_response(response)

    def _apply_refresh_response(self, response: httpx.Response) -> bool:
        """处理 /auth/refresh 响应：200 保存新 token；401/403 清登录态。调用方持有 _refresh_lock。"""

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

    # ========== 存储 URL 校验 ==========

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

    def close(self):
        """关闭 HTTP 客户端"""
        try:
            self._client.close()
        except Exception:
            pass
