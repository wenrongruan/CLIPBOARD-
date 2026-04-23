"""Spaces/成员的本地管理 + 当前激活 space 的会话状态。

职责：
- 对 spaces / space_members 两张本地表做 CRUD。
- 维护内存中的 "当前激活 space" 状态（不落库；切换 space 由调用方感知）。
- 为 cloud_sync_service 提供 upsert_from_remote 入口。

约定：
- PERSONAL_SPACE_ID = "" 表示个人空间，不会落 spaces 表。
- ClipboardItem.space_id == None 与 "" 语义等价（查询要考虑两种）。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Space:
    id: str
    name: str
    type: str              # personal | team
    owner_user_id: str
    created_at: int
    updated_at: int
    role: str = ""         # 当前用户在该 space 的角色（查 space_members 得到）


@dataclass
class SpaceMember:
    space_id: str
    user_id: str
    role: str              # owner | editor | viewer
    joined_at: int
    invited_by: Optional[str] = None


def _now_ms() -> int:
    return int(time.time() * 1000)


class SpaceService:
    """本地 spaces 表 CRUD + 当前激活 space 的状态管理。"""

    # 约定：空字符串代表个人空间（不落库）。
    PERSONAL_SPACE_ID = ""

    def __init__(self, repository):
        """repository: core.repository.ClipboardRepository 实例（通过 .db 拿 DB manager）。"""
        self._repo = repository
        self._db = repository.db
        self._current_space_id: Optional[str] = None  # None 表示个人
        self._logger = logger

    # ========== 空间 CRUD ==========

    def list_spaces(self) -> List[Space]:
        sql = (
            "SELECT id, name, type, owner_user_id, created_at, updated_at "
            "FROM spaces ORDER BY created_at ASC"
        )

        def op(conn):
            return self._db.fetch_all(conn, sql)

        rows = self._db.execute_read(op)
        return [self._row_to_space(row) for row in rows]

    def get_space(self, space_id: str) -> Optional[Space]:
        if not space_id:
            return None
        sql = (
            "SELECT id, name, type, owner_user_id, created_at, updated_at "
            "FROM spaces WHERE id = ?"
        )

        def op(conn):
            return self._db.fetch_one(conn, sql, (space_id,))

        row = self._db.execute_read(op)
        return self._row_to_space(row) if row else None

    def create_space(
        self,
        name: str,
        type_: str = "personal",
        owner_user_id: str = "",
    ) -> Space:
        space_id = str(uuid.uuid4())
        now = _now_ms()
        sql = (
            "INSERT INTO spaces (id, name, type, owner_user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )

        def op(conn):
            self._db.execute_write(
                conn, sql, (space_id, name, type_, owner_user_id, now, now)
            )

        self._db.execute_with_retry(op)
        return Space(
            id=space_id,
            name=name,
            type=type_,
            owner_user_id=owner_user_id,
            created_at=now,
            updated_at=now,
        )

    def update_space(self, space_id: str, name: str) -> Space:
        now = _now_ms()
        sql = "UPDATE spaces SET name = ?, updated_at = ? WHERE id = ?"

        def op(conn):
            self._db.execute_write(conn, sql, (name, now, space_id))

        self._db.execute_with_retry(op)
        found = self.get_space(space_id)
        if not found:
            raise ValueError(f"Space {space_id} 不存在")
        return found

    def delete_space(self, space_id: str) -> None:
        """删除 space 本身及其成员。clipboard_items.space_id 由调用方迁移（不在此服务）。"""
        def op(conn):
            self._db.execute_write(
                conn, "DELETE FROM space_members WHERE space_id = ?", (space_id,)
            )
            self._db.execute_write(
                conn, "DELETE FROM spaces WHERE id = ?", (space_id,)
            )

        self._db.execute_with_retry(op)
        # 当前激活的 space 被删 → 自动回到个人
        if self._current_space_id == space_id:
            self._current_space_id = None

    # ========== 成员 ==========

    def list_members(self, space_id: str) -> List[SpaceMember]:
        sql = (
            "SELECT space_id, user_id, role, joined_at, invited_by "
            "FROM space_members WHERE space_id = ? ORDER BY joined_at ASC"
        )

        def op(conn):
            return self._db.fetch_all(conn, sql, (space_id,))

        rows = self._db.execute_read(op)
        return [self._row_to_member(row) for row in rows]

    def add_member(
        self,
        space_id: str,
        user_id: str,
        role: str,
        invited_by: str = "",
    ) -> SpaceMember:
        now = _now_ms()
        inviter = invited_by if invited_by else None
        sql = (
            "INSERT INTO space_members (space_id, user_id, role, joined_at, invited_by) "
            "VALUES (?, ?, ?, ?, ?)"
        )

        def op(conn):
            self._db.execute_write(conn, sql, (space_id, user_id, role, now, inviter))

        self._db.execute_with_retry(op)
        return SpaceMember(
            space_id=space_id,
            user_id=user_id,
            role=role,
            joined_at=now,
            invited_by=inviter,
        )

    def remove_member(self, space_id: str, user_id: str) -> None:
        sql = "DELETE FROM space_members WHERE space_id = ? AND user_id = ?"

        def op(conn):
            self._db.execute_write(conn, sql, (space_id, user_id))

        self._db.execute_with_retry(op)

    def update_member_role(self, space_id: str, user_id: str, role: str) -> None:
        sql = "UPDATE space_members SET role = ? WHERE space_id = ? AND user_id = ?"

        def op(conn):
            self._db.execute_write(conn, sql, (role, space_id, user_id))

        self._db.execute_with_retry(op)

    # ========== 当前激活 space ==========

    def get_current_space_id(self) -> Optional[str]:
        """None 或 空字符串 = 个人空间。"""
        return self._current_space_id or None

    def set_current_space(self, space_id: Optional[str]) -> None:
        """切换到指定 space；None 或 "" 表示个人空间。"""
        if space_id in (None, ""):
            self._current_space_id = None
            return
        # 防呆：切换到不存在的 space 时拒绝
        if self.get_space(space_id) is None:
            raise ValueError(f"Space {space_id} 不存在，无法切换")
        self._current_space_id = space_id

    # ========== 便利方法（云端同步回来落本地） ==========

    def upsert_from_remote(self, space_dict: dict) -> Space:
        """从云端同步回来的 space 数据落本地。space_dict 字段见 /api/v1/spaces 返回。"""
        space_id = str(space_dict["id"])
        name = str(space_dict.get("name") or "")
        type_ = str(space_dict.get("type") or "personal")
        owner = str(space_dict.get("owner_user_id") or "")
        created = int(space_dict.get("created_at") or _now_ms())
        updated = int(space_dict.get("updated_at") or created)

        # 判断是 INSERT 还是 UPDATE
        existing = self.get_space(space_id)
        if existing is None:
            def op_insert(conn):
                self._db.execute_write(
                    conn,
                    "INSERT INTO spaces (id, name, type, owner_user_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (space_id, name, type_, owner, created, updated),
                )
            self._db.execute_with_retry(op_insert)
        else:
            def op_update(conn):
                self._db.execute_write(
                    conn,
                    "UPDATE spaces SET name = ?, type = ?, owner_user_id = ?, "
                    "created_at = ?, updated_at = ? WHERE id = ?",
                    (name, type_, owner, created, updated, space_id),
                )
            self._db.execute_with_retry(op_update)

        return Space(
            id=space_id,
            name=name,
            type=type_,
            owner_user_id=owner,
            created_at=created,
            updated_at=updated,
        )

    def upsert_member_from_remote(self, member_dict: dict) -> SpaceMember:
        space_id = str(member_dict["space_id"])
        user_id = str(member_dict["user_id"])
        role = str(member_dict.get("role") or "editor")
        joined = int(member_dict.get("joined_at") or _now_ms())
        invited_by_raw = member_dict.get("invited_by")
        invited_by = str(invited_by_raw) if invited_by_raw else None

        # SQLite 用 INSERT OR REPLACE；MySQL 走 ON DUPLICATE KEY UPDATE。
        if getattr(self._db, "is_mysql", False):
            sql = (
                "INSERT INTO space_members (space_id, user_id, role, joined_at, invited_by) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON DUPLICATE KEY UPDATE role = VALUES(role), joined_at = VALUES(joined_at), "
                "invited_by = VALUES(invited_by)"
            )
        else:
            sql = (
                "INSERT OR REPLACE INTO space_members "
                "(space_id, user_id, role, joined_at, invited_by) "
                "VALUES (?, ?, ?, ?, ?)"
            )

        def op(conn):
            self._db.execute_write(
                conn, sql, (space_id, user_id, role, joined, invited_by)
            )

        self._db.execute_with_retry(op)
        return SpaceMember(
            space_id=space_id,
            user_id=user_id,
            role=role,
            joined_at=joined,
            invited_by=invited_by,
        )

    # ========== internal ==========

    @staticmethod
    def _row_to_space(row) -> Space:
        return Space(
            id=str(row["id"]),
            name=str(row["name"] or ""),
            type=str(row["type"] or "personal"),
            owner_user_id=str(row["owner_user_id"] or ""),
            created_at=int(row["created_at"] or 0),
            updated_at=int(row["updated_at"] or 0),
        )

    @staticmethod
    def _row_to_member(row) -> SpaceMember:
        invited_by = row["invited_by"]
        return SpaceMember(
            space_id=str(row["space_id"]),
            user_id=str(row["user_id"]),
            role=str(row["role"] or "editor"),
            joined_at=int(row["joined_at"] or 0),
            invited_by=str(invited_by) if invited_by else None,
        )
