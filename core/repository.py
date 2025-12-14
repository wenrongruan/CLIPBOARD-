import logging
from typing import List, Optional, Tuple, Union, Any

from .database import DatabaseManager
from .models import ClipboardItem, ContentType

logger = logging.getLogger(__name__)

# 检查是否有 MySQL 支持
try:
    from .mysql_database import MySQLDatabaseManager
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    MySQLDatabaseManager = None


class ClipboardRepository:
    def __init__(self, db_manager: Union[DatabaseManager, "MySQLDatabaseManager"]):
        self.db = db_manager
        # 检测数据库类型以选择正确的占位符
        self._is_mysql = MYSQL_AVAILABLE and isinstance(db_manager, MySQLDatabaseManager)

    def _execute_query(self, conn, sql: str, params: tuple = ()) -> Any:
        """执行查询，自动适配 SQLite/MySQL"""
        if self._is_mysql:
            # MySQL 使用 %s 占位符
            sql = sql.replace("?", "%s")
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor
        else:
            # SQLite 使用 ? 占位符
            return conn.execute(sql, params)

    def _fetchone(self, conn, sql: str, params: tuple = ()) -> Optional[tuple]:
        """获取单行结果"""
        if self._is_mysql:
            sql = sql.replace("?", "%s")
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                if row:
                    # 将字典转换为元组（按字段顺序）
                    return tuple(row.values()) if isinstance(row, dict) else row
                return None
        else:
            cursor = conn.execute(sql, params)
            return cursor.fetchone()

    def _fetchall(self, conn, sql: str, params: tuple = ()) -> List[tuple]:
        """获取所有结果"""
        if self._is_mysql:
            sql = sql.replace("?", "%s")
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                # 将字典列表转换为元组列表
                return [tuple(row.values()) if isinstance(row, dict) else row for row in rows]
        else:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    def add_item(self, item: ClipboardItem) -> int:
        def operation(conn) -> int:
            sql = """
                INSERT INTO clipboard_items (
                    content_type, text_content, image_data, image_thumbnail,
                    content_hash, preview, device_id, device_name,
                    created_at, is_starred
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = item.to_db_tuple()

            if self._is_mysql:
                sql = sql.replace("?", "%s")
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.lastrowid
            else:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid

        return self.db.execute_with_retry(operation)

    def get_by_hash(self, content_hash: str) -> Optional[ClipboardItem]:
        def operation(conn) -> Optional[ClipboardItem]:
            sql = """
                SELECT id, content_type, text_content, image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                WHERE content_hash = ?
            """
            row = self._fetchone(conn, sql, (content_hash,))
            if row:
                return ClipboardItem.from_db_row(row)
            return None

        return self.db.execute_read(operation)

    def get_items(
        self, page: int = 0, page_size: int = 10
    ) -> Tuple[List[ClipboardItem], int]:
        def operation(conn) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size

            # 获取总数
            row = self._fetchone(conn, "SELECT COUNT(*) FROM clipboard_items")
            total = row[0] if row else 0

            # 获取分页数据（不加载完整图片数据以提高性能）
            sql = """
                SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            rows = self._fetchall(conn, sql, (page_size, offset))
            items = [ClipboardItem.from_db_row(row) for row in rows]
            return items, total

        return self.db.execute_read(operation)

    def get_item_by_id(self, item_id: int) -> Optional[ClipboardItem]:
        def operation(conn) -> Optional[ClipboardItem]:
            sql = """
                SELECT id, content_type, text_content, image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                WHERE id = ?
            """
            row = self._fetchone(conn, sql, (item_id,))
            if row:
                return ClipboardItem.from_db_row(row)
            return None

        return self.db.execute_read(operation)

    def search(
        self, query: str, page: int = 0, page_size: int = 10
    ) -> Tuple[List[ClipboardItem], int]:
        def operation(conn) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size
            like_query = f"%{query}%"

            # 获取总数
            count_sql = """
                SELECT COUNT(*) FROM clipboard_items
                WHERE text_content LIKE ? OR preview LIKE ?
            """
            row = self._fetchone(conn, count_sql, (like_query, like_query))
            total = row[0] if row else 0

            # 获取分页数据
            sql = """
                SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                WHERE text_content LIKE ? OR preview LIKE ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            rows = self._fetchall(conn, sql, (like_query, like_query, page_size, offset))
            items = [ClipboardItem.from_db_row(row) for row in rows]
            return items, total

        return self.db.execute_read(operation)

    def delete_item(self, item_id: int) -> bool:
        def operation(conn) -> bool:
            sql = "DELETE FROM clipboard_items WHERE id = ?"
            if self._is_mysql:
                sql = sql.replace("?", "%s")
                with conn.cursor() as cursor:
                    cursor.execute(sql, (item_id,))
                    return cursor.rowcount > 0
            else:
                cursor = conn.execute(sql, (item_id,))
                return cursor.rowcount > 0

        return self.db.execute_with_retry(operation)

    def toggle_star(self, item_id: int) -> bool:
        def operation(conn) -> bool:
            sql = """
                UPDATE clipboard_items
                SET is_starred = CASE WHEN is_starred = 1 THEN 0 ELSE 1 END
                WHERE id = ?
            """
            if self._is_mysql:
                sql = sql.replace("?", "%s")
                with conn.cursor() as cursor:
                    cursor.execute(sql, (item_id,))
                    return cursor.rowcount > 0
            else:
                cursor = conn.execute(sql, (item_id,))
                return cursor.rowcount > 0

        return self.db.execute_with_retry(operation)

    def get_new_items_since(
        self, since_id: int, exclude_device_id: str
    ) -> List[ClipboardItem]:
        def operation(conn) -> List[ClipboardItem]:
            sql = """
                SELECT id, content_type, text_content, image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                WHERE id > ? AND device_id != ?
                ORDER BY id ASC
                LIMIT 100
            """
            rows = self._fetchall(conn, sql, (since_id, exclude_device_id))
            return [ClipboardItem.from_db_row(row) for row in rows]

        return self.db.execute_read(operation)

    def cleanup_old_items(self, max_items: int = 10000) -> int:
        def operation(conn) -> int:
            # 获取当前非收藏记录数
            row = self._fetchone(conn, "SELECT COUNT(*) FROM clipboard_items WHERE is_starred = 0")
            count = row[0] if row else 0

            if count <= max_items:
                return 0

            # 计算需要删除的数量
            delete_count = count - max_items

            # 删除最旧的非收藏记录
            if self._is_mysql:
                # MySQL 不支持 DELETE 中使用 LIMIT 子查询，需要用不同方式
                sql = """
                    DELETE FROM clipboard_items
                    WHERE is_starred = 0
                    ORDER BY created_at ASC
                    LIMIT %s
                """
                with conn.cursor() as cursor:
                    cursor.execute(sql, (delete_count,))
                    deleted = cursor.rowcount
            else:
                sql = """
                    DELETE FROM clipboard_items
                    WHERE id IN (
                        SELECT id FROM clipboard_items
                        WHERE is_starred = 0
                        ORDER BY created_at ASC
                        LIMIT ?
                    )
                """
                cursor = conn.execute(sql, (delete_count,))
                deleted = cursor.rowcount

            logger.info(f"清理了 {deleted} 条旧记录")
            return deleted

        return self.db.execute_with_retry(operation)

    def get_latest_id(self) -> int:
        def operation(conn) -> int:
            row = self._fetchone(conn, "SELECT MAX(id) FROM clipboard_items")
            result = row[0] if row else 0
            return result if result else 0

        return self.db.execute_read(operation)
