"""SyncStateDAO: 云端同步状态相关的读写。

只触碰 clipboard_items 上的 cloud_id 字段以及与云同步关联的检索路径。
不持有 DAO 引用 —— 这里都是简单的单语句操作，直接走 db_manager 即可。
"""

import logging
from typing import List, Optional

from ..base_database import AbstractDatabaseManager
from ..models import ClipboardItem
from .clipboard_dao import ClipboardDAO

logger = logging.getLogger(__name__)


class SyncStateDAO:
    """clipboard_items.cloud_id 维度的状态管理。"""

    def __init__(self, db_manager: AbstractDatabaseManager):
        self.db = db_manager

    # ------------------------------------------------------------------
    # 写：cloud_id 标记
    # ------------------------------------------------------------------

    def set_cloud_id(self, item_id: int, cloud_id: int):
        """标记本地条目已同步到云端"""
        def operation(conn):
            sql = "UPDATE clipboard_items SET cloud_id = ? WHERE id = ?"
            self.db.execute_write(conn, sql, (cloud_id, item_id))

        self.db.execute_with_retry(operation)

    def set_cloud_ids_bulk(self, pairs: list):
        """批量标记 cloud_id，pairs 为 [(item_id, cloud_id), ...]"""
        if not pairs:
            return

        def operation(conn):
            sql = "UPDATE clipboard_items SET cloud_id = ? WHERE id = ?"
            data = [(cloud_id, item_id) for item_id, cloud_id in pairs]
            self.db.execute_many(conn, sql, data)

        self.db.execute_with_retry(operation)

    def clear_cloud_id(self, item_id: int):
        """清除云端标记（云端副本已删除）"""
        def operation(conn):
            sql = "UPDATE clipboard_items SET cloud_id = NULL WHERE id = ?"
            self.db.execute_write(conn, sql, (item_id,))

        self.db.execute_with_retry(operation)

    def update_cloud_sync_metadata(
        self,
        item_id: int,
        *,
        cloud_id: Optional[int] = None,
        is_starred: Optional[bool] = None,
    ) -> None:
        """合并云端同步元数据到本地条目。

        用于"本地已存在相同 content_hash，但云端返回了 cloud_id / 收藏状态"的场景。
        """
        fields = []
        params = []
        if cloud_id is not None:
            fields.append("cloud_id = ?")
            params.append(cloud_id)
        if is_starred is not None:
            fields.append("is_starred = ?")
            params.append(1 if is_starred else 0)
        if not fields:
            return

        def operation(conn):
            sql = f"UPDATE clipboard_items SET {', '.join(fields)} WHERE id = ?"
            self.db.execute_write(conn, sql, (*params, item_id))

        self.db.execute_with_retry(operation)

    # ------------------------------------------------------------------
    # 读：基于 cloud_id 的检索
    # ------------------------------------------------------------------

    def get_by_cloud_id(self, cloud_id: int) -> Optional[ClipboardItem]:
        """通过云端 ID 查找本地条目"""
        def operation(conn) -> Optional[ClipboardItem]:
            sql = f"""
                SELECT {ClipboardDAO._SELECT_FIELDS}
                FROM clipboard_items
                WHERE cloud_id = ?
            """
            row = self.db.fetch_one(conn, sql, (cloud_id,))
            if row:
                return ClipboardItem.from_db_row(row)
            return None

        return self.db.execute_read(operation)

    def get_starred_unsynced(self, limit: int = 100) -> List[ClipboardItem]:
        """获取已收藏但未同步到云端的条目（含完整图片数据，用于推送）"""
        def operation(conn) -> List[ClipboardItem]:
            sql = f"""
                SELECT {ClipboardDAO._SELECT_FIELDS}
                FROM clipboard_items
                WHERE is_starred = 1 AND cloud_id IS NULL
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = self.db.fetch_all(conn, sql, (limit,))
            return [ClipboardItem.from_db_row(row) for row in rows]

        return self.db.execute_read(operation)

    def get_unsynced_items(self, limit: int = 20) -> List[ClipboardItem]:
        """获取未同步到云端的条目（含完整图片数据），按最新排序，用于批量推送"""
        def operation(conn) -> List[ClipboardItem]:
            sql = f"""
                SELECT {ClipboardDAO._SELECT_FIELDS}
                FROM clipboard_items
                WHERE cloud_id IS NULL
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = self.db.fetch_all(conn, sql, (limit,))
            return [ClipboardItem.from_db_row(row) for row in rows]
        return self.db.execute_read(operation)

    def get_unstarred_with_cloud_id(self, limit: int = 200) -> List[ClipboardItem]:
        """获取未收藏但有云端副本的条目，按最旧排序（用于配额清理时优先删最旧）"""
        def operation(conn) -> List[ClipboardItem]:
            sql = f"""
                SELECT {ClipboardDAO._SELECT_FIELDS_NO_IMAGE}
                FROM clipboard_items
                WHERE is_starred = 0 AND cloud_id IS NOT NULL
                ORDER BY created_at ASC
                LIMIT ?
            """
            rows = self.db.fetch_all(conn, sql, (limit,))
            return [ClipboardItem.from_db_row(row) for row in rows]

        return self.db.execute_read(operation)
