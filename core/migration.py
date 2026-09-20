import logging
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .repository import ClipboardRepository

logger = logging.getLogger(__name__)

# 与 ClipboardItem.to_db_tuple() 的字段顺序严格一致（v3.4 起为 13 个值）。
# 早期版本这里只写了 10 列，导致 execute_many 恒定抛错、被 except 吞掉后
# 迁移实际写入 0 条却向用户报告"迁移完成"。现在列清单与方言冲突策略都在
# 运行时按目标库真实 schema 生成，并让失败向上抛。
_INSERT_COLUMNS: Tuple[str, ...] = (
    "content_type",
    "text_content",
    "image_data",
    "image_thumbnail",
    "content_hash",
    "preview",
    "device_id",
    "device_name",
    "created_at",
    "is_starred",
    "space_id",
    "source_app",
    "source_title",
)


def _row_dict(item) -> Dict[str, object]:
    """把条目摊平成 {列名: 值}，便于按目标库实际列裁剪。

    不能用 item.to_db_tuple()：它返回的是固定顺序元组，一旦目标库缺列
    （旧 schema 没有 space_id/source_app/source_title）就无法安全裁剪。
    """
    text_content, image_data, image_thumbnail = item._payload_db_fields()
    return {
        "content_type": item.content_type.value,
        "text_content": text_content,
        "image_data": image_data,
        "image_thumbnail": image_thumbnail,
        "content_hash": item.content_hash,
        "preview": item.preview,
        "device_id": item.device_id,
        "device_name": item.device_name,
        "created_at": item.created_at,
        "is_starred": int(item.is_starred),
        "space_id": item.space_id,
        "source_app": item.source_app,
        "source_title": item.source_title,
    }


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
        self._columns: Optional[Tuple[str, ...]] = None

    # ========== 目标库 schema 探测 ==========

    def _target_columns(self) -> Tuple[str, ...]:
        """返回目标表真实存在的、且我们认识的列（按 _INSERT_COLUMNS 顺序）。

        探测失败时回退到全部 13 列并让 INSERT 报错上抛——宁可响亮失败，
        也不要像旧实现那样静默写入 0 条。
        """
        if self._columns is not None:
            return self._columns

        db = self.target.db
        is_mysql = getattr(db, "is_mysql", False)
        if is_mysql:
            sql = (
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'clipboard_items'"
            )
        else:
            sql = "PRAGMA table_info(clipboard_items)"

        try:
            def operation(conn):
                return db.fetch_all(conn, sql)

            rows = db.execute_read(operation) or []
            found = set()
            for row in rows:
                # sqlite 用 name，MySQL 用 column_name（上面已 AS name）
                name = row["name"] if "name" in row.keys() else None
                if name:
                    found.add(str(name))
        except Exception as e:
            logger.warning(f"探测目标库列失败，按完整 13 列写入: {e}")
            self._columns = _INSERT_COLUMNS
            return self._columns

        cols = tuple(c for c in _INSERT_COLUMNS if c in found)
        if not cols:
            logger.warning("目标库列探测结果为空，按完整 13 列写入")
            cols = _INSERT_COLUMNS
        self._columns = cols
        return self._columns

    def _build_insert_sql(self, columns: Sequence[str]) -> str:
        is_mysql = getattr(self.target.db, "is_mysql", False)
        # SQLite: INSERT OR IGNORE；MySQL: INSERT IGNORE（OR 语法在 MySQL 里是语法错误）
        verb = "INSERT IGNORE" if is_mysql else "INSERT OR IGNORE"
        col_list = ", ".join(columns)
        placeholders = ", ".join("?" * len(columns))
        return f"{verb} INTO clipboard_items ({col_list}) VALUES ({placeholders})"

    # ========== 迁移主体 ==========

    def migrate(
        self, progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> int:
        """
        执行迁移，返回实际写入的条数。

        任何一批写入失败都会抛出（由调用方通过 finished_err 告知用户），
        绝不在内部吞掉后继续返回"看起来成功"的计数。

        Args:
            progress_callback: 可选回调 (migrated_so_far, total)
        """
        page = 0
        migrated = 0
        _, total = self.source.get_items_full(0, 1)
        columns = self._target_columns()
        insert_sql = self._build_insert_sql(columns)

        while True:
            items, _ = self.source.get_items_full(page, self.page_size)
            if not items:
                break

            hashes = [it.content_hash for it in items]
            space_scoped = "space_id" in columns
            existing = self._existing_hashes(hashes, space_scoped=space_scoped)
            pending = [
                tuple(_row_dict(it)[c] for c in columns)
                for it in items
                if ((it.space_id or "") if space_scoped else "", it.content_hash)
                not in existing
            ]

            if pending:
                def _insert_batch(conn, rows=pending, sql=insert_sql):
                    self.target.db.execute_many(conn, sql, rows)
                    return len(rows)

                try:
                    migrated += self.target.db.execute_with_retry(_insert_batch)
                except Exception as e:
                    # 关键：失败必须上抛。旧实现在这里只打一条 warning，
                    # 导致迁移写入 0 条却弹"迁移完成"，用户据此删库即全量丢失。
                    logger.error(f"批量迁移失败（第 {page + 1} 页，{len(pending)} 条）: {e}")
                    raise RuntimeError(
                        f"迁移第 {page + 1} 页失败，已成功写入 {migrated} 条：{e}"
                    ) from e

            if progress_callback:
                progress_callback(min((page + 1) * self.page_size, total), total)

            page += 1

        return migrated

    def _existing_hashes(self, hashes: list, space_scoped: bool = True) -> set:
        if not hashes:
            return set()
        placeholders = ",".join("?" * len(hashes))
        columns = "content_hash, space_id" if space_scoped else "content_hash"
        sql = f"SELECT {columns} FROM clipboard_items WHERE content_hash IN ({placeholders})"

        def operation(conn):
            return {
                ((row["space_id"] or "") if space_scoped else "", row["content_hash"])
                for row in self.target.db.fetch_all(conn, sql, tuple(hashes))
            }

        try:
            return self.target.db.execute_read(operation)
        except Exception as e:
            logger.debug(f"批量查重失败，回退逐条: {e}")
            # 查询异常由写入阶段的冲突策略兜底；不能把别的空间条目
            # 错认成已迁移。
            return set()
