"""CloudAPIClient facade。

对外保持现有所有 public 方法签名;内部 delegate 到 auth / sync / files / spaces
四个 domain client + HttpClient 网络底盘。

domain 划分（44 public 方法）:
  auth (15)   = 登录/注册/刷新/注销 + 设备注册 + 订阅 + 积分 + AI 生图
                login, register, refresh_token, logout, set_tokens, get_tokens,
                register_device, get_subscription, create_checkout, get_balance,
                check_credits, ai_generate, ai_poll_task, ai_cancel_task, close
  sync (8)    = 条目批量上传/拉取/删除/收藏 + 图片接口
                upload_items, batch_create, sync, delete_item, toggle_star,
                upload_image, get_image_url, download_image
  files (9)   = 付费文件单段/分片上传 + 下载 + 去重 + meta
                files_list, files_get_quota, files_request_upload,
                files_complete_upload, files_get_download_url, files_update_meta,
                files_delete, upload_file_to_url, download_file_to
  spaces (12) = 团队空间 + 分享链接
                list_spaces, create_space, update_space, delete_space,
                list_space_members, invite_space_member, remove_space_member,
                leave_space, list_share_links, create_share_link,
                revoke_share_link, view_share_link

get_cloud_client() / reset_cloud_client() 保留 Phase 1 加入的 AppContext-first 路由。
CloudAPIError / CreditCheckResult / CreditCheckStatus / requires_plugin_permission
从 core.cloud.http 重导出,外部 import 路径不变。
"""

from __future__ import annotations

import logging
from typing import Optional

from config import (
    get_cloud_access_token,
    get_cloud_refresh_token,
    settings,
)

# 重导出 —— 外部 (cloud_sync_service / entitlement_service / ui) 直接
# from core.cloud_api import CloudAPIError 仍然可用
from core.cloud.http import (  # noqa: F401
    CloudAPIError,
    CreditCheckResult,
    CreditCheckStatus,
    HttpClient,
    requires_plugin_permission,
)
from core.cloud.auth_client import AuthClient
from core.cloud.files_client import FilesClient
from core.cloud.spaces_client import SpacesClient
from core.cloud.sync_client import SyncClient

logger = logging.getLogger(__name__)


class CloudAPIClient:
    """云端 API 客户端 facade。

    构造时建立 HttpClient + 4 个 domain client；所有 public 方法都 delegate 到
    domain client。tests 用 ``patch.object(client, "_request", ...)`` 能拦截所有
    HTTP 调用（domain client 内部统一通过 ``self._facade._request`` 走），
    保持原有 mock 测试不需要改写。
    """

    # ========== Class-level constants（保持外部直接 import 兼容） ==========
    # file_sync_service 读取 cloud_api.FILE_PART_SIZE / FILE_MULTIPART_THRESHOLD
    FILE_SIZE_HARD_LIMIT = HttpClient.FILE_SIZE_HARD_LIMIT
    FILE_MULTIPART_THRESHOLD = HttpClient.FILE_MULTIPART_THRESHOLD
    FILE_PART_SIZE = HttpClient.FILE_PART_SIZE
    _ALLOWED_DOWNLOAD_DOMAINS = HttpClient._ALLOWED_DOWNLOAD_DOMAINS
    _ALLOWED_UPLOAD_DOMAINS = HttpClient._ALLOWED_UPLOAD_DOMAINS

    def __init__(self, base_url: str):
        self._http = HttpClient(base_url)
        # 4 个 domain client 都拿到 facade 引用,domain 方法统一调
        # self._facade._request → tests patch.object(c, "_request") 可拦截。
        self.auth = AuthClient(self)
        self.sync_client = SyncClient(self)
        self.files = FilesClient(self)
        self.spaces = SpacesClient(self)

    # ========== 内部 hook：让 patch.object(c, "_request") 生效 ==========

    def _request(self, method: str, path: str, auth_required: bool = True, **kwargs):
        """统一请求入口。委托给 HttpClient._request。

        放在 facade 上的原因: 既有测试 (test_cloud_sync_service.py 等) 用
        ``patch.object(client, "_request", ...)`` 拦截 HTTP；domain client 内部
        通过 ``self._facade._request(...)`` 调用,patch 后命中实例属性,所有
        delegated public 方法都会走 mock。
        """
        return self._http._request(method, path, auth_required=auth_required, **kwargs)

    def _ensure_auth(self):
        """转发给 HttpClient（保留为兼容入口，旧代码或测试可能直接调用）。"""
        return self._http._ensure_auth()

    def _save_tokens(self, access_token: str, refresh_token: str):
        return self._http._save_tokens(access_token, refresh_token)

    def _update_auth_json(self, access_token: str, refresh_token: str):
        return self._http._update_auth_json(access_token, refresh_token)

    def _handle_auth_response(self, data: dict, email: str):
        return self._http._handle_auth_response(data, email)

    def _validate_storage_url(self, url: str, domains: set) -> bool:
        return self._http._validate_storage_url(url, domains)

    @staticmethod
    def _apply_windows_acl(path):
        return HttpClient._apply_windows_acl(path)

    # ========== 公开属性 / token 状态转发 ==========

    @property
    def base_url(self) -> str:
        return self._http.base_url

    @property
    def is_authenticated(self) -> bool:
        return self._http.is_authenticated

    # token 状态：tests 直接读写 client._access_token / client._refresh_token_str
    @property
    def _access_token(self) -> Optional[str]:
        return self._http._access_token

    @_access_token.setter
    def _access_token(self, value: Optional[str]):
        self._http._access_token = value

    @property
    def _refresh_token_str(self) -> Optional[str]:
        return self._http._refresh_token_str

    @_refresh_token_str.setter
    def _refresh_token_str(self, value: Optional[str]):
        self._http._refresh_token_str = value

    # httpx 客户端：test_file_upload_flow.py 通过 client._client = MockTransport() 替换
    @property
    def _client(self):
        return self._http._client

    @_client.setter
    def _client(self, value):
        self._http._client = value

    @property
    def _base_url(self) -> str:
        return self._http._base_url

    # ========== Token 管理（auth_client 同名方法的对外别名） ==========

    def set_tokens(self, access_token: str, refresh_token: str):
        """从外部设置 tokens（如从配置文件加载）"""
        self._http.set_tokens(access_token, refresh_token)

    def get_tokens(self) -> tuple:
        """返回 (access_token, refresh_token)"""
        return self._http.get_tokens()

    # ========== Auth domain delegation ==========

    def register(self, *args, **kwargs):
        return self.auth.register(*args, **kwargs)

    def login(self, *args, **kwargs):
        return self.auth.login(*args, **kwargs)

    def refresh_token(self) -> bool:
        return self.auth.refresh_token()

    def logout(self):
        return self.auth.logout()

    def register_device(self, *args, **kwargs) -> bool:
        return self.auth.register_device(*args, **kwargs)

    def get_subscription(self) -> dict:
        return self.auth.get_subscription()

    def create_checkout(self, plan: str) -> str:
        return self.auth.create_checkout(plan)

    def get_balance(self) -> dict:
        return self.auth.get_balance()

    def check_credits(self, required: float):
        return self.auth.check_credits(required)

    def ai_generate(self, *args, **kwargs) -> dict:
        return self.auth.ai_generate(*args, **kwargs)

    def ai_poll_task(self, task_uuid: str) -> dict:
        return self.auth.ai_poll_task(task_uuid)

    def ai_cancel_task(self, task_uuid: str) -> dict:
        return self.auth.ai_cancel_task(task_uuid)

    # ========== Sync domain delegation ==========
    # 注意:facade 上的 method 名是 `sync`,domain client 实例叫 `sync_client`
    # （避免 self.sync 与方法 sync() 冲突）。

    def upload_items(self, items: list) -> list:
        return self.sync_client.upload_items(items)

    def batch_create(self, items: list, device_id: Optional[str] = None) -> dict:
        return self.sync_client.batch_create(items, device_id=device_id)

    def sync(self, since_id: int, device_id: str, space_id: Optional[str] = None) -> dict:
        return self.sync_client.sync(since_id, device_id, space_id=space_id)

    def delete_item(self, item_id: int) -> bool:
        return self.sync_client.delete_item(item_id)

    def toggle_star(self, item_id: int) -> bool:
        return self.sync_client.toggle_star(item_id)

    def upload_image(self, item_id: int, image_data: bytes) -> bool:
        return self.sync_client.upload_image(item_id, image_data)

    def get_image_url(self, item_id: int) -> str:
        return self.sync_client.get_image_url(item_id)

    def download_image(self, item_id: int) -> Optional[bytes]:
        return self.sync_client.download_image(item_id)

    # ========== Files domain delegation ==========

    def files_list(self, since_id: int, device_id: str, limit: int = 100) -> dict:
        return self.files.files_list(since_id, device_id, limit=limit)

    def files_get_quota(self) -> dict:
        return self.files.files_get_quota()

    def files_request_upload(self, meta: dict) -> dict:
        return self.files.files_request_upload(meta)

    def files_complete_upload(self, cloud_id: int, etags: list) -> dict:
        return self.files.files_complete_upload(cloud_id, etags)

    def files_get_download_url(self, cloud_id: int) -> str:
        return self.files.files_get_download_url(cloud_id)

    def files_update_meta(self, cloud_id: int, patch: dict) -> dict:
        return self.files.files_update_meta(cloud_id, patch)

    def files_delete(self, cloud_id: int) -> bool:
        return self.files.files_delete(cloud_id)

    def upload_file_to_url(self, *args, **kwargs) -> str:
        return self.files.upload_file_to_url(*args, **kwargs)

    def download_file_to(self, *args, **kwargs) -> int:
        return self.files.download_file_to(*args, **kwargs)

    # ========== Spaces domain delegation ==========

    def list_spaces(self) -> list:
        return self.spaces.list_spaces()

    def create_space(self, name: str, type_: str) -> dict:
        return self.spaces.create_space(name, type_)

    def update_space(self, space_id: str, name: str) -> dict:
        return self.spaces.update_space(space_id, name)

    def delete_space(self, space_id: str) -> None:
        return self.spaces.delete_space(space_id)

    def list_space_members(self, space_id: str) -> list:
        return self.spaces.list_space_members(space_id)

    def invite_space_member(self, space_id: str, email: str, role: str) -> dict:
        return self.spaces.invite_space_member(space_id, email, role)

    def remove_space_member(self, space_id: str, user_id: str) -> None:
        return self.spaces.remove_space_member(space_id, user_id)

    def leave_space(self, space_id: str) -> None:
        return self.spaces.leave_space(space_id)

    def list_space_invitations(self, space_id: str) -> list:
        return self.spaces.list_space_invitations(space_id)

    def revoke_space_invitation(self, space_id: str, token: str) -> None:
        return self.spaces.revoke_space_invitation(space_id, token)

    def list_incoming_invitations(self) -> list:
        return self.spaces.list_incoming_invitations()

    def accept_invitation(self, token: str) -> dict:
        return self.spaces.accept_invitation(token)

    def list_share_links(self) -> list:
        return self.spaces.list_share_links()

    def create_share_link(
        self, space_id: Optional[str], item_ids: list, expires_in_seconds: int,
    ) -> dict:
        return self.spaces.create_share_link(space_id, item_ids, expires_in_seconds)

    def revoke_share_link(self, share_id: str) -> None:
        return self.spaces.revoke_share_link(share_id)

    def view_share_link(self, token: str) -> dict:
        return self.spaces.view_share_link(token)

    # ========== 生命周期 ==========

    def close(self):
        """关闭 HTTP 客户端"""
        self._http.close()


# ========== 全局单例 ==========
# 为避免 main/MainWindow/SettingsDialog 各自 new CloudAPIClient 导致 token 不同步，
# 所有 UI/服务层都应通过 get_cloud_client() 访问。
_cloud_client_singleton: Optional[CloudAPIClient] = None


def get_cloud_client(create_if_missing: bool = True) -> Optional[CloudAPIClient]:
    """返回全局唯一的 CloudAPIClient，按需从已保存 token 恢复。
    create_if_missing=False 时仅查，不会自动创建空壳客户端。

    Phase 1 起：优先走 AppContext.current().cloud_api；AppContext 还没 bootstrap
    （测试 / 早期启动）时退回旧的单例逻辑。
    """
    # 走 AppContext 而非裸单例，避免 main 与 AppContext 各持一份不同步的 client
    ctx_for_writeback = None
    try:
        from core.app_context import AppContext
        ctx = AppContext.current()
        if ctx.cloud_api is not None:
            return ctx.cloud_api
        ctx_for_writeback = ctx
    except RuntimeError:
        pass
    except Exception:
        # AppContext 模块导入异常不应连锁拖垮云端 client；走旧路径兜底
        pass

    global _cloud_client_singleton
    if _cloud_client_singleton is not None:
        return _cloud_client_singleton
    if not create_if_missing:
        return None
    client = CloudAPIClient(settings().cloud_api_url)
    access = get_cloud_access_token()
    if access:
        client.set_tokens(access, get_cloud_refresh_token())
    _cloud_client_singleton = client
    if ctx_for_writeback is not None:
        ctx_for_writeback.cloud_api = client
    return client


def reset_cloud_client():
    """关闭并清除单例（仅测试或完全退出时使用）"""
    global _cloud_client_singleton
    clients = []
    if _cloud_client_singleton is not None:
        clients.append(_cloud_client_singleton)
    _cloud_client_singleton = None
    try:
        from core.app_context import AppContext
        ctx = AppContext.current()
        if getattr(ctx, "cloud_api", None) is not None:
            if ctx.cloud_api not in clients:
                clients.append(ctx.cloud_api)
            ctx.cloud_api = None
    except Exception:
        pass
    for client in clients:
        try:
            client.close()
        except Exception:
            logger.debug("关闭 CloudAPIClient 失败", exc_info=True)


def rebuild_cloud_client_for_url(new_url: str) -> CloudAPIClient:
    """切换服务器地址后重建客户端。

    Why: HttpClient 的 base_url 在构造时固定，更换 cloud_api_url 后必须
    丢掉旧 client，否则后续请求仍会打到旧域名。同时清掉 AppContext 的引用，
    让 get_cloud_client() 走重新构造分支。
    """
    global _cloud_client_singleton
    reset_cloud_client()
    try:
        from core.app_context import AppContext
        ctx = AppContext.current()
        if getattr(ctx, "cloud_api", None) is not None:
            try:
                ctx.cloud_api.close()
            except Exception:
                pass
            ctx.cloud_api = None
    except Exception:
        pass
    client = CloudAPIClient(new_url)
    _cloud_client_singleton = client
    try:
        from core.app_context import AppContext
        ctx = AppContext.current()
        ctx.cloud_api = client
    except Exception:
        pass
    return client
