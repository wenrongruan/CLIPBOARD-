"""ClipboardQuery: 列表 / 搜索 / 时间轴 / 标签过滤等只读查询。

持有 ClipboardDAO 引用以复用 _SELECT_FIELDS / _fetchone / _fetchall / _scalar
以及 _has_fts / _is_mysql 等状态，避免重复实现。
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from ..base_database import AbstractDatabaseManager
from ..models import ClipboardItem
from ..query_parser import Filter, Op, QuerySpec, parse as parse_query
from .clipboard_dao import ClipboardDAO

logger = logging.getLogger(__name__)


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


class ClipboardQuery:
    """clipboard_items 上的只读查询/搜索/聚合。"""

    def __init__(self, db_manager: AbstractDatabaseManager, dao: ClipboardDAO):
        self.db = db_manager
        self._dao = dao
        self._is_mysql = dao._is_mysql
        self._has_fts = dao._has_fts

    # ------------------------------------------------------------------
    # 分页列表
    # ------------------------------------------------------------------

    def get_items(
        self,
        page: int = 0,
        page_size: int = 10,
        starred_only: bool = False,
        space_id: Optional[str] = None,
    ) -> Tuple[List[ClipboardItem], int]:
        """分页查询列表。

        space_id 语义（与 search/get_timeline 保持一致）：
          - None  → 个人空间：WHERE space_id IS NULL
          - ""    → 不过滤，返回全部空间的条目
          - 其他  → 按具体 space_id 过滤
        """
        def operation(conn) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size

            # 构造 WHERE 条件
            clauses: List[str] = []
            params_where: List = []
            if starred_only:
                clauses.append("is_starred = 1")
            if space_id is None:
                clauses.append("space_id IS NULL")
            elif space_id != "":
                clauses.append("space_id = ?")
                params_where.append(space_id)
            # space_id == "" → 不追加任何 space 过滤，返回全部空间

            where_clause = ("WHERE " + " AND ".join(clauses)) if clauses else ""

            # 获取总数（条件与分页查询完全一致）
            count_sql = f"SELECT COUNT(*) FROM clipboard_items {where_clause}"
            total = self._dao._scalar(conn, count_sql, tuple(params_where))

            # 获取分页数据（不加载完整图片数据以提高性能）
            sql = f"""
                SELECT {ClipboardDAO._SELECT_FIELDS_NO_IMAGE}
                FROM clipboard_items
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            rows = self._dao._fetchall(conn, sql, tuple(params_where) + (page_size, offset))
            items = [ClipboardItem.from_db_row(row) for row in rows]
            return items, total

        return self.db.execute_read(operation)

    def get_items_full(
        self, page: int = 0, page_size: int = 100
    ) -> Tuple[List[ClipboardItem], int]:
        """获取分页数据（包含完整图片数据，用于数据迁移）"""
        def operation(conn) -> Tuple[List[ClipboardItem], int]:
            offset = page * page_size

            total = self._dao._scalar(conn, "SELECT COUNT(*) FROM clipboard_items")

            sql = f"""
                SELECT {ClipboardDAO._SELECT_FIELDS}
                FROM clipboard_items
                ORDER BY created_at ASC
                LIMIT ? OFFSET ?
            """
            rows = self._dao._fetchall(conn, sql, (page_size, offset))
            items = [ClipboardItem.from_db_row(row) for row in rows]
            return items, total

        return self.db.execute_read(operation)

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

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
            return self._dao._scalar(conn, count_sql, tuple(params))

        sql = f"SELECT {ClipboardDAO._SELECT_FIELDS_NO_IMAGE} FROM clipboard_items"
        if where_sql:
            sql += f" WHERE {where_sql}"
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = params + [limit, offset]
        return self._dao._fetchall(conn, sql, tuple(params))

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
    # v3.4: tag 填充 & 时间轴 & 按 tag 列表
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
                return self._dao._fetchall(conn, sql, tuple(ids))
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
            return self._dao._fetchall(conn, sql, tuple(params))

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
            f"SELECT {ClipboardDAO._SELECT_FIELDS_NO_IMAGE} FROM clipboard_items "
            f"WHERE id IN (SELECT item_id FROM clipboard_tags WHERE tag_id = ?) "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )

        def op(conn):
            return self._dao._fetchall(conn, sql, (tag_id, page_size, offset))

        rows = self.db.execute_read(op)
        items = [ClipboardItem.from_db_row(row) for row in rows]
        self._fill_tag_ids(items)
        return items
