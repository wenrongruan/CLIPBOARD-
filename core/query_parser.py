"""结构化查询字符串解析器。

把用户输入的搜索字符串（支持 filter、正则、引号短语、否定）解析成
``QuerySpec`` dataclass，供 Repository 层拼 SQL 使用。

示例::

    parse('from:chrome tag:work after:2026-04-01 /hello.*world/ size:>1MB')

语法规则见 ``CLAUDE.md`` / 产品文档，本模块只负责解析，不生成 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Tuple


class QueryParseError(ValueError):
    """查询字符串不符合语法时抛出。"""


class Op(str, Enum):
    EQ = "="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="


@dataclass
class Filter:
    key: str
    op: Op
    value: Any
    negate: bool = False


@dataclass
class QuerySpec:
    keywords: List[str] = field(default_factory=list)
    exact_phrases: List[str] = field(default_factory=list)
    regex: List[str] = field(default_factory=list)
    filters: List[Filter] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.keywords or self.exact_phrases or self.regex or self.filters)

    def fts_match_expression(self) -> str:
        """把 keywords 和 exact_phrases 拼成 FTS5 MATCH 表达式。

        - exact_phrases 用双引号包裹（内部 ``"`` 转义为 ``""``）。
        - keywords 做 FTS5 特殊字符转义（``"`` → ``""``；保留 ``*`` 作为前缀通配符）。
        - 多段之间用空格连接（FTS5 默认 AND）。
        - 若都为空返回 ``""``。
        """
        parts: List[str] = []
        for phrase in self.exact_phrases:
            parts.append('"' + phrase.replace('"', '""') + '"')
        for kw in self.keywords:
            escaped = kw.replace('"', '""')
            # 若包含非字母数字字符（除 * 外），用引号包裹以避免 FTS5 语法错误。
            if _needs_quoting(kw):
                parts.append('"' + escaped + '"')
            else:
                parts.append(escaped)
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Tokenize
# ---------------------------------------------------------------------------


# filter 关键字集合；是 filter key 时以 ``key:`` 开头才按 filter 解析。
_FILTER_KEYS = {"from", "tag", "space", "size", "before", "after", "is"}

_IS_VALUES = {"starred", "text", "image"}

_SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 ** 2,
    "GB": 1024 ** 3,
}


def _needs_quoting(token: str) -> bool:
    """检查关键字是否含需要 FTS5 引号保护的特殊字符。"""
    # 字母、数字、下划线、以及作为前缀通配符的 * 放行。
    for ch in token:
        if ch.isalnum() or ch == "_" or ch == "*":
            continue
        # 中日韩文字直接交给 FTS5（通常 tokenizer 会处理）。
        if ord(ch) > 127:
            continue
        return True
    return False


def _tokenize(query: str) -> List[Tuple[str, Any]]:
    """把查询拆成 (kind, payload) 元组列表。

    kind 之一：
      - ``phrase``: 引号包裹的精确短语，payload 已脱引号并处理 ``\\"`` 转义
      - ``regex``: ``/.../`` 包裹的正则，payload 是中间的 pattern
      - ``filter``: payload 是 ``Filter`` 实例
      - ``word``: 普通单词
    """
    tokens: List[Tuple[str, Any]] = []
    i = 0
    n = len(query)

    while i < n:
        ch = query[i]
        if ch.isspace():
            i += 1
            continue

        # 引号短语。可能带前导 ``-``？规格说否定只作用于 filter，故引号短语前的 ``-``
        # 视为普通 word 的一部分（交由 word 分支处理），这里只处理直接起头的 ``"``。
        if ch == '"':
            end, phrase = _consume_quoted(query, i)
            tokens.append(("phrase", phrase))
            i = end
            continue

        # 正则 /pattern/：必须左侧是边界，右侧的 / 后是边界。
        if ch == "/":
            consumed = _try_consume_regex(query, i)
            if consumed is not None:
                end, pattern = consumed
                tokens.append(("regex", pattern))
                i = end
                continue
            # 否则按普通 word 解析（下面的分支）。

        # 普通 word / filter / 否定 filter。读到下一个空白为止，但遇到引号需要按整体吞掉。
        end, raw = _consume_word(query, i)
        i = end
        if not raw:
            continue

        # 判断是否为 filter。允许前导 ``-`` 表示否定。
        stripped = raw
        negate = False
        if stripped.startswith("-") and len(stripped) > 1:
            # ``-key:value`` 才算否定 filter；否则 ``-foo`` 当普通 word。
            rest = stripped[1:]
            if ":" in rest:
                key_part = rest.split(":", 1)[0]
                if key_part in _FILTER_KEYS:
                    negate = True
                    stripped = rest

        if ":" in stripped:
            key_part, value_part = stripped.split(":", 1)
            if key_part in _FILTER_KEYS:
                tokens.append(("filter", _encode_filter(key_part, value_part, negate)))
                continue

        # 都不是 → 普通关键词。若开头本来是 ``-``（非否定 filter），保留原样。
        tokens.append(("word", raw))

    return tokens


def _consume_quoted(query: str, start: int) -> Tuple[int, str]:
    """从 ``query[start] == '"'`` 开始读到下一个非转义 ``"``。"""
    assert query[start] == '"'
    i = start + 1
    buf: List[str] = []
    n = len(query)
    while i < n:
        ch = query[i]
        if ch == "\\" and i + 1 < n and query[i + 1] == '"':
            buf.append('"')
            i += 2
            continue
        if ch == '"':
            return i + 1, "".join(buf)
        buf.append(ch)
        i += 1
    raise QueryParseError("未闭合的引号短语（缺少结束 \"）")


def _try_consume_regex(query: str, start: int):
    """尝试把 ``/pattern/`` 作为 regex token 吞掉，边界严格。

    要求：
      - ``query[start] == '/'``
      - 其前一个字符是空白或在串首（调用者已确保起点边界）
      - 必须找到匹配的闭合 ``/``，其后一个字符是空白或串尾
      - pattern 内不能出现未转义的 ``/``
    """
    assert query[start] == "/"
    # 左边界：要求前一个字符是空白或 start=0。
    if start > 0 and not query[start - 1].isspace():
        return None

    i = start + 1
    n = len(query)
    buf: List[str] = []
    while i < n:
        ch = query[i]
        if ch == "\\" and i + 1 < n:
            # 转义符：原样保留以供下游 re 引擎处理。
            buf.append(ch)
            buf.append(query[i + 1])
            i += 2
            continue
        if ch == "/":
            # 右边界：后面必须是空白或串尾。
            if i + 1 == n or query[i + 1].isspace():
                if not buf:
                    return None  # 空 pattern 不接受，交给普通 word 处理
                return i + 1, "".join(buf)
            # 否则视为 regex 中间包含裸 / → 非法（我们不支持）
            return None
        buf.append(ch)
        i += 1
    return None  # 未闭合，不算 regex，交由 word 分支（它会遇到空白而断开）


def _consume_word(query: str, start: int) -> Tuple[int, str]:
    """读一个"普通"token：直到下一个空白；遇到引号要把引号内当成 token 一部分。

    例子::
        tag:"my val"  → 当前规格不支持，这里也会把整段读进来但后续解析会失败。
        -from:chrome  → 作为一个 word 读完。
    """
    i = start
    n = len(query)
    buf: List[str] = []
    while i < n:
        ch = query[i]
        if ch.isspace():
            break
        if ch == '"':
            # 把引号整体纳入当前 word，保留引号字符；例如 filter 值含引号会在稍后报错。
            end, inner = _consume_quoted(query, i)
            buf.append('"')
            buf.append(inner)
            buf.append('"')
            i = end
            continue
        buf.append(ch)
        i += 1
    return i, "".join(buf)


# ---------------------------------------------------------------------------
# Filter 解析
# ---------------------------------------------------------------------------


def _encode_filter(key: str, raw_value: str, negate: bool) -> Filter:
    if key in {"from", "tag", "space"}:
        if not raw_value:
            raise QueryParseError(f"{key}: 的值不能为空")
        if any(c.isspace() for c in raw_value):
            raise QueryParseError(f"{key}: 的值不支持空格：{raw_value!r}")
        return Filter(key=key, op=Op.EQ, value=raw_value, negate=negate)

    if key == "size":
        op, num_str = _split_comparison(raw_value)
        size_val = _parse_size(num_str)
        return Filter(key="size", op=op, value=size_val, negate=negate)

    if key in {"before", "after"}:
        if not raw_value:
            raise QueryParseError(f"{key}: 的值不能为空")
        ts = _parse_date(raw_value, end_of_day=(key == "before"))
        op = Op.LE if key == "before" else Op.GE
        return Filter(key=key, op=op, value=ts, negate=negate)

    if key == "is":
        if raw_value not in _IS_VALUES:
            raise QueryParseError(
                f"is: 不支持的值 {raw_value!r}，可选：{sorted(_IS_VALUES)}"
            )
        return Filter(key="is", op=Op.EQ, value=raw_value, negate=negate)

    # 走不到这里（tokenizer 已过滤）。
    raise QueryParseError(f"未知 filter：{key}")


def _split_comparison(raw: str) -> Tuple[Op, str]:
    """从 ``>=1MB`` / ``<500`` / ``=100`` / ``1MB`` 中切出运算符和值。"""
    if not raw:
        raise QueryParseError("size: 的值不能为空")
    if raw.startswith(">="):
        return Op.GE, raw[2:]
    if raw.startswith("<="):
        return Op.LE, raw[2:]
    if raw.startswith(">"):
        return Op.GT, raw[1:]
    if raw.startswith("<"):
        return Op.LT, raw[1:]
    if raw.startswith("="):
        return Op.EQ, raw[1:]
    return Op.EQ, raw


def _parse_size(raw: str) -> int:
    if not raw:
        raise QueryParseError("size: 的数值缺失")
    # 切分数值和单位。单位可能是 B / KB / MB / GB（大小写不敏感），也可能缺省（当 B）。
    up = raw.upper()
    unit = None
    for candidate in ("GB", "MB", "KB", "B"):
        if up.endswith(candidate):
            num_str = raw[: len(raw) - len(candidate)]
            unit = candidate
            break
    if unit is None:
        # 没带单位：必须是纯数字，按字节处理。
        num_str = raw
        unit = "B"

    num_str = num_str.strip()
    if not num_str:
        raise QueryParseError(f"size: 的数值缺失：{raw!r}")
    try:
        number = float(num_str)
    except ValueError as exc:
        raise QueryParseError(f"size: 数值非法：{raw!r}") from exc
    if number < 0:
        raise QueryParseError(f"size: 数值不能为负：{raw!r}")
    multiplier = _SIZE_UNITS[unit]
    return int(number * multiplier)


def _parse_date(raw: str, *, end_of_day: bool) -> int:
    """把 ``YYYY-MM-DD`` 或 ``YYYY-MM-DDTHH:MM`` 转为毫秒时间戳。

    - ``before:`` → 当天 23:59:59.999（若未显式给时间）
    - ``after:``  → 当天 00:00:00.000（若未显式给时间）
    - 若给了时间（含 ``T``），不再调整，按给定时间。
    - 统一按 UTC 解析（下游 Repository 可自行决定语义；先保证可测试一致性）。
    """
    has_time = "T" in raw
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise QueryParseError(f"日期格式非法：{raw!r}，应为 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM") from exc

    if not has_time:
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999_000)
        else:
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def parse(query: str) -> QuerySpec:
    """主入口：解析查询字符串。"""
    if query is None:
        return QuerySpec()
    query = query.strip()
    if not query:
        return QuerySpec()

    spec = QuerySpec()
    for kind, payload in _tokenize(query):
        if kind == "phrase":
            spec.exact_phrases.append(payload)
        elif kind == "regex":
            spec.regex.append(payload)
        elif kind == "filter":
            spec.filters.append(payload)
        elif kind == "word":
            spec.keywords.append(payload)
        else:  # pragma: no cover
            raise QueryParseError(f"未知 token 类型：{kind}")
    return spec


__all__ = [
    "Op",
    "Filter",
    "QuerySpec",
    "QueryParseError",
    "parse",
]
