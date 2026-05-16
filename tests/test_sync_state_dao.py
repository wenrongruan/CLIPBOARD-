"""SyncStateDAO 单元测试。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.db.clipboard_dao import ClipboardDAO
from core.db.sync_state_dao import SyncStateDAO
from core.models import TextClipboardItem


@pytest.fixture
def daos(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    yield ClipboardDAO(db), SyncStateDAO(db)
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


def test_set_cloud_id_and_lookup(daos):
    dao, sync = daos
    iid = dao.add_item(_mk("a", h="c1"))
    sync.set_cloud_id(iid, 12345)
    found = sync.get_by_cloud_id(12345)
    assert found is not None
    assert found.id == iid


def test_clear_cloud_id(daos):
    dao, sync = daos
    iid = dao.add_item(_mk("a", h="c2"))
    sync.set_cloud_id(iid, 999)
    sync.clear_cloud_id(iid)
    assert sync.get_by_cloud_id(999) is None


def test_get_unsynced_items(daos):
    dao, sync = daos
    iid1 = dao.add_item(_mk("a", h="u1", ts=1000))
    iid2 = dao.add_item(_mk("b", h="u2", ts=1001))
    sync.set_cloud_id(iid1, 1)
    unsynced = sync.get_unsynced_items(limit=10)
    ids = {i.id for i in unsynced}
    assert iid2 in ids
    assert iid1 not in ids


def test_get_starred_unsynced(daos):
    dao, sync = daos
    iid = dao.add_item(_mk("a", h="s1"))
    dao.toggle_star(iid)
    starred = sync.get_starred_unsynced(limit=10)
    assert any(i.id == iid for i in starred)
