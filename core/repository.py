import logging
import re
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from .base_database import AbstractDatabaseManager
from .models import ClipboardItem
from .query_parser import Filter, Op, QuerySpec, parse as parse_query

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


def _negate_op(op: str) -> str:
    """把比较运算符翻转 (用于 size:!x 这种 negate filter)。"""
    mapping = {
        "=": "!=",
        "!=": "=",
        ">": "<=",
        ">=": "<",
        "<": ">=",
        "<=": ">",
    }
    return mapping.get(op, op)


class ClipboardRepository:
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

        item = self.db.execute_read(operation)
        if item is not None:
            self._fill_tag_ids([item])
        return item

    def search_by_keyword(
        self,
        keyword: str,
        page: int = 0,
        page_size: int = 10,
        starred_only: bool = False,
        space_id: Optional[str] = None,
    ) -> Tuple[List[ClipboardItem], int]:
        """旧关键词搜索契约：解析 keyword -> QuerySpec 后委托给 search()。

        保留原先的 ``(items, total)`` 返回形状，方便 v3.4 之前的 UI 分页继续工作。
        Wave 3 迁移完毕后可下线。
        """
        spec = parse_query(keyword or "")
        if starred_only:
            spec.filters.append(Filter(key="is", op=Op.EQ, value="starred"))
        # 旧契约里 page 是 0-based；search() 内部兼容 0/1-based
        items = self.search(
            spec, page=page if page else 1, page_size=page_size, space_id=space_id
        )
        total = self._count_spec(spec, space_id=space_id)
        return items, total

    def search(
        self,
        query_spec: Optional[QuerySpec] = None,
        page: int = 1,
        page_size: int = 50,
        *,
        space_id: Optional[str] = None,
    ) -> List[ClipboardItem]:
        """v3.4 新结构化查询入口。

        参数：
          - query_spec: QuerySpec；None/空 spec 且无 space_id → 按 created_at DESC 分页
          - page/page_size: 1-based 分页
          - space_id: 显式 space 过滤；优先级高于 query_spec.filters 中的 space:
                     None 表示个人空间（WHERE space_id IS NULL）；传 "" 表示不过滤
        """
        if query_spec is None:
            query_spec = QuerySpec()

        # page 在新 API 中 1-based，兼容老调用可能传 0
        eff_page = max(page, 1)
        offset = (eff_page - 1) * page_size

        # 正则过滤需要在 Python 层后置，为了让 LIMIT 仍能取到足够结果，先多取一些。
        has_regex = bool(query_spec.regex)
        fetch_limit = page_size * 3 if has_regex else page_size

        rows = self._run_query(
            query_spec, fetch_limit, offset, space_id=space_id, for_count=False
        )
        items: List[ClipboardItem] = [ClipboardItem.from_db_row(row) for row in rows]

        if has_regex:
            items = self._apply_regex_filter(items, query_spec.regex)
            items = items[:page_size]

        self._fill_tag_ids(items)
        return items

    def _count_spec(
        self,
        query_spec: QuerySpec,
        space_id: Optional[str] = None,
    ) -> int:
        """配合旧 search 返回 total。正则后置过滤会让 total 不精确；
        这里给近似值（SQL 层过滤后的行数），足以驱动旧分页 UI。"""
        return self._run_query(
            query_spec, limit=None, offset=0, space_id=space_id, for_count=True
        )

    # ------------------------------------------------------------------
    # 查询构造
    # ------------------------------------------------------------------

    # filter key -> 解析函数，构建 (where_sql_fragment, params_list)
    def _build_filter_clauses(
        self,
        query_spec: QuerySpec,
        space_id: Optional[str],
    ) -> Tuple[List[str], List]:
        clauses: List[str] = []
        params: List = []

        # 显式 space_id 优先；若显式传入非空串，忽略 query_spec 里的 space: filter
        explicit_space = space_id is not None and space_id != ""
        explicit_space_is_null = space_id is None  # None = 个人空间

        # 处理 query_spec.filters
        content_type_pinned = False
        for f in query_spec.filters:
            key = f.key
            if key == "from":
                op = "=" if not f.negate else "!="
                clauses.append(f"source_app {op} ?")
                params.append(f.value)
            elif key == "tag":
                # tag 名关联 tag_definitions -> clipboard_tags
                sub_body = (
                    "SELECT ct.item_id FROM clipboard_tags ct "
                    "JOIN tag_definitions td ON ct.tag_id = td.id "
                    "WHERE td.name = ?"
                )
                in_op = "NOT IN" if f.negate else "IN"
                clauses.append(f"id {in_op} ({sub_body})")
                params.append(f.value)
            elif key == "space":
                if explicit_space or explicit_space_is_null:
                    continue  # 显式 space_id 接管
                op = "=" if not f.negate else "!="
                clauses.append(f"space_id {op} ?")
                params.append(f.value)
            elif key == "size":
                op_sql = f.op.value
                if f.negate:
                    op_sql = _negate_op(op_sql)
                if content_type_pinned:
                    # 前面已固定 content_type，只查对应载荷列
                    clauses.append(
                        f"((content_type = 'text' AND LENGTH(text_content) {op_sql} ?)"
                        f" OR (content_type = 'image' AND LENGTH(image_data) {op_sql} ?))"
                    )
                    params.extend([f.value, f.value])
                else:
                    clauses.append(
                        f"(LENGTH(text_content) {op_sql} ? OR LENGTH(image_data) {op_sql} ?)"
                    )
                    params.extend([f.value, f.value])
            elif key == "before":
                op_sql = "<=" if not f.negate else ">"
                clauses.append(f"created_at {op_sql} ?")
                params.append(f.value)
            elif key == "after":
                op_sql = ">=" if not f.negate else "<"
                clauses.append(f"created_at {op_sql} ?")
                params.append(f.value)
            elif key == "is":
                v = f.value
                if v == "starred":
                    clauses.append("is_starred != 1" if f.negate else "is_starred = 1")
                elif v == "text":
                    clauses.append(
                        "content_type != 'text'" if f.negate else "content_type = 'text'"
                    )
                    content_type_pinned = True
                elif v == "image":
                    clauses.append(
                        "content_type != 'image'" if f.negate else "content_type = 'image'"
                    )
                    content_type_pinned = True

        # 显式 space_id
        if explicit_space:
            clauses.append("space_id = ?")
            params.append(space_id)
        elif explicit_space_is_null:
            clauses.append("space_id IS NULL")

        return clauses, params

    def _run_query(
        self,
        query_spec: QuerySpec,
        limit: Optional[int],
        offset: int,
        space_id: Optional[str],
        for_count: bool,
    ):
        """根据 has_fts + is_mysql 生成对应 SQL，返回 rows（或 for_count=True 时返回 int）。"""
        filter_clauses, filter_params = self._build_filter_clauses(query_spec, space_id)

        has_text = bool(query_spec.keywords or query_spec.exact_phrases)

        def op(conn):
            # SQLite + FTS5 可用：关键词走 FTS5 子查询
            if has_text and self._has_fts and not self._is_mysql:
                fts_expr = query_spec.fts_match_expression()
                where_sql = "id IN (SELECT rowid FROM clipboard_fts WHERE clipboard_fts MATCH ?)"
                params: List = [fts_expr]
                if filter_clauses:
                    where_sql += " AND " + " AND ".join(filter_clauses)
                    params.extend(filter_params)
                return self._do_select(
                    conn, where_sql, params, limit, offset, for_count
                )

            # FTS 不可用或无关键词：LIKE 回退 + filter
            like_clauses: List[str] = []
            like_params: List = []
            if has_text:
                for kw in query_spec.keywords:
                    like_clauses.append(
                        "(text_content LIKE ? OR preview LIKE ?)"
                    )
                    like_params.extend([f"%{kw}%", f"%{kw}%"])
                for phrase in query_spec.exact_phrases:
                    like_clauses.append(
                        "(text_content LIKE ? OR preview LIKE ?)"
                    )
                    like_params.extend([f"%{phrase}%", f"%{phrase}%"])

            all_clauses = like_clauses + filter_clauses
            where_sql = " AND ".join(all_clauses) if all_clauses else ""
            params = like_params + filter_params
            return self._do_select(conn, where_sql, params, limit, offset, for_count)

        return self.db.execute_read(op)

    def _do_select(
        self,
        conn,
        where_sql: str,
        params: List,
        limit: Optional[int],
        offset: int,
        for_count: bool,
    ):
        if for_count:
            count_sql = "SELECT COUNT(*) FROM clipboard_items"
            if where_sql:
                count_sql += f" WHERE {where_sql}"
            return self._scalar(conn, count_sql, tuple(params))

        sql = f"SELECT {self._SELECT_FIELDS_NO_IMAGE} FROM clipboard_items"
        if where_sql:
            sql += f" WHERE {where_sql}"
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = params + [limit, offset]
        return self._fetchall(conn, sql, tuple(params))

    @staticmethod
    def _apply_regex_filter(
        items: List[ClipboardItem], patterns: List[str]
    ) -> List[ClipboardItem]:
        """Python 层后置正则过滤。模式任一匹配即保留（AND 语义：每个模式都需命中）。"""
        if not patterns:
            return items
        try:
            compiled = [re.compile(p) for p in patterns]
        except re.error as exc:
            logger.warning("正则编译失败，跳过正则过滤: %s", exc)
            return items

        out: List[ClipboardItem] = []
        for it in items:
            # 只对文本条目做正则匹配；图片没有可搜的文本载荷
            text = getattr(it, "text_content", None) or it.preview or ""
            if all(r.search(text) for r in compiled):
                out.append(it)
        return out

    # ------------------------------------------------------------------
    # v3.4: tag 填充 & 时间轴 & tag CRUD
    # ------------------------------------------------------------------

    def _fill_tag_ids(self, items: List[ClipboardItem]) -> None:
        """给一批 item 回填 tag_ids 字段（批量查询 clipboard_tags）。

        clipboard_tags 表在 v3.4 之前不存在，迁移未执行时要静默跳过，避免
        在旧库上使 search 直接崩溃。
        """
        if not items:
            return
        ids = [it.id for it in items if it.id is not None]
        if not ids:
            return

        mapping: Dict[int, List[str]] = {}
        placeholders = ",".join("?" * len(ids))
        sql = (
            f"SELECT item_id, tag_id FROM clipboard_tags WHERE item_id IN ({placeholders})"
        )

        def op(conn):
            try:
                return self._fetchall(conn, sql, tuple(ids))
            except Exception as exc:
                # 迁移未跑或表不存在：记 debug 后返回空
                logger.debug("读 clipboard_tags 失败（可能未迁移）: %s", exc)
                return []

        try:
            rows = self.db.execute_read(op)
        except Exception:
            return

        for row in rows:
            # 兼容 sqlite3.Row / dict
            try:
                item_id = row["item_id"]
                tag_id = row["tag_id"]
            except (KeyError, IndexError, TypeError):
                item_id = row[0]
                tag_id = row[1]
            mapping.setdefault(item_id, []).append(tag_id)

        for it in items:
            if it.id in mapping:
                it.tag_ids = mapping[it.id]

    def get_timeline(
        self,
        start_ts: int,
        end_ts: int,
        granularity: str = "day",
        space_id: Optional[str] = None,
    ) -> List[dict]:
        """按时间桶聚合统计。

        参数：
          - start_ts / end_ts: 毫秒时间戳，闭区间 [start_ts, end_ts]
          - granularity: "hour" 或 "day"
          - space_id: None = 个人空间；空串 = 所有空间；其他值 = 特定空间

        返回 [{bucket_start_ts, count, first_item_id, last_item_id}, ...]，
        按 bucket_start_ts ASC 排序。
        """
        if granularity not in ("hour", "day"):
            raise ValueError(f"granularity 必须是 hour|day，收到 {granularity!r}")

        # 各方言计算 bucket_start_ts（单位：毫秒）。均向下取整到桶边界。
        if self._is_mysql:
            fmt = "%Y-%m-%d %H:00:00" if granularity == "hour" else "%Y-%m-%d 00:00:00"
            bucket_expr = (
                f"UNIX_TIMESTAMP(DATE_FORMAT(FROM_UNIXTIME(created_at/1000), '{fmt}')) * 1000"
            )
        else:
            fmt = "%Y-%m-%d %H:00:00" if granularity == "hour" else "%Y-%m-%d 00:00:00"
            bucket_expr = (
                f"CAST(strftime('%s', strftime('{fmt}', created_at/1000, 'unixepoch')) AS INTEGER) * 1000"
            )

        where = ["created_at >= ?", "created_at <= ?"]
        params: List = [start_ts, end_ts]
        if space_id is None:
            where.append("space_id IS NULL")
        elif space_id != "":
            where.append("space_id = ?")
            params.append(space_id)

        sql = (
            f"SELECT {bucket_expr} AS bucket, COUNT(*) AS cnt, "
            f"MIN(id) AS first_id, MAX(id) AS last_id "
            f"FROM clipboard_items "
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY bucket ORDER BY bucket ASC"
        )

        def op(conn):
            return self._fetchall(conn, sql, tuple(params))

        rows = self.db.execute_read(op)
        out: List[dict] = []
        for row in rows:
            try:
                bucket = row["bucket"]
                cnt = row["cnt"]
                first_id = row["first_id"]
                last_id = row["last_id"]
            except (KeyError, IndexError, TypeError):
                bucket, cnt, first_id, last_id = row[0], row[1], row[2], row[3]
            out.append(
                {
                    "bucket_start_ts": int(bucket) if bucket is not None else 0,
                    "count": int(cnt),
                    "first_item_id": first_id,
                    "last_item_id": last_id,
                }
            )
        return out

    def get_items_by_tag(
        self, tag_id: str, page: int = 1, page_size: int = 50
    ) -> List[ClipboardItem]:
        """按 tag_id 查询条目。"""
        eff_page = max(page, 1)
        offset = (eff_page - 1) * page_size
        sql = (
            f"SELECT {self._SELECT_FIELDS_NO_IMAGE} FROM clipboard_items "
            f"WHERE id IN (SELECT item_id FROM clipboard_tags WHERE tag_id = ?) "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )

        def op(conn):
            return self._fetchall(conn, sql, (tag_id, page_size, offset))

        rows = self.db.execute_read(op)
        items = [ClipboardItem.from_db_row(row) for row in rows]
        self._fill_tag_ids(items)
        return items

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

    def get_starred_unsynced(self, limit: int = 100) -> List[ClipboardItem]:
        """获取已收藏但未同步到云端的条目（含完整图片数据，用于推送）"""
        def operation(conn) -> List[ClipboardItem]:
            sql = f"""
                SELECT {self._SELECT_FIELDS}
                FROM clipboard_items
                WHERE is_starred = 1 AND cloud_id IS NULL
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = self._fetchall(conn, sql, (limit,))
            return [ClipboardItem.from_db_row(row) for row in rows]

        return self.db.execute_read(operation)

    def get_unsynced_items(self, limit: int = 20) -> List[ClipboardItem]:
        """获取未同步到云端的条目（含完整图片数据），按最新排序，用于批量推送"""
        def operation(conn) -> List[ClipboardItem]:
            sql = f"""
                SELECT {self._SELECT_FIELDS}
                FROM clipboard_items
                WHERE cloud_id IS NULL
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = self._fetchall(conn, sql, (limit,))
            return [ClipboardItem.from_db_row(row) for row in rows]
        return self.db.execute_read(operation)

    def get_unstarred_with_cloud_id(self, limit: int = 200) -> List[ClipboardItem]:
        """获取未收藏但有云端副本的条目，按最旧排序（用于配额清理时优先删最旧）"""
        def operation(conn) -> List[ClipboardItem]:
            sql = f"""
                SELECT {self._SELECT_FIELDS_NO_IMAGE}
                FROM clipboard_items
                WHERE is_starred = 0 AND cloud_id IS NOT NULL
                ORDER BY created_at ASC
                LIMIT ?
            """
            rows = self._fetchall(conn, sql, (limit,))
            return [ClipboardItem.from_db_row(row) for row in rows]

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
