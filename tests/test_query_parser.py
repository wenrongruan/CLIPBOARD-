"""``core.query_parser`` 的单元测试。

覆盖 tokenize、每种 filter、否定、错误分支以及 ``fts_match_expression`` 的拼装规则。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.query_parser import (  # noqa: E402
    Filter,
    Op,
    QueryParseError,
    QuerySpec,
    parse,
)


def _ts(date_str: str, *, end_of_day: bool = False) -> int:
    """测试辅助：把日期转成毫秒时间戳（UTC），和解析器保持一致。"""
    has_time = "T" in date_str
    dt = datetime.fromisoformat(date_str)
    if not has_time:
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999_000)
        else:
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# 基础：空串 / 关键字
# ---------------------------------------------------------------------------


def test_empty_string_returns_empty_spec():
    spec = parse("")
    assert spec == QuerySpec()
    assert spec.is_empty()


def test_whitespace_only_is_empty():
    spec = parse("   \t  ")
    assert spec.is_empty()


def test_none_returns_empty_spec():
    spec = parse(None)  # type: ignore[arg-type]
    assert spec.is_empty()


def test_single_keyword():
    spec = parse("python")
    assert spec.keywords == ["python"]
    assert spec.exact_phrases == []
    assert spec.regex == []
    assert spec.filters == []


def test_multiple_keywords():
    spec = parse("python code review")
    assert spec.keywords == ["python", "code", "review"]


def test_extra_whitespace_collapsed():
    spec = parse("  python    code  ")
    assert spec.keywords == ["python", "code"]


# ---------------------------------------------------------------------------
# 引号短语
# ---------------------------------------------------------------------------


def test_quoted_phrase_basic():
    spec = parse('"hello world"')
    assert spec.exact_phrases == ["hello world"]
    assert spec.keywords == []


def test_quoted_phrase_with_word():
    spec = parse('"hello world" python')
    assert spec.exact_phrases == ["hello world"]
    assert spec.keywords == ["python"]


def test_quoted_phrase_escaped_quote():
    spec = parse(r'"say \"hi\""')
    assert spec.exact_phrases == ['say "hi"']


def test_unclosed_quote_raises():
    with pytest.raises(QueryParseError):
        parse('"unterminated')


# ---------------------------------------------------------------------------
# 正则
# ---------------------------------------------------------------------------


def test_regex_basic():
    spec = parse("/hello.*world/")
    assert spec.regex == ["hello.*world"]
    assert spec.keywords == []


def test_regex_with_other_tokens():
    spec = parse("foo /a.b/ bar")
    assert spec.regex == ["a.b"]
    assert spec.keywords == ["foo", "bar"]


def test_slash_not_regex_when_in_path_like_token():
    """``/path/to/file`` 这种 token 不应被识别为 regex（内部有裸 /）。"""
    spec = parse("/path/to/file")
    # 整段回退为一个普通 word
    assert spec.regex == []
    assert spec.keywords == ["/path/to/file"]


def test_lone_slash_pair_empty_pattern_not_regex():
    spec = parse("//")
    # 空 pattern 不接受，回退为 word
    assert spec.regex == []
    assert spec.keywords == ["//"]


def test_regex_with_escaped_slash():
    spec = parse(r"/a\/b/")
    assert spec.regex == [r"a\/b"]


# ---------------------------------------------------------------------------
# filter: from / tag / space
# ---------------------------------------------------------------------------


def test_filter_from():
    spec = parse("from:chrome")
    assert spec.filters == [Filter("from", Op.EQ, "chrome")]


def test_filter_tag():
    spec = parse("tag:work")
    assert spec.filters == [Filter("tag", Op.EQ, "work")]


def test_filter_space_keeps_string_value():
    spec = parse("space:42")
    assert spec.filters == [Filter("space", Op.EQ, "42")]


# ---------------------------------------------------------------------------
# filter: size 四种比较符
# ---------------------------------------------------------------------------


def test_filter_size_gt_mb():
    spec = parse("size:>1MB")
    assert spec.filters == [Filter("size", Op.GT, 1024 * 1024)]


def test_filter_size_lt_kb():
    spec = parse("size:<500KB")
    assert spec.filters == [Filter("size", Op.LT, 500 * 1024)]


def test_filter_size_ge_gb_float():
    spec = parse("size:>=1.5GB")
    assert spec.filters == [Filter("size", Op.GE, int(1.5 * 1024 ** 3))]


def test_filter_size_eq_bytes_implicit():
    spec = parse("size:100")
    assert spec.filters == [Filter("size", Op.EQ, 100)]


def test_filter_size_le_with_unit():
    spec = parse("size:<=2MB")
    assert spec.filters == [Filter("size", Op.LE, 2 * 1024 * 1024)]


def test_filter_size_invalid_unit_raises():
    with pytest.raises(QueryParseError):
        parse("size:1TB")


def test_filter_size_invalid_number_raises():
    with pytest.raises(QueryParseError):
        parse("size:abcMB")


# ---------------------------------------------------------------------------
# filter: before / after
# ---------------------------------------------------------------------------


def test_filter_after_date_only():
    spec = parse("after:2026-04-01")
    assert spec.filters == [
        Filter("after", Op.GE, _ts("2026-04-01", end_of_day=False))
    ]


def test_filter_before_date_only_uses_end_of_day():
    spec = parse("before:2026-04-01")
    assert spec.filters == [
        Filter("before", Op.LE, _ts("2026-04-01", end_of_day=True))
    ]


def test_filter_after_with_explicit_time():
    spec = parse("after:2026-04-01T09:30")
    assert spec.filters == [
        Filter("after", Op.GE, _ts("2026-04-01T09:30"))
    ]


def test_filter_bad_date_raises():
    with pytest.raises(QueryParseError):
        parse("after:not-a-date")


# ---------------------------------------------------------------------------
# filter: is
# ---------------------------------------------------------------------------


def test_filter_is_starred():
    spec = parse("is:starred")
    assert spec.filters == [Filter("is", Op.EQ, "starred")]


def test_filter_is_text():
    spec = parse("is:text")
    assert spec.filters == [Filter("is", Op.EQ, "text")]


def test_filter_is_image():
    spec = parse("is:image")
    assert spec.filters == [Filter("is", Op.EQ, "image")]


def test_filter_is_unknown_raises():
    with pytest.raises(QueryParseError):
        parse("is:video")


# ---------------------------------------------------------------------------
# 否定
# ---------------------------------------------------------------------------


def test_negated_filter():
    spec = parse("-from:chrome")
    assert spec.filters == [Filter("from", Op.EQ, "chrome", negate=True)]


def test_negated_size_filter():
    spec = parse("-size:>1MB")
    assert spec.filters == [Filter("size", Op.GT, 1024 * 1024, negate=True)]


def test_leading_dash_on_plain_keyword_not_negation():
    """普通关键词前的 ``-`` 不做否定，整段作为 word 保留。"""
    spec = parse("-foo")
    assert spec.filters == []
    assert spec.keywords == ["-foo"]


# ---------------------------------------------------------------------------
# 混合场景 + 复杂样例
# ---------------------------------------------------------------------------


def test_full_example_from_spec():
    spec = parse("from:chrome tag:work after:2026-04-01 /hello.*world/ size:>1MB")
    assert spec.keywords == []
    assert spec.exact_phrases == []
    assert spec.regex == ["hello.*world"]
    assert spec.filters == [
        Filter("from", Op.EQ, "chrome"),
        Filter("tag", Op.EQ, "work"),
        Filter("after", Op.GE, _ts("2026-04-01")),
        Filter("size", Op.GT, 1024 * 1024),
    ]


def test_mixed_keywords_phrase_filter():
    spec = parse('python "api docs" tag:work')
    assert spec.keywords == ["python"]
    assert spec.exact_phrases == ["api docs"]
    assert spec.filters == [Filter("tag", Op.EQ, "work")]


def test_unknown_key_with_colon_stays_word():
    """非 filter key 的 ``foo:bar`` 当作普通关键词。"""
    spec = parse("foo:bar hello")
    assert spec.filters == []
    assert spec.keywords == ["foo:bar", "hello"]


# ---------------------------------------------------------------------------
# 其他错误分支
# ---------------------------------------------------------------------------


def test_empty_from_value_raises():
    with pytest.raises(QueryParseError):
        parse("from:")


def test_tag_with_quoted_value_raises():
    """规格：``tag:"x y"`` 不支持。我们在 tokenize 阶段会把整个值读下来，
    然后 filter 值含引号字符被视为非法空格（实际含 ``"`` 和内部空格）→ 报错。"""
    with pytest.raises(QueryParseError):
        parse('tag:"my tag"')


# ---------------------------------------------------------------------------
# fts_match_expression()
# ---------------------------------------------------------------------------


def test_fts_expression_empty():
    assert QuerySpec().fts_match_expression() == ""


def test_fts_expression_single_keyword():
    spec = parse("python")
    assert spec.fts_match_expression() == "python"


def test_fts_expression_multiple_keywords_space_joined():
    spec = parse("python code")
    assert spec.fts_match_expression() == "python code"


def test_fts_expression_phrase_wrapped_in_quotes():
    spec = parse('"hello world"')
    assert spec.fts_match_expression() == '"hello world"'


def test_fts_expression_phrase_plus_keyword():
    spec = parse('"hello world" python')
    # phrases 先于 keywords
    assert spec.fts_match_expression() == '"hello world" python'


def test_fts_expression_escapes_inner_quote():
    spec = QuerySpec(exact_phrases=['he said "hi"'])
    assert spec.fts_match_expression() == '"he said ""hi"""'


def test_fts_expression_preserves_prefix_star():
    spec = parse("py*")
    assert spec.fts_match_expression() == "py*"


def test_fts_expression_quotes_keyword_with_special_chars():
    # 含点号等特殊字符会被 FTS5 视为语法字符 → 加引号保护
    spec = QuerySpec(keywords=["foo.bar"])
    assert spec.fts_match_expression() == '"foo.bar"'


def test_fts_expression_filters_do_not_leak_into_match():
    """filters 不应进入 FTS 表达式，只有 keywords/phrases 会。"""
    spec = parse("tag:work python")
    assert spec.fts_match_expression() == "python"
