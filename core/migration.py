import logging
from typing import Callable, Optional

from .repository import ClipboardRepository

logger = logging.getLogger(__name__)

# INSERT OR IGNORE 让 content_hash UNIQUE 冲突静默跳过，避免迁移中 IntegrityError 往上抛
_INSERT_SQL = """
    INSERT OR IGNORE INTO clipboard_items (
        content_type, text_content, image_data, image_thumbnail,
        content_hash, preview, device_id, device_name,
        created_at, is_starred
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class DatabaseMigrator:
    """数据库迁移工具：从源库分页读取全量数据，按 content_hash 去重写入目标库"""

    def __init__(
        self,
        source: ClipboardRepository,
        target: ClipboardRepository,
        page_size: int = 100,
    ):
        self.source = source
        self.target = target
        self.page_size = page_size

    def migrate(
        self, progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> int:
        """
        执行迁移，返回实际写入的条数。

        Args:
            progress_callback: 可选回调 (migrated_so_far, total)
        """
        page = 0
        migrated = 0
        _, total = self.source.get_items_full(0, 1)

        while True:
            items, _ = self.source.get_items_full(page, self.page_size)
            if not items:
                break

            hashes = [it.content_hash for it in items]
            existing = self._existing_hashes(hashes)
            pending = [it.to_db_tuple() for it in items if it.content_hash not in existing]

            if pending:
                try:
                    def _insert_batch(conn, rows=pending):
                        self.target.db.execute_many(conn, _INSERT_SQL, rows)
                        return len(rows)
                    migrated += self.target.db.execute_with_retry(_insert_batch)
                except Exception as e:
                    logger.warning(f"批量迁移失败: {e}")

            if progress_callback:
                progress_callback(min((page + 1) * self.page_size, total), total)

            page += 1

        return migrated

    def _existing_hashes(self, hashes: list) -> set:
        if not hashes:
            return set()
        placeholders = ",".join("?" * len(hashes))
        sql = f"SELECT content_hash FROM clipboard_items WHERE content_hash IN ({placeholders})"

        def operation(conn):
            return {row["content_hash"] for row in self.target.db.fetch_all(conn, sql, tuple(hashes))}

        try:
            return self.target.db.execute_read(operation)
        except Exception as e:
            logger.debug(f"批量查重失败，回退逐条: {e}")
            return {h for h in hashes if self.target.get_by_hash(h) is not None}
