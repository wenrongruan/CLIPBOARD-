"""SpaceService 单元测试：本地 spaces / space_members CRUD + 当前 space 状态。"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.db_migrations import run_migrations
from core.repository import ClipboardRepository
from core.space_service import Space, SpaceMember, SpaceService

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"


@pytest.fixture
def repo(tmp_path):
    """临时 SQLite repository + 应用 v3.4 迁移。"""
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)

    # 应用 v3.4 迁移以创建 spaces / space_members / tag_definitions / clipboard_tags / share_links
    with db.get_connection() as conn:
        run_migrations(conn, _MIGRATIONS_DIR, dialect="sqlite", db_path=Path(db_path))

    repository = ClipboardRepository(db)
    yield repository
    db.close()


@pytest.fixture
def service(repo):
    return SpaceService(repo)


class TestSpaceCRUD:
    def test_create_space_returns_populated_object(self, service):
        s = service.create_space("团队 A", type_="team", owner_user_id="user1")
        assert s.id
        assert s.name == "团队 A"
        assert s.type == "team"
        assert s.owner_user_id == "user1"
        assert s.created_at > 0
        assert s.updated_at == s.created_at

    def test_list_spaces_empty(self, service):
        assert service.list_spaces() == []

    def test_list_spaces_sorted(self, service):
        a = service.create_space("A")
        b = service.create_space("B")
        names = [s.name for s in service.list_spaces()]
        assert names == ["A", "B"]
        # 确保 id 是两个新建的
        ids = {s.id for s in service.list_spaces()}
        assert ids == {a.id, b.id}

    def test_get_space(self, service):
        s = service.create_space("X")
        got = service.get_space(s.id)
        assert got is not None
        assert got.id == s.id
        assert got.name == "X"

    def test_get_space_missing(self, service):
        assert service.get_space("nonexistent") is None
        assert service.get_space("") is None

    def test_update_space(self, service):
        s = service.create_space("old")
        updated = service.update_space(s.id, "new")
        assert updated.name == "new"
        # 数据库中也更新了
        refetch = service.get_space(s.id)
        assert refetch.name == "new"

    def test_delete_space(self, service):
        s = service.create_space("to_delete")
        service.delete_space(s.id)
        assert service.get_space(s.id) is None

    def test_delete_space_resets_current(self, service):
        s = service.create_space("cur")
        service.set_current_space(s.id)
        assert service.get_current_space_id() == s.id
        service.delete_space(s.id)
        assert service.get_current_space_id() is None


class TestMembers:
    def test_add_and_list_members(self, service):
        s = service.create_space("team")
        m1 = service.add_member(s.id, "u1", "owner", invited_by="sys")
        m2 = service.add_member(s.id, "u2", "editor")

        members = service.list_members(s.id)
        assert len(members) == 2
        user_ids = {m.user_id for m in members}
        assert user_ids == {"u1", "u2"}

        # invited_by = "" 应存成 None
        u2 = next(m for m in members if m.user_id == "u2")
        assert u2.invited_by is None
        u1 = next(m for m in members if m.user_id == "u1")
        assert u1.invited_by == "sys"
        assert m1.role == "owner"
        assert m2.role == "editor"

    def test_update_member_role(self, service):
        s = service.create_space("team")
        service.add_member(s.id, "u1", "editor")
        service.update_member_role(s.id, "u1", "owner")
        members = service.list_members(s.id)
        assert members[0].role == "owner"

    def test_remove_member(self, service):
        s = service.create_space("team")
        service.add_member(s.id, "u1", "editor")
        service.remove_member(s.id, "u1")
        assert service.list_members(s.id) == []

    def test_list_members_empty(self, service):
        s = service.create_space("team")
        assert service.list_members(s.id) == []

    def test_list_members_only_for_given_space(self, service):
        s1 = service.create_space("a")
        s2 = service.create_space("b")
        service.add_member(s1.id, "u1", "owner")
        service.add_member(s2.id, "u2", "owner")
        s1_members = service.list_members(s1.id)
        assert {m.user_id for m in s1_members} == {"u1"}


class TestCurrentSpace:
    def test_default_is_personal(self, service):
        # 首次访问应返回 None（个人空间）
        assert service.get_current_space_id() is None

    def test_set_and_get_current(self, service):
        s = service.create_space("active")
        service.set_current_space(s.id)
        assert service.get_current_space_id() == s.id

    def test_set_to_none_means_personal(self, service):
        s = service.create_space("active")
        service.set_current_space(s.id)
        service.set_current_space(None)
        assert service.get_current_space_id() is None

    def test_set_to_empty_string_means_personal(self, service):
        s = service.create_space("active")
        service.set_current_space(s.id)
        service.set_current_space("")
        assert service.get_current_space_id() is None

    def test_set_nonexistent_raises(self, service):
        with pytest.raises(ValueError):
            service.set_current_space("nonexistent-id")


class TestUpsertFromRemote:
    def test_upsert_insert(self, service):
        s = service.upsert_from_remote({
            "id": "remote-1",
            "name": "远程",
            "type": "team",
            "owner_user_id": "user-x",
            "created_at": 100,
            "updated_at": 200,
        })
        assert isinstance(s, Space)
        assert s.id == "remote-1"
        got = service.get_space("remote-1")
        assert got.name == "远程"
        assert got.owner_user_id == "user-x"
        assert got.updated_at == 200

    def test_upsert_update_existing(self, service):
        service.upsert_from_remote({
            "id": "remote-1",
            "name": "old",
            "type": "team",
            "owner_user_id": "u",
            "created_at": 100,
            "updated_at": 100,
        })
        service.upsert_from_remote({
            "id": "remote-1",
            "name": "new",
            "type": "team",
            "owner_user_id": "u",
            "created_at": 100,
            "updated_at": 300,
        })
        got = service.get_space("remote-1")
        assert got.name == "new"
        assert got.updated_at == 300

    def test_upsert_member_from_remote(self, service):
        s = service.create_space("team")
        m = service.upsert_member_from_remote({
            "space_id": s.id,
            "user_id": "u1",
            "role": "editor",
            "joined_at": 12345,
            "invited_by": "admin",
        })
        assert isinstance(m, SpaceMember)
        members = service.list_members(s.id)
        assert len(members) == 1
        assert members[0].invited_by == "admin"

        # 再次 upsert 相同主键 → 更新 role
        service.upsert_member_from_remote({
            "space_id": s.id,
            "user_id": "u1",
            "role": "owner",
            "joined_at": 12345,
            "invited_by": None,
        })
        members = service.list_members(s.id)
        assert len(members) == 1
        assert members[0].role == "owner"
        assert members[0].invited_by is None
