"""标签定义（tag_definitions）的本地 CRUD + 便利绑定方法。

条目↔标签的关联在 clipboard_tags 表，由 ClipboardRepository 的 add_tags_to_item 管理；
本服务仅负责 tag_definitions 的增删改查，以及 "按名字打标签（缺则自动建）" 的便利方法。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TagDefinition:
    id: str
    space_id: str
    name: str
    color: Optional[str]
    created_at: int


def _now_ms() -> int:
    return int(time.time() * 1000)


class TagService:
    """tag_definitions 的 CRUD + 打标签便利方法。"""

    def __init__(self, repository):
        self._repo = repository
        self._db = repository.db

    def list_tags(self, space_id: Optional[str] = None) -> List[TagDefinition]:
        """space_id=None 返回所有 space 的标签；"" 返回个人空间（space_id == '' ）的。"""
        def op(conn):
            if space_id is None:
                sql = (
                    "SELECT id, space_id, name, color, created_at "
                    "FROM tag_definitions ORDER BY created_at ASC"
                )
                return self._db.fetch_all(conn, sql)
            sql = (
                "SELECT id, space_id, name, color, created_at "
                "FROM tag_definitions WHERE space_id = ? ORDER BY created_at ASC"
            )
            return self._db.fetch_all(conn, sql, (space_id,))

        rows = self._db.execute_read(op)
        return [self._row_to_tag(row) for row in rows]

    def create_tag(
        self,
        space_id: str,
        name: str,
        color: Optional[str] = None,
    ) -> TagDefinition:
        if not name:
            raise ValueError("tag name 不能为空")
        tag_id = str(uuid.uuid4())
        now = _now_ms()
        sql = (
            "INSERT INTO tag_definitions (id, space_id, name, color, created_at) "
            "VALUES (?, ?, ?, ?, ?)"
        )

        def op(conn):
            self._db.execute_write(conn, sql, (tag_id, space_id, name, color, now))

        self._db.execute_with_retry(op)
        return TagDefinition(
            id=tag_id,
            space_id=space_id,
            name=name,
            color=color,
            created_at=now,
        )

    def update_tag(
        self,
        tag_id: str,
        name: Optional[str] = None,
        color: Optional[str] = None,
    ) -> TagDefinition:
        fields = []
        params: list = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if color is not None:
            fields.append("color = ?")
            params.append(color)
        if not fields:
            # 无事可做 → 直接返回现状（若不存在则抛错）
            current = self.get_tag(tag_id)
            if current is None:
                raise ValueError(f"tag {tag_id} 不存在")
            return current
        params.append(tag_id)
        sql = f"UPDATE tag_definitions SET {', '.join(fields)} WHERE id = ?"

        def op(conn):
            self._db.execute_write(conn, sql, tuple(params))

        self._db.execute_with_retry(op)
        current = self.get_tag(tag_id)
        if current is None:
            raise ValueError(f"tag {tag_id} 不存在")
        return current

    def delete_tag(self, tag_id: str) -> None:
        """级联删除 clipboard_tags 里的关联。"""
        def op(conn):
            self._db.execute_write(
                conn, "DELETE FROM clipboard_tags WHERE tag_id = ?", (tag_id,)
            )
            self._db.execute_write(
                conn, "DELETE FROM tag_definitions WHERE id = ?", (tag_id,)
            )

        self._db.execute_with_retry(op)

    def get_tag(self, tag_id: str) -> Optional[TagDefinition]:
        sql = (
            "SELECT id, space_id, name, color, created_at "
            "FROM tag_definitions WHERE id = ?"
        )

        def op(conn):
            return self._db.fetch_one(conn, sql, (tag_id,))

        row = self._db.execute_read(op)
        return self._row_to_tag(row) if row else None

    def get_tag_by_name(self, space_id: str, name: str) -> Optional[TagDefinition]:
        sql = (
            "SELECT id, space_id, name, color, created_at "
            "FROM tag_definitions WHERE space_id = ? AND name = ?"
        )

        def op(conn):
            return self._db.fetch_one(conn, sql, (space_id, name))

        row = self._db.execute_read(op)
        return self._row_to_tag(row) if row else None

    # ========== 打标签便利方法 ==========

    def apply_tag_names(
        self,
        item_id: int,
        space_id: str,
        tag_names: List[str],
    ) -> List[str]:
        """为 item 打标签，不存在的 tag_name 自动创建。返回 tag_id 列表。

        不会清除原有标签（append 语义）；若需要 replace 请由上层先删再打。
        使用 INSERT OR IGNORE 保证 (item_id, tag_id) 幂等。
        """
        if not tag_names:
            return []

        # 去重（保持顺序）
        deduped: list = []
        seen = set()
        for n in tag_names:
            if n and n not in seen:
                seen.add(n)
                deduped.append(n)

        tag_ids: List[str] = []
        for name in deduped:
            existing = self.get_tag_by_name(space_id, name)
            if existing is None:
                existing = self.create_tag(space_id, name)
            tag_ids.append(existing.id)

        now = _now_ms()
        is_mysql = getattr(self._db, "is_mysql", False)
        sql = (
            "INSERT IGNORE INTO clipboard_tags (item_id, tag_id, created_at) VALUES (?, ?, ?)"
            if is_mysql
            else "INSERT OR IGNORE INTO clipboard_tags (item_id, tag_id, created_at) VALUES (?, ?, ?)"
        )

        def op(conn):
            for tid in tag_ids:
                self._db.execute_write(conn, sql, (item_id, tid, now))

        self._db.execute_with_retry(op)
        return tag_ids

    # ========== internal ==========

    @staticmethod
    def _row_to_tag(row) -> TagDefinition:
        color_val = row["color"]
        return TagDefinition(
            id=str(row["id"]),
            space_id=str(row["space_id"] or ""),
            name=str(row["name"] or ""),
            color=str(color_val) if color_val else None,
            created_at=int(row["created_at"] or 0),
        )
