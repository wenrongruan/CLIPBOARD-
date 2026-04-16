"""ClipboardRepository CRUD 测试"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.database import DatabaseManager
from core.repository import ClipboardRepository
from core.models import ClipboardItem, TextClipboardItem, ImageClipboardItem, ContentType


@pytest.fixture
def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    repository = ClipboardRepository(db)
    yield repository
    db.close()


def _make_item(text="hello", hash_suffix="", device_id="dev1", starred=False):
    """构造测试用文本条目（TextClipboardItem 是 sealed union 的文本变体）"""
    return TextClipboardItem(
        text_content=text,
        content_hash=f"hash_{text}_{hash_suffix}",
        preview=text[:50],
        device_id=device_id,
        device_name="TestPC",
        created_at=1000,
        is_starred=starred,
    )


class TestAddAndGet:
    def test_add_item(self, repo):
        item = _make_item("test1")
        item_id = repo.add_item(item)
        assert item_id > 0

    def test_get_by_hash(self, repo):
        item = _make_item("findme")
        repo.add_item(item)

        found = repo.get_by_hash(item.content_hash)
        assert found is not None
        assert found.text_content == "findme"

    def test_get_by_hash_not_found(self, repo):
        result = repo.get_by_hash("nonexistent")
        assert result is None

    def test_get_item_by_id(self, repo):
        item = _make_item("byid")
        item_id = repo.add_item(item)

        found = repo.get_item_by_id(item_id)
        assert found is not None
        assert found.id == item_id
        assert found.text_content == "byid"

    def test_get_item_by_id_not_found(self, repo):
        result = repo.get_item_by_id(99999)
        assert result is None


class TestPagination:
    def test_get_items_empty(self, repo):
        items, total = repo.get_items(page=0, page_size=10)
        assert items == []
        assert total == 0

    def test_get_items_pagination(self, repo):
        for i in range(15):
            repo.add_item(_make_item(f"item_{i}", hash_suffix=str(i)))

        items, total = repo.get_items(page=0, page_size=10)
        assert len(items) == 10
        assert total == 15

        items2, _ = repo.get_items(page=1, page_size=10)
        assert len(items2) == 5

    def test_starred_only(self, repo):
        repo.add_item(_make_item("normal", hash_suffix="1"))
        repo.add_item(_make_item("star", hash_suffix="2", starred=True))

        items, total = repo.get_items(page=0, page_size=10, starred_only=True)
        assert total == 1
        assert items[0].text_content == "star"


class TestSearch:
    def test_search_finds_match(self, repo):
        repo.add_item(_make_item("python programming", hash_suffix="1"))
        repo.add_item(_make_item("java code", hash_suffix="2"))

        items, total = repo.search("python")
        assert total >= 1
        assert any("python" in it.text_content for it in items)

    def test_search_no_match(self, repo):
        repo.add_item(_make_item("hello world", hash_suffix="1"))

        items, total = repo.search("zzzznotfound")
        assert total == 0


class TestDeleteAndStar:
    def test_delete_item(self, repo):
        item_id = repo.add_item(_make_item("to_delete"))
        assert repo.delete_item(item_id) is True

        found = repo.get_item_by_id(item_id)
        assert found is None

    def test_delete_nonexistent(self, repo):
        assert repo.delete_item(99999) is False

    def test_toggle_star(self, repo):
        item_id = repo.add_item(_make_item("star_test"))

        # 第一次 toggle: 0 -> 1
        repo.toggle_star(item_id)
        item = repo.get_item_by_id(item_id)
        assert item.is_starred is True

        # 第二次 toggle: 1 -> 0
        repo.toggle_star(item_id)
        item = repo.get_item_by_id(item_id)
        assert item.is_starred is False


class TestCloudSync:
    def test_set_and_get_cloud_id(self, repo):
        item_id = repo.add_item(_make_item("cloud_test"))
        repo.set_cloud_id(item_id, 100)

        item = repo.get_item_by_id(item_id)
        assert item.cloud_id == 100

    def test_set_cloud_ids_bulk(self, repo):
        id1 = repo.add_item(_make_item("bulk1", hash_suffix="1"))
        id2 = repo.add_item(_make_item("bulk2", hash_suffix="2"))

        repo.set_cloud_ids_bulk([(id1, 101), (id2, 102)])

        item1 = repo.get_item_by_id(id1)
        item2 = repo.get_item_by_id(id2)
        assert item1.cloud_id == 101
        assert item2.cloud_id == 102

    def test_clear_cloud_id(self, repo):
        item_id = repo.add_item(_make_item("clear_test"))
        repo.set_cloud_id(item_id, 200)
        repo.clear_cloud_id(item_id)

        item = repo.get_item_by_id(item_id)
        assert item.cloud_id is None

    def test_get_by_cloud_id(self, repo):
        item_id = repo.add_item(_make_item("by_cloud"))
        repo.set_cloud_id(item_id, 300)

        found = repo.get_by_cloud_id(300)
        assert found is not None
        assert found.text_content == "by_cloud"

    def test_get_new_items_since(self, repo):
        repo.add_item(_make_item("mine", hash_suffix="1", device_id="dev_self"))
        repo.add_item(_make_item("theirs", hash_suffix="2", device_id="dev_other"))

        items = repo.get_new_items_since(0, "dev_self")
        texts = [it.text_content for it in items]
        assert "theirs" in texts
        assert "mine" not in texts


class TestCleanup:
    def test_cleanup_old_items(self, repo):
        for i in range(20):
            repo.add_item(_make_item(f"item_{i}", hash_suffix=str(i)))

        deleted = repo.cleanup_old_items(max_items=10)
        assert deleted == 10

        _, total = repo.get_items(page=0, page_size=100)
        assert total == 10

    def test_cleanup_preserves_starred(self, repo):
        repo.add_item(_make_item("starred", hash_suffix="s", starred=True))
        for i in range(5):
            repo.add_item(_make_item(f"normal_{i}", hash_suffix=str(i)))

        repo.cleanup_old_items(max_items=3)

        _, total = repo.get_items(page=0, page_size=100, starred_only=True)
        assert total == 1


class TestBatchOperations:
    def test_get_existing_hashes_empty(self, repo):
        result = repo.get_existing_hashes([])
        assert result == {}

    def test_get_existing_hashes_found(self, repo):
        item1 = _make_item("batch1", hash_suffix="1")
        item2 = _make_item("batch2", hash_suffix="2")
        repo.add_item(item1)
        repo.add_item(item2)

        result = repo.get_existing_hashes([item1.content_hash, item2.content_hash, "nonexistent"])
        assert len(result) == 2
        assert item1.content_hash in result
        assert item2.content_hash in result
        assert "nonexistent" not in result

    def test_get_existing_hashes_large_batch(self, repo):
        """测试超过 500 条的分批查询"""
        hashes = []
        for i in range(10):
            item = _make_item(f"large_{i}", hash_suffix=str(i))
            repo.add_item(item)
            hashes.append(item.content_hash)

        # 添加大量不存在的 hash 来测试分批逻辑
        hashes.extend([f"fake_hash_{i}" for i in range(600)])

        result = repo.get_existing_hashes(hashes)
        assert len(result) == 10


class TestHashUtils:
    def test_compute_content_hash_string(self):
        from utils.hash_utils import compute_content_hash
        h = compute_content_hash("hello")
        assert len(h) == 32
        # 确定性
        assert compute_content_hash("hello") == h

    def test_compute_content_hash_bytes(self):
        from utils.hash_utils import compute_content_hash
        h = compute_content_hash(b"\x89PNG")
        assert len(h) == 32

    def test_different_inputs_different_hashes(self):
        from utils.hash_utils import compute_content_hash
        assert compute_content_hash("a") != compute_content_hash("b")


class TestUpdateItemContentCrossType:
    def _fetch_row(self, repo, item_id):
        def op(conn):
            cur = conn.execute(
                "SELECT content_type, text_content, image_data, image_thumbnail, preview "
                "FROM clipboard_items WHERE id = ?",
                (item_id,),
            )
            return cur.fetchone()
        return repo.db.execute_with_retry(op)

    def test_replace_image_to_text_clears_image_payload(self, repo):
        item = ImageClipboardItem(
            image_data=b"\x89PNGfake",
            image_thumbnail=b"thumb",
            content_hash="hash_img",
            preview="[图片]",
            device_id="dev1",
            device_name="TestPC",
            created_at=1000,
        )
        item_id = repo.add_item(item)

        ok = repo.update_item_content(
            item_id, text_content="replaced text", content_type="text"
        )
        assert ok is True

        row = self._fetch_row(repo, item_id)
        assert row[0] == "text"
        assert row[1] == "replaced text"
        assert row[2] is None
        assert row[3] is None

    def test_replace_text_to_image_clears_text_payload(self, repo):
        item = _make_item("original text", hash_suffix="cross1")
        item_id = repo.add_item(item)

        ok = repo.update_item_content(
            item_id, image_data=b"\x89PNGfake2", content_type="image"
        )
        assert ok is True

        row = self._fetch_row(repo, item_id)
        assert row[0] == "image"
        assert row[1] is None
        assert row[2] == b"\x89PNGfake2"
        assert row[4] == ""
