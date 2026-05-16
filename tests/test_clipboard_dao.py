"""ClipboardDAO 单元测试。

使用 DatabaseManager 直接构造，与 tests/test_repository.py 风格保持一致。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.db.clipboard_dao import ClipboardDAO
from core.models import TextClipboardItem


@pytest.fixture
def dao(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    yield ClipboardDAO(db)
    db.close()


def _mk(text="hello", h="h1"):
    return TextClipboardItem(
        text_content=text,
        content_hash=h,
        preview=text[:50],
        device_id="dev1",
        device_name="TestPC",
        created_at=1000,
    )


def test_add_item_returns_id(dao):
    item_id = dao.add_item(_mk("hello", h="h1"))
    assert item_id > 0


def test_get_by_hash(dao):
    dao.add_item(_mk("hello", h="h2"))
    fetched = dao.get_by_hash("h2")
    assert fetched is not None
    assert fetched.text_content == "hello"


def test_delete_item(dao):
    iid = dao.add_item(_mk("x", h="h3"))
    assert dao.delete_item(iid) is True
    assert dao.get_item_by_id(iid) is None


def test_toggle_star(dao):
    iid = dao.add_item(_mk("x", h="h4"))
    # toggle_star 返回 rowcount>0；状态需要通过 get_item_by_id 验证
    assert dao.toggle_star(iid) is True
    assert dao.get_item_by_id(iid).is_starred is True
    assert dao.toggle_star(iid) is True
    assert dao.get_item_by_id(iid).is_starred is False


def test_meta_get_set(dao):
    dao.set_meta("k1", "v1")
    assert dao.get_meta("k1") == "v1"
    assert dao.get_meta("missing", default="d") == "d"


def test_tags_attach_detach(dao):
    iid = dao.add_item(_mk("x", h="h5"))
    # clipboard_tags 没有外键约束，tag_id 可以是任意字符串
    dao.add_tags_to_item(iid, ["t1", "t2"])
    assert set(dao.get_tags_for_item(iid)) == {"t1", "t2"}
    dao.remove_tags_from_item(iid, ["t1"])
    assert dao.get_tags_for_item(iid) == ["t2"]
