import sqlite3
import logging
from typing import List, Optional, Tuple

from .database import DatabaseManager
from .models import ClipboardItem, ContentType

logger = logging.getLogger(__name__)


class ClipboardRepository:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add_item(self, item: ClipboardItem) -> int:
        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                """
                INSERT INTO clipboard_items (
                    content_type, text_content, image_data, image_thumbnail,
                    content_hash, preview, device_id, device_name,
                    created_at, is_starred
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                item.to_db_tuple(),
            )
            return cursor.lastrowid

        return self.db.execute_with_retry(operation)

    def get_by_hash(self, content_hash: str) -> Optional[ClipboardItem]:
        def operation(conn: sqlite3.Connection) -> Optional[ClipboardItem]:
            cursor = conn.execute(
                """
                SELECT id, content_type, text_content, image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                WHERE content_hash = ?
                """,
                (content_hash,),
            )
            row = cursor.fetchone()
            if row:
                return ClipboardItem.from_db_row(row)
            return None

        return self.db.execute_read(operation)

    def get_items(
        self, page: int = 0, page_size: int = 10
    ) -> Tuple[List[ClipboardItem], int]:
        def operation(conn: sqlite3.Connection) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size

            # 获取总数
            cursor = conn.execute("SELECT COUNT(*) FROM clipboard_items")
            total = cursor.fetchone()[0]

            # 获取分页数据（不加载完整图片数据以提高性能）
            cursor = conn.execute(
                """
                SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )

            items = [ClipboardItem.from_db_row(row) for row in cursor.fetchall()]
            return items, total

        return self.db.execute_read(operation)

    def get_item_by_id(self, item_id: int) -> Optional[ClipboardItem]:
        def operation(conn: sqlite3.Connection) -> Optional[ClipboardItem]:
            cursor = conn.execute(
                """
                SELECT id, content_type, text_content, image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                WHERE id = ?
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            if row:
                return ClipboardItem.from_db_row(row)
            return None

        return self.db.execute_read(operation)

    def search(
        self, query: str, page: int = 0, page_size: int = 10
    ) -> Tuple[List[ClipboardItem], int]:
        def operation(conn: sqlite3.Connection) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size

            # 尝试使用FTS搜索
            try:
                # 获取匹配总数
                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM clipboard_items
                    WHERE id IN (SELECT rowid FROM clipboard_fts WHERE clipboard_fts MATCH ?)
                    """,
                    (query,),
                )
                total = cursor.fetchone()[0]

                # 获取分页数据
                cursor = conn.execute(
                    """
                    SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                           content_hash, preview, device_id, device_name,
                           created_at, is_starred
                    FROM clipboard_items
                    WHERE id IN (SELECT rowid FROM clipboard_fts WHERE clipboard_fts MATCH ?)
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (query, page_size, offset),
                )
                items = [ClipboardItem.from_db_row(row) for row in cursor.fetchall()]

            except sqlite3.OperationalError:
                # FTS不可用，回退到LIKE搜索
                like_query = f"%{query}%"

                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM clipboard_items
                    WHERE text_content LIKE ? OR preview LIKE ?
                    """,
                    (like_query, like_query),
                )
                total = cursor.fetchone()[0]

                cursor = conn.execute(
                    """
                    SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                           content_hash, preview, device_id, device_name,
                           created_at, is_starred
                    FROM clipboard_items
                    WHERE text_content LIKE ? OR preview LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (like_query, like_query, page_size, offset),
                )
                items = [ClipboardItem.from_db_row(row) for row in cursor.fetchall()]

            return items, total

        return self.db.execute_read(operation)

    def delete_item(self, item_id: int) -> bool:
        def operation(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM clipboard_items WHERE id = ?", (item_id,)
            )
            return cursor.rowcount > 0

        return self.db.execute_with_retry(operation)

    def toggle_star(self, item_id: int) -> bool:
        def operation(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                """
                UPDATE clipboard_items
                SET is_starred = CASE WHEN is_starred = 1 THEN 0 ELSE 1 END
                WHERE id = ?
                """,
                (item_id,),
            )
            return cursor.rowcount > 0

        return self.db.execute_with_retry(operation)

    def get_new_items_since(
        self, since_id: int, exclude_device_id: str
    ) -> List[ClipboardItem]:
        def operation(conn: sqlite3.Connection) -> List[ClipboardItem]:
            cursor = conn.execute(
                """
                SELECT id, content_type, text_content, image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                WHERE id > ? AND device_id != ?
                ORDER BY id ASC
                LIMIT 100
                """,
                (since_id, exclude_device_id),
            )
            return [ClipboardItem.from_db_row(row) for row in cursor.fetchall()]

        return self.db.execute_read(operation)

    def cleanup_old_items(self, max_items: int = 10000) -> int:
        def operation(conn: sqlite3.Connection) -> int:
            # 获取当前非收藏记录数
            cursor = conn.execute(
                "SELECT COUNT(*) FROM clipboard_items WHERE is_starred = 0"
            )
            count = cursor.fetchone()[0]

            if count <= max_items:
                return 0

            # 计算需要删除的数量
            delete_count = count - max_items

            # 删除最旧的非收藏记录
            cursor = conn.execute(
                """
                DELETE FROM clipboard_items
                WHERE id IN (
                    SELECT id FROM clipboard_items
                    WHERE is_starred = 0
                    ORDER BY created_at ASC
                    LIMIT ?
                )
                """,
                (delete_count,),
            )
            deleted = cursor.rowcount
            logger.info(f"清理了 {deleted} 条旧记录")
            return deleted

        return self.db.execute_with_retry(operation)

    def get_latest_id(self) -> int:
        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "SELECT MAX(id) FROM clipboard_items"
            )
            result = cursor.fetchone()[0]
            return result if result else 0

        return self.db.execute_read(operation)
