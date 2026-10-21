"""SyncStateDAO: 云端同步状态相关的读写。

管理 clipboard_items 上的 cloud_id，以及云端图片修复和同步检索路径。
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

    def restore_cloud_image(
        self,
        item_id: int,
        image_data: bytes,
        image_thumbnail: Optional[bytes],
        cloud_id: int,
    ) -> bool:
        """补齐已有图片的云端二进制，保留原始内容 hash 和其他元数据。

        云端图片可能经过压缩，不能按下载后的二进制重算 content_hash。
        只更新仍存在的图片行，避免下载完成时复活已删除的条目。
        """
        if not image_data:
            return False

        def operation(conn) -> bool:
            sql = """
                UPDATE clipboard_items
                SET image_data = ?, image_thumbnail = ?, cloud_id = ?
                WHERE id = ? AND content_type = 'image'
            """
            rowcount, _ = self.db.execute_write(
                conn, sql, (image_data, image_thumbnail, cloud_id, item_id)
            )
            if rowcount > 0:
                return True
            # MySQL 的 rowcount 默认只计实际变更；相同图片的重复修复仍算成功。
            return self.db.fetch_one(
                conn,
                "SELECT id FROM clipboard_items WHERE id = ? AND content_type = 'image'",
                (item_id,),
            ) is not None

        return self.db.execute_with_retry(operation)

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

    def get_cloud_ids_for_ids(self, item_ids: List[int]) -> dict:
        """批量查询给定 item_id 对应的 cloud_id，返回 {item_id: cloud_id 或 None}。

        仅含 item_ids 中实际存在的行；不存在的 id 不出现在结果里。
        用于 UI 在上传完成后刷新当前列表的云端标记。
        """
        if not item_ids:
            return {}

        def operation(conn):
            placeholders = ",".join("?" for _ in item_ids)
            sql = f"SELECT id, cloud_id FROM clipboard_items WHERE id IN ({placeholders})"
            rows = self.db.fetch_all(conn, sql, tuple(item_ids))
            return {row["id"]: row["cloud_id"] for row in rows}

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

    def get_image_hashes_with_data(
        self, hashes: list, space_id: Optional[str] = None
    ) -> set[str]:
        """返回目标空间内有完整图片二进制的 hash，不读取图片 BLOB。

        个人空间兼容 NULL / 空串；缩略图存在不能替代完整图片数据。
        """
        if not hashes:
            return set()

        def operation(conn) -> set[str]:
            result = set()
            # 为空间参数保留一个位置，每次最多绑定 500 个参数。
            batch_size = 499
            for offset in range(0, len(hashes), batch_size):
                batch = hashes[offset:offset + batch_size]
                placeholders = ",".join("?" for _ in batch)
                sql = f"""
                    SELECT content_hash
                    FROM clipboard_items
                    WHERE content_hash IN ({placeholders})
                      AND COALESCE(space_id, '') = ?
                      AND content_type = 'image'
                      AND image_data IS NOT NULL
                      AND LENGTH(image_data) > 0
                """
                rows = self.db.fetch_all(conn, sql, (*batch, space_id or ""))
                result.update(row["content_hash"] for row in rows)
            return result

        return self.db.execute_read(operation)
