"""ClipboardQuery 单元测试。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.db.clipboard_dao import ClipboardDAO
from core.db.clipboard_query import ClipboardQuery
from core.models import TextClipboardItem
from core.query_parser import parse as parse_query


@pytest.fixture
def dao_and_query(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    dao = ClipboardDAO(db)
    q = ClipboardQuery(db, dao)
    yield dao, q
    db.close()


def _mk(text, h, ts=1000):
    return TextClipboardItem(
        text_content=text,
        content_hash=h,
        preview=text[:50],
        device_id="dev1",
        device_name="TestPC",
        created_at=ts,
    )


def test_get_items_pagination(dao_and_query):
    dao, q = dao_and_query
    for i in range(5):
        dao.add_item(_mk(f"item{i}", h=f"h{i}", ts=1000 + i))
    page1, total = q.get_items(page=0, page_size=2)
    page2, _ = q.get_items(page=1, page_size=2)
    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0].text_content != page2[0].text_content


def test_search_by_keyword(dao_and_query):
    dao, q = dao_and_query
    dao.add_item(_mk("hello world", h="hw1"))
    dao.add_item(_mk("foo bar", h="hw2", ts=1001))
    items, total = q.search_by_keyword("hello")
    assert total == 1
    assert "hello" in items[0].text_content


def test_search_query_spec(dao_and_query):
    """search() 走 QuerySpec, 验证 starred:true 语法。"""
    dao, q = dao_and_query
    iid = dao.add_item(_mk("a", h="qa"))
    dao.toggle_star(iid)
    dao.add_item(_mk("b", h="qb", ts=1001))
    spec = parse_query("is:starred")
    results = q.search(spec)
    assert len(results) >= 1
    assert all(item.is_starred for item in results)


def test_get_timeline_groups_by_day(dao_and_query):
    dao, q = dao_and_query
    # created_at 使用毫秒
    dao.add_item(_mk("a", h="t1", ts=1_700_000_000_000))
    dao.add_item(_mk("b", h="t2", ts=1_700_086_400_000))  # +1 天
    timeline = q.get_timeline(
        start_ts=1_700_000_000_000 - 1,
        end_ts=1_700_086_400_000 + 1,
        granularity="day",
    )
    assert len(timeline) >= 2
    total_cnt = sum(t["count"] for t in timeline)
    assert total_cnt == 2
