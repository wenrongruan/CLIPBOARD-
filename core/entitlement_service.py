"""付费闸（会员等级 + 文件云同步配额）的唯一入口。

职责：
- 从云端 /api/v1/subscription 拉取 plan / status / 文件配额
- 本地缓存到 app_meta，带 TTL 和离线宽限
- can_use_files / can_upload(size) 作为 UI 灰化与上传前预检的唯一判据

重要约定：
- 本地缓存可被篡改，但不影响服务端强校验（上传到 /files/request-upload 时会二次确认）
- plan == 'free' 或 status != 'active' → files_enabled = False
- 档位命名与云端 website/api/config.php 对齐：free / basic / super / ultimate
- 文件单体上限硬编码 1 GB，与服务端保持一致
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Tuple

from PySide6.QtCore import QObject, Signal

from core.cloud_api import CloudAPIClient, CloudAPIError

logger = logging.getLogger(__name__)


# 客户端硬上限：1 GB/单文件。服务端也会校验，这里只是为了尽早拦截。
MAX_SINGLE_FILE_BYTES = 1 << 30
# 配额兜底值，仅在云端响应缺少 files.quota_bytes 时使用。权威值见 website/api/config.php 的 'plans'。
_DEFAULT_BASIC_QUOTA_BYTES = 5 * (1 << 30)         # 5 GB
_DEFAULT_SUPER_QUOTA_BYTES = 50 * (1 << 30)        # 50 GB
_DEFAULT_ULTIMATE_QUOTA_BYTES = 200 * (1 << 30)    # 200 GB
_CACHE_TTL_SEC = 60 * 60                         # 60 min
_OFFLINE_GRACE_SEC = 7 * 24 * 60 * 60            # 7 天
_APP_META_KEY = "entitlement_cache"


class Plan(str, Enum):
    FREE = "free"
    BASIC = "basic"
    SUPER = "super"
    ULTIMATE = "ultimate"

    @classmethod
    def parse(cls, raw) -> "Plan":
        # 未知字符串（含老缓存里的 'pro'/'premium'）兜底为 FREE；下一次 refresh_async
        # 从服务端拉到正确值后会自动自愈。
        if isinstance(raw, dict):
            raw = raw.get("tier") or raw.get("name") or raw.get("code") or "free"
        try:
            return cls(str(raw).lower())
        except ValueError:
            return cls.FREE


@dataclass(frozen=True)
class Entitlement:
    plan: Plan = Plan.FREE
    status: str = "inactive"
    files_enabled: bool = False
    files_quota_bytes: int = 0
    files_used_bytes: int = 0
    max_file_size_bytes: int = MAX_SINGLE_FILE_BYTES
    fetched_at: int = 0
    offline_grace_until: int = 0

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.files_quota_bytes - self.files_used_bytes)


def _default_quota_for(plan: Plan) -> int:
    if plan == Plan.BASIC:
        return _DEFAULT_BASIC_QUOTA_BYTES
    if plan == Plan.SUPER:
        return _DEFAULT_SUPER_QUOTA_BYTES
    if plan == Plan.ULTIMATE:
        return _DEFAULT_ULTIMATE_QUOTA_BYTES
    return 0


class EntitlementService(QObject):
    """会员/配额缓存服务（线程安全，UI 与同步服务共用）。"""

    entitlement_changed = Signal(object)  # Entitlement

    def __init__(self, cloud_api: Optional[CloudAPIClient], repository=None, parent=None):
        super().__init__(parent)
        self._cloud_api = cloud_api
        self._repository = repository  # 复用已有的 app_meta 存储（可能为 None，退化为内存）
        self._lock = threading.RLock()
        self._current: Entitlement = Entitlement()
        self._refresh_thread: Optional[threading.Thread] = None
        self._load_from_meta_locked()

    def set_cloud_api(self, cloud_api: Optional[CloudAPIClient]) -> None:
        with self._lock:
            self._cloud_api = cloud_api

    # ---------- 读 ----------

    def current(self) -> Entitlement:
        with self._lock:
            return self._current

    def can_use_files(self) -> Tuple[bool, str]:
        e = self.current()
        if not e.files_enabled:
            if e.plan == Plan.FREE:
                return False, "文件云同步需要付费订阅（Basic / Super / Ultimate），请先升级套餐。"
            if e.status != "active":
                return False, f"订阅当前状态为 {e.status}，无法使用文件云同步。"
            return False, "当前套餐暂不支持文件云同步。"
        # 离线宽限期已到期且最近一次缓存很旧 → 拒绝（服务端校验也会兜底）
        now = int(time.time())
        if e.offline_grace_until and now > e.offline_grace_until:
            return False, "长时间未能连接云端确认订阅，功能暂时停用，请联网后重试。"
        return True, ""

    def can_upload(self, size: int) -> Tuple[bool, str]:
        ok, reason = self.can_use_files()
        if not ok:
            return False, reason
        if size <= 0:
            return False, "文件为空，无法上传。"
        e = self.current()
        if size > MAX_SINGLE_FILE_BYTES:
            return False, f"单文件不能超过 1 GB（当前 {size / (1 << 30):.2f} GB）。"
        if e.max_file_size_bytes and size > e.max_file_size_bytes:
            return False, f"当前套餐单文件上限为 {e.max_file_size_bytes / (1 << 30):.2f} GB。"
        if e.files_quota_bytes and e.files_used_bytes + size > e.files_quota_bytes:
            return False, (
                f"剩余云端空间不足：剩 {e.remaining_bytes / (1 << 20):.1f} MB，"
                f"需要 {size / (1 << 20):.1f} MB。"
            )
        return True, ""

    # ---------- 写 ----------

    def refresh_async(self) -> None:
        """后台刷新；同一时刻只允许一条刷新线程。"""
        with self._lock:
            if self._refresh_thread and self._refresh_thread.is_alive():
                return
            if self._cloud_api is None or not self._cloud_api.is_authenticated:
                # 未登录：置为 free；无后台请求
                self._apply_locked(Entitlement(
                    plan=Plan.FREE, status="inactive", files_enabled=False,
                    fetched_at=int(time.time()),
                ))
                return
            t = threading.Thread(
                target=self._do_refresh, name="EntitlementRefresh", daemon=True,
            )
            self._refresh_thread = t
        t.start()

    def invalidate(self) -> None:
        """登出时调用：清空内存与持久化缓存。"""
        with self._lock:
            self._current = Entitlement()
            self._persist_locked(None)
        self.entitlement_changed.emit(self._current)

    def record_local_upload(self, size: int) -> None:
        """乐观更新本地 files_used_bytes，避免连续上传时本地预检过于乐观。
        真实用量以下次 refresh_async 的服务端返回为准。"""
        with self._lock:
            new = replace(
                self._current,
                files_used_bytes=max(0, self._current.files_used_bytes + int(size)),
            )
            self._apply_locked(new)

    # ---------- internal ----------

    def _do_refresh(self) -> None:
        try:
            data = self._cloud_api.get_subscription()
        except CloudAPIError as e:
            logger.info(f"EntitlementService 刷新失败（走缓存兜底）: {e}")
            self._extend_grace_on_error()
            return
        except Exception as e:
            logger.warning(f"EntitlementService 刷新异常: {e}")
            self._extend_grace_on_error()
            return

        plan = Plan.parse(data.get("plan", "free"))
        status = (data.get("status") or "active").lower()
        files_block = data.get("files") if isinstance(data.get("files"), dict) else {}
        quota = int(files_block.get("quota_bytes") or data.get("files_quota_bytes") or _default_quota_for(plan))
        used = int(files_block.get("used_bytes") or data.get("files_used_bytes") or 0)
        # 服务端若下发 max_file_size_bytes 则尊重，否则以客户端硬上限为准
        max_single = int(
            files_block.get("max_file_size_bytes")
            or data.get("max_file_size_bytes")
            or MAX_SINGLE_FILE_BYTES
        )
        max_single = min(max_single, MAX_SINGLE_FILE_BYTES)

        files_enabled_server = files_block.get("enabled")
        if files_enabled_server is None:
            files_enabled = plan != Plan.FREE and status == "active"
        else:
            files_enabled = bool(files_enabled_server) and plan != Plan.FREE and status == "active"

        now = int(time.time())
        ent = Entitlement(
            plan=plan,
            status=status,
            files_enabled=files_enabled,
            files_quota_bytes=max(0, quota) if files_enabled else 0,
            files_used_bytes=max(0, used),
            max_file_size_bytes=max_single,
            fetched_at=now,
            offline_grace_until=now + _OFFLINE_GRACE_SEC if files_enabled else 0,
        )
        with self._lock:
            self._apply_locked(ent)

    def _extend_grace_on_error(self) -> None:
        """网络失败时不动 plan / status，仅重设 offline_grace_until（若从未联网过则置 0）。"""
        with self._lock:
            cur = self._current
            if cur.fetched_at == 0:
                return
            # grace 基于上次成功时间，不因失败延长；这里仅 emit 给 UI 刷一下显示
            self.entitlement_changed.emit(cur)

    def _apply_locked(self, ent: Entitlement) -> None:
        changed = ent != self._current
        self._current = ent
        self._persist_locked(ent)
        if changed:
            self.entitlement_changed.emit(ent)

    def _persist_locked(self, ent: Optional[Entitlement]) -> None:
        if self._repository is None:
            return
        try:
            if ent is None:
                self._repository.set_meta(_APP_META_KEY, "")
                return
            payload = {
                "plan": ent.plan.value,
                "status": ent.status,
                "files_enabled": ent.files_enabled,
                "files_quota_bytes": ent.files_quota_bytes,
                "files_used_bytes": ent.files_used_bytes,
                "max_file_size_bytes": ent.max_file_size_bytes,
                "fetched_at": ent.fetched_at,
                "offline_grace_until": ent.offline_grace_until,
            }
            self._repository.set_meta(_APP_META_KEY, json.dumps(payload))
        except Exception as e:
            logger.debug(f"持久化 entitlement 失败: {e}")

    def _load_from_meta_locked(self) -> None:
        if self._repository is None:
            return
        try:
            raw = self._repository.get_meta(_APP_META_KEY, None)
        except Exception:
            raw = None
        if not raw:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("entitlement 缓存 JSON 损坏，忽略")
            return
        try:
            self._current = Entitlement(
                plan=Plan.parse(data.get("plan", "free")),
                status=str(data.get("status", "inactive")),
                files_enabled=bool(data.get("files_enabled", False)),
                files_quota_bytes=int(data.get("files_quota_bytes", 0)),
                files_used_bytes=int(data.get("files_used_bytes", 0)),
                max_file_size_bytes=int(data.get("max_file_size_bytes", MAX_SINGLE_FILE_BYTES)),
                fetched_at=int(data.get("fetched_at", 0)),
                offline_grace_until=int(data.get("offline_grace_until", 0)),
            )
        except (TypeError, ValueError) as e:
            logger.debug(f"entitlement 缓存反序列化失败: {e}")


# ========== 全局单例 ==========
_instance: Optional[EntitlementService] = None
_instance_lock = threading.Lock()


def get_entitlement_service(
    cloud_api: Optional[CloudAPIClient] = None, repository=None,
) -> EntitlementService:
    """返回全局 EntitlementService；首次调用时初始化。后续调用会按需更新 cloud_api 引用。"""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = EntitlementService(cloud_api=cloud_api, repository=repository)
        else:
            if cloud_api is not None:
                _instance.set_cloud_api(cloud_api)
        return _instance


def reset_entitlement_service() -> None:
    """仅在测试或完全重启时调用。"""
    global _instance
    with _instance_lock:
        _instance = None
