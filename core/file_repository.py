"""云端文件表（cloud_files / cloud_file_upload_parts）CRUD 封装。

与 ClipboardRepository 分开，避免文件同步改到剪贴板主路径。
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from .base_database import AbstractDatabaseManager
from .file_models import CloudFile, FileSyncState

logger = logging.getLogger(__name__)


class CloudFileRepository:
    _SELECT_FIELDS = (
        "id, cloud_id, name, original_path, local_path, size_bytes, "
        "mime_type, content_sha256, mtime, device_id, device_name, "
        "created_at, is_deleted, sync_state, last_error, bookmark"
    )
    # 列表视图不需要 bookmark（可能几 KB）。用 NULL 填充保持 from_db_row 字段顺序。
    _SELECT_FIELDS_NO_BOOKMARK = (
        "id, cloud_id, name, original_path, local_path, size_bytes, "
        "mime_type, content_sha256, mtime, device_id, device_name, "
        "created_at, is_deleted, sync_state, last_error, NULL as bookmark"
    )

    def __init__(self, db_manager: AbstractDatabaseManager):
        self.db = db_manager
        self._is_mysql = db_manager.is_mysql

    # ========== Files CRUD ==========

    def add_file(self, f: CloudFile) -> int:
        """插入新条目，返回 local id。依赖 uq_files_sha_not_deleted 做唯一约束。"""
        def op(conn) -> int:
            sql = (
                "INSERT INTO cloud_files ("
                "cloud_id, name, original_path, local_path, size_bytes, "
                "mime_type, content_sha256, mtime, device_id, device_name, "
                "created_at, is_deleted, sync_state, last_error, bookmark"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            _, lastrowid = self.db.execute_write(conn, sql, f.to_db_tuple())
            return int(lastrowid or 0)

        return self.db.execute_with_retry(op)

    def update_meta(self, file_id: int, **fields) -> bool:
        """按需更新 cloud_files 某几列（白名单保护）。"""
        allowed = {
            "cloud_id", "name", "local_path", "size_bytes", "mime_type",
            "content_sha256", "mtime", "is_deleted", "sync_state", "last_error",
            "bookmark", "original_path",
        }
        cols = [k for k in fields.keys() if k in allowed]
        if not cols:
            return False

        def op(conn) -> bool:
            assignments = ", ".join(f"{c} = ?" for c in cols)
            params = tuple(fields[c] for c in cols) + (file_id,)
            rowcount, _ = self.db.execute_write(
                conn, f"UPDATE cloud_files SET {assignments} WHERE id = ?", params
            )
            return rowcount > 0

        return self.db.execute_with_retry(op)

    def set_sync_state(self, file_id: int, state: str, last_error: str = "") -> None:
        self.update_meta(file_id, sync_state=state, last_error=last_error or None)

    def set_cloud_id(self, file_id: int, cloud_id: Optional[int]) -> None:
        self.update_meta(file_id, cloud_id=cloud_id)

    def mark_deleted(self, file_id: int) -> bool:
        return self.update_meta(
            file_id, is_deleted=1, sync_state=FileSyncState.PENDING.value,
            mtime=int(time.time() * 1000),
        )

    def hard_delete(self, file_id: int) -> bool:
        def op(conn) -> bool:
            rowcount, _ = self.db.execute_write(
                conn, "DELETE FROM cloud_files WHERE id = ?", (file_id,)
            )
            return rowcount > 0

        return self.db.execute_with_retry(op)

    def get_by_id(self, file_id: int) -> Optional[CloudFile]:
        def op(conn):
            row = self.db.fetch_one(
                conn,
                f"SELECT {self._SELECT_FIELDS} FROM cloud_files WHERE id = ?",
                (file_id,),
            )
            return CloudFile.from_db_row(row) if row else None

        return self.db.execute_read(op)

    def get_by_cloud_id(self, cloud_id: int) -> Optional[CloudFile]:
        def op(conn):
            row = self.db.fetch_one(
                conn,
                f"SELECT {self._SELECT_FIELDS} FROM cloud_files WHERE cloud_id = ?",
                (cloud_id,),
            )
            return CloudFile.from_db_row(row) if row else None

        return self.db.execute_read(op)

    def get_by_sha(self, sha: str, include_deleted: bool = False) -> Optional[CloudFile]:
        def op(conn):
            if include_deleted:
                sql = f"SELECT {self._SELECT_FIELDS} FROM cloud_files WHERE content_sha256 = ?"
                row = self.db.fetch_one(conn, sql, (sha,))
            else:
                sql = (
                    f"SELECT {self._SELECT_FIELDS} FROM cloud_files "
                    "WHERE content_sha256 = ? AND is_deleted = 0"
                )
                row = self.db.fetch_one(conn, sql, (sha,))
            return CloudFile.from_db_row(row) if row else None

        return self.db.execute_read(op)

    def list_files(self, include_deleted: bool = False) -> List[CloudFile]:
        """列表视图：省去 bookmark BLOB 列，减少 UI 渲染时的内存压力。"""
        def op(conn):
            where = "" if include_deleted else "WHERE is_deleted = 0"
            sql = (
                f"SELECT {self._SELECT_FIELDS_NO_BOOKMARK} FROM cloud_files "
                f"{where} ORDER BY created_at DESC"
            )
            rows = self.db.fetch_all(conn, sql, ())
            return [CloudFile.from_db_row(r) for r in rows]

        return self.db.execute_read(op)

    def list_by_states(self, states: list) -> List[CloudFile]:
        """按 sync_state 过滤。用于启动时扫 pending/syncing。"""
        if not states:
            return []

        def op(conn):
            placeholders = ",".join("?" * len(states))
            sql = (
                f"SELECT {self._SELECT_FIELDS_NO_BOOKMARK} FROM cloud_files "
                f"WHERE sync_state IN ({placeholders}) ORDER BY created_at ASC"
            )
            rows = self.db.fetch_all(conn, sql, tuple(states))
            return [CloudFile.from_db_row(r) for r in rows]

        return self.db.execute_read(op)

    def total_used_bytes(self) -> int:
        """本地 cloud_files 未删除条目的字节总和（仅用于 UX 估算，云端配额以服务端为准）。"""
        def op(conn):
            return self.db.fetch_scalar(
                conn,
                "SELECT COALESCE(SUM(size_bytes), 0) FROM cloud_files WHERE is_deleted = 0",
                (), 0,
            )

        return int(self.db.execute_read(op) or 0)

    # ========== Upload parts（multipart 断点续传） ==========

    def record_part(self, file_id: int, part_number: int, etag: str) -> None:
        def op(conn):
            if self._is_mysql:
                sql = (
                    "INSERT INTO cloud_file_upload_parts (file_id, part_number, etag, uploaded_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON DUPLICATE KEY UPDATE etag = VALUES(etag), uploaded_at = VALUES(uploaded_at)"
                )
            else:
                sql = (
                    "INSERT OR REPLACE INTO cloud_file_upload_parts "
                    "(file_id, part_number, etag, uploaded_at) VALUES (?, ?, ?, ?)"
                )
            self.db.execute_write(
                conn, sql, (file_id, part_number, etag, int(time.time()))
            )

        self.db.execute_with_retry(op)

    def get_parts(self, file_id: int) -> dict:
        """返回 {part_number: etag} 字典。"""
        def op(conn):
            rows = self.db.fetch_all(
                conn,
                "SELECT part_number, etag FROM cloud_file_upload_parts WHERE file_id = ?",
                (file_id,),
            )
            result = {}
            for r in rows:
                pn = r["part_number"] if isinstance(r, dict) else r[0]
                tag = r["etag"] if isinstance(r, dict) else r[1]
                if tag:
                    result[int(pn)] = tag
            return result

        return self.db.execute_read(op)

    def clear_parts(self, file_id: int) -> None:
        def op(conn):
            self.db.execute_write(
                conn,
                "DELETE FROM cloud_file_upload_parts WHERE file_id = ?",
                (file_id,),
            )

        self.db.execute_with_retry(op)
