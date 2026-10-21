"""TagService 单元测试：tag_definitions CRUD + 打标签便利方法。"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.db_migrations import run_migrations
from core.models import TextClipboardItem
from core.repository import ClipboardRepository
from core.tag_service import TagDefinition, TagService

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"


@pytest.fixture
def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    with db.get_connection() as conn:
        run_migrations(conn, _MIGRATIONS_DIR, dialect="sqlite", db_path=Path(db_path))
    repository = ClipboardRepository(db)
    yield repository
    db.close()


@pytest.fixture
def service(repo):
    return TagService(repo)


def _make_item(repo, text="note", hash_suffix="x"):
    item = TextClipboardItem(
        text_content=text,
        content_hash=f"h_{text}_{hash_suffix}",
        preview=text,
        device_id="dev",
        device_name="pc",
        created_at=1000,
    )
    return repo.add_item(item)


class TestTagCRUD:
    def test_create_tag(self, service):
        t = service.create_tag("", "work", color="#ff0000")
        assert t.id
        assert t.name == "work"
        assert t.color == "#ff0000"
        assert t.space_id == ""

    def test_create_tag_requires_name(self, service):
        with pytest.raises(ValueError):
            service.create_tag("", "")

    def test_list_tags_all_spaces(self, service):
        service.create_tag("", "personal-tag")
        service.create_tag("space-1", "team-tag")
        tags = service.list_tags(None)
        names = {t.name for t in tags}
        assert names == {"personal-tag", "team-tag"}

    def test_list_tags_filtered_by_space(self, service):
        service.create_tag("", "p")
        service.create_tag("space-1", "t")
        personal = service.list_tags("")
        assert [t.name for t in personal] == ["p"]
        team = service.list_tags("space-1")
        assert [t.name for t in team] == ["t"]

    def test_get_tag_by_name(self, service):
        t = service.create_tag("", "foo", color="#aabbcc")
        got = service.get_tag_by_name("", "foo")
        assert got is not None
        assert got.id == t.id
        assert got.color == "#aabbcc"
        # 不同 space_id 应拿不到
        assert service.get_tag_by_name("other", "foo") is None

    def test_update_tag(self, service):
        t = service.create_tag("", "old", color="#111111")
        updated = service.update_tag(t.id, name="new", color="#222222")
        assert updated.name == "new"
        assert updated.color == "#222222"
        # 再读一次确认
        refetch = service.get_tag_by_name("", "new")
        assert refetch is not None

    def test_update_tag_only_color(self, service):
        t = service.create_tag("", "keep", color="#000000")
        updated = service.update_tag(t.id, color="#ffffff")
        assert updated.name == "keep"
        assert updated.color == "#ffffff"

    def test_delete_tag_cascades_clipboard_tags(self, service, repo):
        t = service.create_tag("", "bye")
        item_id = _make_item(repo, "item1", hash_suffix="1")
        service.apply_tag_names(item_id, "", ["bye"])

        # 删除前有关联
        def count_rel(conn):
            return repo.db.fetch_scalar(
                conn, "SELECT COUNT(*) FROM clipboard_tags WHERE tag_id = ?", (t.id,)
            )
        assert repo.db.execute_read(count_rel) == 1

        service.delete_tag(t.id)
        assert service.get_tag_by_name("", "bye") is None
        assert repo.db.execute_read(count_rel) == 0


class TestApplyTagNames:
    def test_apply_creates_missing_tags(self, service, repo):
        item_id = _make_item(repo, "itA")
        ids = service.apply_tag_names(item_id, "", ["alpha", "beta"])
        assert len(ids) == 2
        tags = {t.name: t.id for t in service.list_tags("")}
        assert set(tags.keys()) == {"alpha", "beta"}
        assert set(ids) == set(tags.values())

    def test_apply_reuses_existing_tag(self, service, repo):
        existing = service.create_tag("", "reuse")
        item_id = _make_item(repo, "itB")
        ids = service.apply_tag_names(item_id, "", ["reuse"])
        assert ids == [existing.id]
        # 不应新建多余 tag
        assert len(service.list_tags("")) == 1

    def test_apply_is_idempotent_on_same_item(self, service, repo):
        item_id = _make_item(repo, "itC")
        service.apply_tag_names(item_id, "", ["tag1"])
        service.apply_tag_names(item_id, "", ["tag1"])

        def count_rel(conn):
            return repo.db.fetch_scalar(
                conn, "SELECT COUNT(*) FROM clipboard_tags WHERE item_id = ?", (item_id,)
            )
        assert repo.db.execute_read(count_rel) == 1

    def test_apply_empty_returns_empty(self, service, repo):
        item_id = _make_item(repo, "itD")
        assert service.apply_tag_names(item_id, "", []) == []

    def test_apply_dedupes_within_call(self, service, repo):
        item_id = _make_item(repo, "itE")
        ids = service.apply_tag_names(item_id, "", ["dup", "dup", "unique"])
        assert len(ids) == 2
