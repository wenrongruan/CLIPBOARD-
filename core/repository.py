import logging
import time
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
        # 检测 FTS5 是否可用
        self._has_fts = self._detect_fts()

    def _detect_fts(self) -> bool:
        """检测 FTS5 表是否存在"""
        if self._is_mysql:
            return False
        try:
            def operation(conn):
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='clipboard_fts'"
                )
                return cursor.fetchone() is not None
            return self.db.execute_read(operation)
        except Exception:
            return False

    def _execute_write(self, conn, sql: str, params: tuple = ()) -> tuple:
        """执行写操作，返回 (rowcount, lastrowid)"""
        if self._is_mysql:
            sql = sql.replace("?", "%s")
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.rowcount, cursor.lastrowid
        else:
            cursor = conn.execute(sql, params)
            return cursor.rowcount, cursor.lastrowid

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
            _, lastrowid = self._execute_write(conn, sql, item.to_db_tuple())
            return lastrowid

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
        self, page: int = 0, page_size: int = 10, starred_only: bool = False
    ) -> Tuple[List[ClipboardItem], int]:
        def operation(conn) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size

            # 获取总数
            count_sql = "SELECT COUNT(*) FROM clipboard_items"
            if starred_only:
                count_sql += " WHERE is_starred = 1"
            row = self._fetchone(conn, count_sql)
            total = row[0] if row else 0

            # 获取分页数据（不加载完整图片数据以提高性能）
            where_clause = "WHERE is_starred = 1" if starred_only else ""
            sql = f"""
                SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            rows = self._fetchall(conn, sql, (page_size, offset))
            items = [ClipboardItem.from_db_row(row) for row in rows]
            return items, total

        return self.db.execute_read(operation)

    def get_items_full(
        self, page: int = 0, page_size: int = 100
    ) -> Tuple[List[ClipboardItem], int]:
        """获取分页数据（包含完整图片数据，用于数据迁移）"""
        def operation(conn) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size

            row = self._fetchone(conn, "SELECT COUNT(*) FROM clipboard_items")
            total = row[0] if row else 0

            sql = """
                SELECT id, content_type, text_content, image_data, image_thumbnail,
                       content_hash, preview, device_id, device_name,
                       created_at, is_starred
                FROM clipboard_items
                ORDER BY created_at ASC
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
        self, query: str, page: int = 0, page_size: int = 10, starred_only: bool = False
    ) -> Tuple[List[ClipboardItem], int]:
        def operation(conn) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size
            star_filter = " AND is_starred = 1" if starred_only else ""

            if self._has_fts and not self._is_mysql:
                # 使用 FTS5 全文搜索（更快），包装为短语避免特殊字符注入
                fts_query = '"' + query.replace('"', '""') + '"'

                count_sql = f"""
                    SELECT COUNT(*) FROM clipboard_items
                    WHERE id IN (SELECT rowid FROM clipboard_fts WHERE clipboard_fts MATCH ?){star_filter}
                """
                row = self._fetchone(conn, count_sql, (fts_query,))
                total = row[0] if row else 0

                sql = f"""
                    SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                           content_hash, preview, device_id, device_name,
                           created_at, is_starred
                    FROM clipboard_items
                    WHERE id IN (SELECT rowid FROM clipboard_fts WHERE clipboard_fts MATCH ?){star_filter}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = self._fetchall(conn, sql, (fts_query, page_size, offset))
            else:
                # FTS5 不可用，回退到 LIKE
                like_query = f"%{query}%"

                count_sql = f"""
                    SELECT COUNT(*) FROM clipboard_items
                    WHERE (text_content LIKE ? OR preview LIKE ?){star_filter}
                """
                row = self._fetchone(conn, count_sql, (like_query, like_query))
                total = row[0] if row else 0

                sql = f"""
                    SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
                           content_hash, preview, device_id, device_name,
                           created_at, is_starred
                    FROM clipboard_items
                    WHERE (text_content LIKE ? OR preview LIKE ?){star_filter}
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
            rowcount, _ = self._execute_write(conn, sql, (item_id,))
            return rowcount > 0

        return self.db.execute_with_retry(operation)

    def toggle_star(self, item_id: int) -> bool:
        def operation(conn) -> bool:
            sql = """
                UPDATE clipboard_items
                SET is_starred = CASE WHEN is_starred = 1 THEN 0 ELSE 1 END
                WHERE id = ?
            """
            rowcount, _ = self._execute_write(conn, sql, (item_id,))
            return rowcount > 0

        return self.db.execute_with_retry(operation)

    def get_new_items_since(
        self, since_id: int, exclude_device_id: str
    ) -> List[ClipboardItem]:
        def operation(conn) -> List[ClipboardItem]:
            sql = """
                SELECT id, content_type, text_content, NULL as image_data, image_thumbnail,
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

    def cleanup_expired_items(self, retention_days: int) -> int:
        """删除超过保留天数的非收藏记录"""
        cutoff_ms = int((time.time() - retention_days * 86400) * 1000)

        def operation(conn) -> int:
            sql = "DELETE FROM clipboard_items WHERE is_starred = 0 AND created_at < ?"
            deleted, _ = self._execute_write(conn, sql, (cutoff_ms,))
            if deleted > 0:
                logger.info(f"清理了 {deleted} 条过期记录 (超过 {retention_days} 天)")
            return deleted

        return self.db.execute_with_retry(operation)

    def update_item_content(
        self, item_id: int, text_content: Optional[str] = None,
        image_data: Optional[bytes] = None, content_type: Optional[str] = None,
    ) -> bool:
        """更新条目内容（用于插件 REPLACE 操作）"""
        from utils.hash_utils import compute_content_hash

        def operation(conn) -> bool:
            # 构建动态 UPDATE
            fields = []
            params = []
            hash_source = None
            if text_content is not None:
                fields.append("text_content = ?")
                params.append(text_content)
                fields.append("preview = ?")
                params.append(text_content[:100] if text_content else "")
                hash_source = text_content
            if image_data is not None:
                fields.append("image_data = ?")
                params.append(image_data)
                hash_source = image_data
            if content_type is not None:
                fields.append("content_type = ?")
                params.append(content_type)
            if hash_source is not None:
                fields.append("content_hash = ?")
                params.append(compute_content_hash(hash_source))
            if not fields:
                return False
            params.append(item_id)
            sql = f"UPDATE clipboard_items SET {', '.join(fields)} WHERE id = ?"
            rowcount, _ = self._execute_write(conn, sql, tuple(params))
            return rowcount > 0

        return self.db.execute_with_retry(operation)

    def get_latest_id(self) -> int:
        def operation(conn) -> int:
            row = self._fetchone(conn, "SELECT MAX(id) FROM clipboard_items")
            result = row[0] if row else 0
            return result if result else 0

        return self.db.execute_read(operation)
