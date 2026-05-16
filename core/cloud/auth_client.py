"""AuthClient：登录 / 注册 / 刷新 token / 注销 / 设备注册。

同时包含账户级"非 item"接口：订阅、积分、AI 生图。
Why：spec 只允许 4 个 domain client，account-level（订阅/积分/AI）
天然贴近"用户身份"语义，与登录/退出同源，故合并到 auth_client。

domain client 通过持有 facade（CloudAPIClient 实例）调用 self._facade._request,
这样 tests 用 patch.object(client, "_request", ...) 仍能拦截到所有调用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.cloud.http import (
    CloudAPIError,
    CreditCheckResult,
    CreditCheckStatus,
    requires_plugin_permission,
)

if TYPE_CHECKING:  # pragma: no cover
    from core.cloud_api import CloudAPIClient

logger = logging.getLogger(__name__)


class AuthClient:
    """认证 + 账户级接口（订阅 / 积分 / AI）。"""

    def __init__(self, facade: "CloudAPIClient"):
        self._facade = facade
        self._http = facade._http  # 直读 http 状态（token / base_url）

    # ========== 认证接口 ==========

    @requires_plugin_permission("network")
    def register(self, email: str, password: str, display_name: str = None) -> dict:
        """注册新用户，返回用户信息和 tokens"""
        payload = {"email": email, "password": password}
        if display_name:
            payload["name"] = display_name

        response = self._facade._request("POST", "/api/v1/auth/register", auth_required=False, json=payload)
        data = response.json()
        self._http._handle_auth_response(data, email)
        return data

    @requires_plugin_permission("network")
    def login(self, email: str, password: str) -> dict:
        """登录，返回 tokens"""
        payload = {"email": email, "password": password}
        response = self._facade._request("POST", "/api/v1/auth/login", auth_required=False, json=payload)
        data = response.json()
        self._http._handle_auth_response(data, email)
        return data

    @requires_plugin_permission("network")
    def refresh_token(self) -> bool:
        """使用 refresh_token 刷新 access_token。委托给 HttpClient.refresh_token。
        Why: _request 的 401 自动重试路径必须直接调用 HttpClient.refresh_token,
        避免 HttpClient → AuthClient 反向依赖；此方法是给外部业务代码的稳定入口。
        """
        return self._http.refresh_token()

    @requires_plugin_permission("network")
    def logout(self):
        """退出登录，清除本地 tokens"""
        from config import set_cloud_access_token, set_cloud_refresh_token, update_settings

        try:
            self._facade._request("POST", "/api/v1/auth/logout", auth_required=True)
        except CloudAPIError as e:
            logger.warning(f"服务端 logout 失败（仍清除本地 token）: {e}")

        self._http._access_token = None
        self._http._refresh_token_str = None
        set_cloud_access_token("")
        set_cloud_refresh_token("")
        update_settings(cloud_user_email="")
        self._http._update_auth_json("", "")
        logger.info("已退出云端登录")

    # ========== 设备接口 ==========

    @requires_plugin_permission("network")
    def register_device(self, device_id: str, device_name: str, platform: str) -> bool:
        """注册当前设备"""
        try:
            self._facade._request(
                "POST",
                "/api/v1/devices",
                json={"device_id": device_id, "device_name": device_name, "platform": platform},
            )
            return True
        except CloudAPIError as e:
            logger.error(f"设备注册失败: {e}")
            return False

    # ========== 订阅接口 ==========

    @requires_plugin_permission("credits")
    def get_subscription(self) -> dict:
        """获取当前用户的订阅信息"""
        response = self._facade._request("GET", "/api/v1/subscription")
        return response.json()

    @requires_plugin_permission("credits")
    def create_checkout(self, plan: str) -> str:
        """创建支付 checkout，返回 checkout URL"""
        response = self._facade._request("POST", "/api/v1/subscription/checkout", json={"plan": plan})
        return response.json().get("checkout_url", "")

    # ========== 积分/扣点接口 ==========

    @requires_plugin_permission("credits")
    def get_balance(self) -> dict:
        """获取当前用户的积分余额
        返回: {"balance": float, "frozen": float}
        """
        response = self._facade._request("GET", "/api/v1/credits")
        return response.json()

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
        response = self._facade._request("POST", "/api/v1/ai/generate", json=payload)
        return response.json()

    @requires_plugin_permission("network")
    def ai_poll_task(self, task_uuid: str) -> dict:
        """查询 AI 生图任务状态（万相异步轮询用）。"""
        response = self._facade._request("GET", f"/api/v1/ai/task/{task_uuid}")
        return response.json()

    @requires_plugin_permission("network")
    def ai_cancel_task(self, task_uuid: str) -> dict:
        """取消 AI 生图任务。"""
        response = self._facade._request("POST", f"/api/v1/ai/task/{task_uuid}/cancel")
        return response.json()
