"""共享链接（share_links）服务。

职责：
- 调用 cloud_api（如可用）在云端创建/撤销共享链接；把关键字段缓存在本地 share_links 表。
- 没有 cloud_api 时退化为本地模拟路径，仅用于单元测试。

依赖注入：
- cloud_api_factory: 调用时返回一个 CloudAPIClient 实例；None 或调用失败 → 本地模拟。
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class ShareService:
    """创建/撤销/列出共享链接（云端优先，本地缓存）。"""

    def __init__(
        self,
        repository,
        cloud_api_factory: Optional[Callable[[], Any]] = None,
    ):
        self._repo = repository
        self._db = repository.db
        self._cloud_api_factory = cloud_api_factory

    # ========== 对外 API ==========

    def create_share_link(
        self,
        space_id: str,
        item_ids: List[int],
        expires_in_seconds: int,
    ) -> dict:
        """创建共享链接。

        返回: {id, token, expires_at, share_url}
        - 若 cloud_api 可用：POST /api/v1/share-links，云端返回的字段直接写入本地缓存。
        - 若不可用：生成本地 token，仅写本地（share_url 留空字符串）。
        """
        if not item_ids:
            raise ValueError("item_ids 不能为空")
        if expires_in_seconds <= 0:
            raise ValueError("expires_in_seconds 必须为正数")

        api = self._resolve_cloud_api()
        now = _now_ms()
        if api is not None:
            try:
                remote = api.create_share_link(
                    space_id=space_id,
                    item_ids=item_ids,
                    expires_in_seconds=expires_in_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("云端创建 share link 失败，降级到本地模拟: %s", exc)
                remote = None
        else:
            remote = None

        if remote is None:
            share_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(24)
            expires_at = now + expires_in_seconds * 1000
            share_url = ""
        else:
            share_id = str(remote.get("id") or uuid.uuid4())
            token = str(remote.get("token") or secrets.token_urlsafe(24))
            # 云端 expires_at 通常是秒；统一按 ms 存
            raw_exp = remote.get("expires_at")
            if raw_exp is None:
                expires_at = now + expires_in_seconds * 1000
            else:
                raw_exp_int = int(raw_exp)
                # 小于 10^12 → 秒；大于等于 → 毫秒
                expires_at = raw_exp_int * 1000 if raw_exp_int < 10 ** 12 else raw_exp_int
            share_url = str(remote.get("share_url") or remote.get("url") or "")

        # 写本地缓存
        creator = self._current_user_id()
        item_ids_json = json.dumps(sorted(int(i) for i in item_ids))
        sql = (
            "INSERT INTO share_links "
            "(id, token, space_id, creator_user_id, item_ids_json, expires_at, created_at, access_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)"
        )

        def op(conn):
            self._db.execute_write(
                conn,
                sql,
                (share_id, token, space_id, creator, item_ids_json, expires_at, now),
            )

        try:
            self._db.execute_with_retry(op)
        except Exception as exc:  # noqa: BLE001
            # 即使本地缓存失败也返回云端结果（非致命）
            logger.warning("share_links 本地缓存写入失败: %s", exc)

        return {
            "id": share_id,
            "token": token,
            "expires_at": expires_at,
            "share_url": share_url,
        }

    def revoke_share_link(self, share_id: str) -> None:
        """撤销：云端调用 + 本地删除。云端失败不阻塞本地删除（允许离线清理）。"""
        api = self._resolve_cloud_api()
        if api is not None:
            try:
                api.revoke_share_link(share_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("云端撤销 share link 失败（本地仍会清理）: %s", exc)

        def op(conn):
            self._db.execute_write(
                conn, "DELETE FROM share_links WHERE id = ?", (share_id,)
            )

        self._db.execute_with_retry(op)

    def list_my_share_links(self) -> List[dict]:
        """返回当前用户创建的本地缓存 share_links。"""
        creator = self._current_user_id()
        sql = (
            "SELECT id, token, space_id, creator_user_id, item_ids_json, "
            "expires_at, created_at, access_count "
            "FROM share_links WHERE creator_user_id = ? ORDER BY created_at DESC"
        )

        def op(conn):
            return self._db.fetch_all(conn, sql, (creator,))

        rows = self._db.execute_read(op)
        result = []
        for row in rows:
            try:
                item_ids = json.loads(row["item_ids_json"] or "[]")
            except (TypeError, ValueError):
                item_ids = []
            result.append({
                "id": row["id"],
                "token": row["token"],
                "space_id": row["space_id"],
                "creator_user_id": row["creator_user_id"],
                "item_ids": item_ids,
                "expires_at": int(row["expires_at"] or 0),
                "created_at": int(row["created_at"] or 0),
                "access_count": int(row["access_count"] or 0),
            })
        return result

    # ========== internal ==========

    def _resolve_cloud_api(self):
        """安全解析 cloud_api；factory 抛错或返回 None 都当作不可用。"""
        if self._cloud_api_factory is None:
            return None
        try:
            api = self._cloud_api_factory()
        except Exception as exc:  # noqa: BLE001
            logger.debug("cloud_api_factory 抛错: %s", exc)
            return None
        if api is None:
            return None
        # 若能检查登录态就检查一下
        is_auth = getattr(api, "is_authenticated", True)
        if callable(is_auth):
            try:
                is_auth = is_auth()
            except Exception:
                is_auth = False
        return api if is_auth else None

    def _current_user_id(self) -> str:
        """尽力获取当前用户 id。拿不到就返回空串（本地模式可接受）。"""
        api_factory = self._cloud_api_factory
        if api_factory is None:
            return ""
        try:
            api = api_factory()
        except Exception:
            return ""
        if api is None:
            return ""
        for attr in ("user_id", "current_user_id"):
            val = getattr(api, attr, None)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = None
            if val:
                return str(val)
        return ""
