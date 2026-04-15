import logging
import sqlite3
import time
from typing import List, Optional, Tuple

from .base_database import AbstractDatabaseManager
from .models import ClipboardItem

logger = logging.getLogger(__name__)

# pymysql 在纯 SQLite 部署中可能未安装，兜底为不存在的占位异常，避免 import 失败。
try:
    import pymysql  # type: ignore

    _PyMySQLIntegrityError = pymysql.err.IntegrityError  # type: ignore[attr-defined]
except ImportError:
    class _PyMySQLIntegrityError(Exception):
        pass

# 用于 except 元组：两个后端的 UNIQUE 冲突都会落在这里。
_INTEGRITY_ERRORS: tuple = (sqlite3.IntegrityError, _PyMySQLIntegrityError)


class ClipboardRepository:
    # 所有 SELECT 查询共用的字段列表（与 ClipboardItem.from_db_row dict 键一致）
    _SELECT_FIELDS = (
        "id, content_type, text_content, image_data, image_thumbnail, "
        "content_hash, preview, device_id, device_name, "
        "created_at, is_starred, cloud_id"
    )
    # 列表查询时跳过完整图片数据以提高性能
    _SELECT_FIELDS_NO_IMAGE = (
        "id, content_type, text_content, NULL as image_data, image_thumbnail, "
        "content_hash, preview, device_id, device_name, "
        "created_at, is_starred, cloud_id"
    )

    def __init__(self, db_manager: AbstractDatabaseManager):
        self.db = db_manager
        # 仅保留方言标识，SQL 执行全部委托给 db_manager
        self._is_mysql = db_manager.is_mysql
        self._has_fts = self._detect_fts()

    def _detect_fts(self) -> bool:
        """检测 FTS5 表是否存在（仅 SQLite 适用）"""
        if self._is_mysql:
            return False
        try:
            def operation(conn):
                row = self.db.fetch_one(
                    conn,
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='clipboard_fts'",
                )
                return row is not None
            return self.db.execute_read(operation)
        except Exception as e:
            logger.debug(f"FTS 检测失败: {e}")
            return False

    # 方言透明的短别名，保持现有方法体的可读性
    def _execute_write(self, conn, sql: str, params: tuple = ()) -> tuple:
        return self.db.execute_write(conn, sql, params)

    def _fetchone(self, conn, sql: str, params: tuple = ()):
        return self.db.fetch_one(conn, sql, params)

    def _fetchall(self, conn, sql: str, params: tuple = ()) -> list:
        return self.db.fetch_all(conn, sql, params)

    def _scalar(self, conn, sql: str, params: tuple = (), default=0):
        return self.db.fetch_scalar(conn, sql, params, default)

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

        try:
            return self.db.execute_with_retry(operation)
        except _INTEGRITY_ERRORS:
            # content_hash UNIQUE 冲突视为"已存在"，降噪为 debug 并返回现有 id。
            # Why: 剪贴板监控偶发重复写入（跨设备同步窗口期、连续轮询到同一内容），
            # IntegrityError 冒泡会污染日志且打断调用链。
            existing = self.get_by_hash(item.content_hash)
            if existing is not None and existing.id:
                logger.debug(
                    "add_item 遇到 content_hash 冲突，返回已有 id=%s", existing.id
                )
                return existing.id
            # 极少见：冲突但又查不到（竞态/其它约束），继续冒泡让上层处理
            raise

    def get_by_hash(self, content_hash: str) -> Optional[ClipboardItem]:
        def operation(conn) -> Optional[ClipboardItem]:
            sql = f"""
                SELECT {self._SELECT_FIELDS_NO_IMAGE}
                FROM clipboard_items
                WHERE content_hash = ?
            """
            row = self._fetchone(conn, sql, (content_hash,))
            if row:
                return ClipboardItem.from_db_row(row)
            return None

        return self.db.execute_read(operation)

    def get_existing_hashes(self, hashes: list) -> dict:
        """批量查询已存在的 content_hash，返回 {hash: ClipboardItem}"""
        if not hashes:
            return {}

        def operation(conn) -> dict:
            result = {}
            # SQLite 参数上限 999，分批查询
            batch_size = 500
            for i in range(0, len(hashes), batch_size):
                batch = hashes[i:i + batch_size]
                placeholders = ",".join("?" * len(batch))
                sql = f"""
                    SELECT {self._SELECT_FIELDS_NO_IMAGE}
                    FROM clipboard_items
                    WHERE content_hash IN ({placeholders})
                """
                rows = self._fetchall(conn, sql, tuple(batch))
                for row in rows:
                    item = ClipboardItem.from_db_row(row)
                    result[item.content_hash] = item
            return result

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
            total = self._scalar(conn, count_sql)

            # 获取分页数据（不加载完整图片数据以提高性能）
            where_clause = "WHERE is_starred = 1" if starred_only else ""
            sql = f"""
                SELECT {self._SELECT_FIELDS_NO_IMAGE}
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

            total = self._scalar(conn, "SELECT COUNT(*) FROM clipboard_items")

            sql = f"""
                SELECT {self._SELECT_FIELDS}
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
            sql = f"""
                SELECT {self._SELECT_FIELDS}
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
                total = self._scalar(conn, count_sql, (fts_query,))

                sql = f"""
                    SELECT {self._SELECT_FIELDS_NO_IMAGE}
                    FROM clipboard_items
                    WHERE id IN (SELECT rowid FROM clipboard_fts WHERE clipboard_fts MATCH ?){star_filter}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = self._fetchall(conn, sql, (fts_query, page_size, offset))
            else:
                # FTS5 不可用，回退到 LIKE（转义通配符）
                escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                like_query = f"%{escaped}%"
                escape_clause = " ESCAPE '\\\\'" if self._is_mysql else " ESCAPE '\\'"

                count_sql = f"""
                    SELECT COUNT(*) FROM clipboard_items
                    WHERE (text_content LIKE ?{escape_clause} OR preview LIKE ?{escape_clause}){star_filter}
                """
                total = self._scalar(conn, count_sql, (like_query, like_query))

                sql = f"""
                    SELECT {self._SELECT_FIELDS_NO_IMAGE}
                    FROM clipboard_items
                    WHERE (text_content LIKE ?{escape_clause} OR preview LIKE ?{escape_clause}){star_filter}
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
            sql = f"""
                SELECT {self._SELECT_FIELDS_NO_IMAGE}
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
            count = self._scalar(conn, "SELECT COUNT(*) FROM clipboard_items WHERE is_starred = 0")

            if count <= max_items:
                return 0

            # 计算需要删除的数量
            delete_count = count - max_items

            # 删除最旧的非收藏记录（MySQL 不支持 DELETE 中引用子查询的同表，需走不同 SQL）
            if self._is_mysql:
                sql = """
                    DELETE FROM clipboard_items
                    WHERE is_starred = 0
                    ORDER BY created_at ASC
                    LIMIT ?
                """
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
            deleted, _ = self._execute_write(conn, sql, (delete_count,))

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

    def set_cloud_id(self, item_id: int, cloud_id: int):
        """标记本地条目已同步到云端"""
        def operation(conn):
            sql = "UPDATE clipboard_items SET cloud_id = ? WHERE id = ?"
            self._execute_write(conn, sql, (cloud_id, item_id))

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
            self._execute_write(conn, sql, (item_id,))

        self.db.execute_with_retry(operation)

    def get_by_cloud_id(self, cloud_id: int) -> Optional[ClipboardItem]:
        """通过云端 ID 查找本地条目"""
        def operation(conn) -> Optional[ClipboardItem]:
            sql = f"""
                SELECT {self._SELECT_FIELDS}
                FROM clipboard_items
                WHERE cloud_id = ?
            """
            row = self._fetchone(conn, sql, (cloud_id,))
            if row:
                return ClipboardItem.from_db_row(row)
            return None

        return self.db.execute_read(operation)

    def get_latest_id(self) -> int:
        def operation(conn) -> int:
            result = self._scalar(conn, "SELECT MAX(id) FROM clipboard_items")
            return result if result else 0

        return self.db.execute_read(operation)

    # ========== app_meta key-value 访问 ==========
    # Why: 少量跨会话状态（如 "永久放弃同步的 server_id 集合"）原本是
    # _SyncWorker 的实例 dict，进程重启丢失后同步游标可能再度被同一条坏记录卡死。
    # 复用已有的 app_meta 表存 JSON value，跨 SQLite / MySQL 方言透明。

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """读取 app_meta 表中的一条键值；MySQL 的 `key` 需反引号转义。"""
        sql = (
            "SELECT `value` FROM app_meta WHERE `key` = ?"
            if self._is_mysql
            else "SELECT value FROM app_meta WHERE key = ?"
        )

        def operation(conn):
            row = self._fetchone(conn, sql, (key,))
            # SQLite Row (row_factory=sqlite3.Row) 与 MySQL DictCursor 均支持 row["value"]
            return row["value"] if row else default

        try:
            return self.db.execute_read(operation)
        except Exception as e:
            logger.debug(f"读取 app_meta[{key}] 失败: {e}")
            return default

    def set_meta(self, key: str, value: str) -> None:
        """写入 app_meta 表；SQLite 用 INSERT OR REPLACE，MySQL 用 ON DUPLICATE KEY UPDATE。"""
        if self._is_mysql:
            sql = (
                "INSERT INTO app_meta (`key`, `value`) VALUES (?, ?) "
                "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)"
            )
        else:
            sql = "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)"

        def operation(conn):
            self._execute_write(conn, sql, (key, value))

        try:
            self.db.execute_with_retry(operation)
        except Exception as e:
            logger.warning(f"写入 app_meta[{key}] 失败: {e}")
