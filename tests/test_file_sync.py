"""文件同步核心逻辑测试（不依赖 Qt 事件循环）。"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.file_models import CloudFile, FileSyncState
from core.file_repository import CloudFileRepository


@pytest.fixture
def repo(tmp_path):
    db = DatabaseManager(str(tmp_path / "f.db"))
    r = CloudFileRepository(db)
    yield r
    db.close()


def test_schema_v4_tables_exist(repo):
    with repo.db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('cloud_files', 'cloud_file_upload_parts')"
        )
        names = {row[0] for row in cursor.fetchall()}
        assert "cloud_files" in names
        assert "cloud_file_upload_parts" in names

    with repo.db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT value FROM app_meta WHERE key='schema_version'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert int(row[0]) >= 4


def test_add_and_list_file(repo):
    f = CloudFile(
        name="a.txt", content_sha256="a" * 64, size_bytes=123,
        device_id="dev1", mtime=1000, created_at=1000,
    )
    fid = repo.add_file(f)
    assert fid > 0
    files = repo.list_files()
    assert len(files) == 1
    assert files[0].name == "a.txt"


def test_sha_uniqueness_on_undeleted(repo):
    f1 = CloudFile(name="a.txt", content_sha256="b" * 64, device_id="d", mtime=1, created_at=1)
    repo.add_file(f1)
    f2 = CloudFile(name="a2.txt", content_sha256="b" * 64, device_id="d", mtime=2, created_at=2)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_file(f2)


def test_mark_deleted_allows_re_add(repo):
    f1 = CloudFile(name="a.txt", content_sha256="c" * 64, device_id="d", mtime=1, created_at=1)
    fid = repo.add_file(f1)
    repo.mark_deleted(fid)
    f2 = CloudFile(name="a2.txt", content_sha256="c" * 64, device_id="d", mtime=2, created_at=2)
    new_id = repo.add_file(f2)
    assert new_id != fid


def test_parts_record_and_retrieve(repo):
    f = CloudFile(name="a.bin", content_sha256="d" * 64, device_id="d", mtime=1, created_at=1, size_bytes=1024)
    fid = repo.add_file(f)
    repo.record_part(fid, 1, "etag-1")
    repo.record_part(fid, 2, "etag-2")
    parts = repo.get_parts(fid)
    assert parts == {1: "etag-1", 2: "etag-2"}
    repo.clear_parts(fid)
    assert repo.get_parts(fid) == {}


def test_list_by_states_filters(repo):
    f1 = CloudFile(name="1", content_sha256="e" * 64, device_id="d", mtime=1, created_at=1,
                   sync_state=FileSyncState.PENDING.value)
    f2 = CloudFile(name="2", content_sha256="f" * 64, device_id="d", mtime=1, created_at=1,
                   sync_state=FileSyncState.SYNCED.value)
    id1 = repo.add_file(f1)
    repo.add_file(f2)
    pending = repo.list_by_states([FileSyncState.PENDING.value])
    assert len(pending) == 1
    assert pending[0].id == id1


def test_total_used_bytes(repo):
    for i in range(3):
        repo.add_file(CloudFile(
            name=f"{i}", content_sha256=str(i) * 64, device_id="d",
            mtime=1, created_at=1, size_bytes=100 * (i + 1),
        ))
    total = repo.total_used_bytes()
    assert total == 100 + 200 + 300
