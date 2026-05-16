"""ClipboardDAO: clipboard_items / clipboard_tags / app_meta 的 CRUD 与基础访问。

设计取舍: _execute_write / _fetchone / _fetchall / _scalar 这几个薄包装保留为
"protected" 实例方法 (下划线开头)，由本包内的 ClipboardQuery / SyncStateDAO
通过持有的 dao 引用调用 (`self._dao._fetchone(...)`)。
- 优点: 单点封装，将来如果要换执行通道 (例如加追踪/重试策略) 只改一处。
- 缺点: 跨类访问下划线属性。鉴于 Query / SyncStateDAO 与 DAO 是同包同层
  且本来就是 repository.py 拆出来的内部协作者，可以接受。
"""

import logging
import sqlite3
import time
from typing import List, Optional

from ..base_database import AbstractDatabaseManager
from ..models import ClipboardItem

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


class ClipboardDAO:
    """clipboard_items 主表 + clipboard_tags 关联 + app_meta KV 的访问层。"""

    # 所有 SELECT 查询共用的字段列表（与 ClipboardItem.from_db_row dict 键一致）
    # v3.4: 末尾追加 space_id / source_app / source_title（对齐 to_db_tuple）
    _SELECT_FIELDS = (
        "id, content_type, text_content, image_data, image_thumbnail, "
        "content_hash, preview, device_id, device_name, "
        "created_at, is_starred, cloud_id, "
        "space_id, source_app, source_title"
    )
    # 列表查询时跳过完整图片数据以提高性能
    _SELECT_FIELDS_NO_IMAGE = (
        "id, content_type, text_content, NULL as image_data, image_thumbnail, "
        "content_hash, preview, device_id, device_name, "
        "created_at, is_starred, cloud_id, "
        "space_id, source_app, source_title"
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

    # 方言透明的短别名，保持方法体的可读性。
    # Query/SyncStateDAO 也通过 self._dao._fetchone 等访问这些 helper。
    def _execute_write(self, conn, sql: str, params: tuple = ()) -> tuple:
        return self.db.execute_write(conn, sql, params)

    def _fetchone(self, conn, sql: str, params: tuple = ()):
        return self.db.fetch_one(conn, sql, params)

    def _fetchall(self, conn, sql: str, params: tuple = ()) -> list:
        return self.db.fetch_all(conn, sql, params)

    def _scalar(self, conn, sql: str, params: tuple = (), default=0):
        return self.db.fetch_scalar(conn, sql, params, default)

    # ------------------------------------------------------------------
    # CRUD: clipboard_items
    # ------------------------------------------------------------------

    def add_item(self, item: ClipboardItem) -> int:
        def operation(conn) -> int:
            # v3.4: 列数从 10 增加到 13（追加 space_id / source_app / source_title）
            # 必须和 ClipboardItem.to_db_tuple() 的列顺序一一对应
            sql = """
                INSERT INTO clipboard_items (
                    content_type, text_content, image_data, image_thumbnail,
                    content_hash, preview, device_id, device_name,
                    created_at, is_starred,
                    space_id, source_app, source_title
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def get_item_by_id(self, item_id: int) -> Optional[ClipboardItem]:
        """按主键取条目。注意: 这里不回填 tag_ids；facade / query 层负责。"""
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
            # rowcount > 0 表示更新成功，但调用方关心"切换后的状态"
            # 重新读一次更稳，但旧 repository 返回 bool(rowcount>0) 语义保持。
            return rowcount > 0

        return self.db.execute_with_retry(operation)

    def update_item_content(
        self, item_id: int, text_content: Optional[str] = None,
        image_data: Optional[bytes] = None, content_type: Optional[str] = None,
    ) -> bool:
        """更新条目内容（用于插件 REPLACE 操作）。

        当 content_type 从 image 切到 text（或反向）时，另一类载荷列必须显式清空，
        否则数据库行会同时残留 image_data/image_thumbnail 和 text_content，后续读取逻辑
        可能按旧 content_type 误判。
        """
        from utils.hash_utils import compute_content_hash

        def operation(conn) -> bool:
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
                if content_type == "text":
                    fields.append("image_data = NULL")
                    fields.append("image_thumbnail = NULL")
                elif content_type == "image":
                    fields.append("text_content = NULL")
                    fields.append("preview = ?")
                    params.append("")
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

    def touch_item(self, item_id: int, created_at: int) -> bool:
        """更新条目的 created_at 让其置顶（用于重复复制时刷新时间）。"""
        def operation(conn) -> bool:
            sql = "UPDATE clipboard_items SET created_at = ? WHERE id = ?"
            rowcount, _ = self._execute_write(conn, sql, (created_at, item_id))
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

    def get_latest_id(self) -> int:
        def operation(conn) -> int:
            result = self._scalar(conn, "SELECT MAX(id) FROM clipboard_items")
            return result if result else 0

        return self.db.execute_read(operation)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # clipboard_tags 关联表
    # ------------------------------------------------------------------

    def add_tags_to_item(self, item_id: int, tag_ids: List[str]) -> None:
        """给 item 追加 tag 绑定。已存在的 (item_id, tag_id) 组合静默跳过。"""
        if not tag_ids:
            return
        now_ms = int(time.time() * 1000)

        def op(conn):
            # SQLite: INSERT OR IGNORE；MySQL: INSERT IGNORE
            if self._is_mysql:
                sql = (
                    "INSERT IGNORE INTO clipboard_tags (item_id, tag_id, created_at) "
                    "VALUES (?, ?, ?)"
                )
            else:
                sql = (
                    "INSERT OR IGNORE INTO clipboard_tags (item_id, tag_id, created_at) "
                    "VALUES (?, ?, ?)"
                )
            data = [(item_id, tid, now_ms) for tid in tag_ids]
            self.db.execute_many(conn, sql, data)

        self.db.execute_with_retry(op)

    def remove_tags_from_item(self, item_id: int, tag_ids: List[str]) -> None:
        """移除 item 上的指定 tag 绑定。"""
        if not tag_ids:
            return
        placeholders = ",".join("?" * len(tag_ids))
        sql = (
            f"DELETE FROM clipboard_tags WHERE item_id = ? AND tag_id IN ({placeholders})"
        )

        def op(conn):
            self._execute_write(conn, sql, (item_id, *tag_ids))

        self.db.execute_with_retry(op)

    def get_tags_for_item(self, item_id: int) -> List[str]:
        """返回该 item 上已绑定的 tag_id 列表。"""
        def op(conn):
            try:
                return self._fetchall(
                    conn,
                    "SELECT tag_id FROM clipboard_tags WHERE item_id = ?",
                    (item_id,),
                )
            except Exception as exc:
                logger.debug("读 clipboard_tags 失败（可能未迁移）: %s", exc)
                return []

        rows = self.db.execute_read(op)
        out: List[str] = []
        for row in rows:
            try:
                out.append(row["tag_id"])
            except (KeyError, IndexError, TypeError):
                out.append(row[0])
        return out

    # ------------------------------------------------------------------
    # app_meta key-value 访问
    # ------------------------------------------------------------------
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
