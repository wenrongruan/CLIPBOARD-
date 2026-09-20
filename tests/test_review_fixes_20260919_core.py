"""2026-09-19 core 审查缺陷的回归测试。"""

import logging
import sqlite3
from unittest.mock import MagicMock

from PySide6.QtGui import QColor, QImage

from core.cloud_sync_service import _SyncWorker
from core.database import DatabaseManager
from core.file_sync_service import FileCloudSyncService, _FileSyncWorker
from core.file_repository import CloudFileRepository
from core.migration import DatabaseMigrator
from core.models import TextClipboardItem
from core.repository import ClipboardRepository


def _item(content_hash, space_id=None):
    return TextClipboardItem(
        text_content="same text", content_hash=content_hash,
        device_id="device", device_name="Device", created_at=1,
        space_id=space_id,
    )


def test_team_pull_does_not_bind_cloud_id_to_personal_item(tmp_path, qapp):
    db = DatabaseManager(str(tmp_path / "spaces.db"))
    repo = ClipboardRepository(db)
    try:
        personal_id = repo.add_item(_item("same-hash"))
        api = MagicMock()
        api.sync.return_value = {"items": [{
            "id": 77, "content_type": "text", "text_content": "same text",
            "content_hash": "same-hash", "device_id": "other",
            "device_name": "Other", "created_at": 2, "space_id": "team-1",
        }]}
        worker = _SyncWorker(api, repo)
        worker.do_pull("team-1", 0)

        personal = repo.get_item_by_id(personal_id)
        team = repo.get_existing_hashes(
            ["same-hash"], space_id="team-1", space_scoped=True
        )["same-hash"]
        assert team.id != personal.id
        assert team.cloud_id == 77
        assert personal.cloud_id is None
    finally:
        db.close()


def test_starred_sync_keeps_same_hash_cloud_ids_separate_by_space(tmp_path, qapp):
    db = DatabaseManager(str(tmp_path / "starred-spaces.db"))
    repo = ClipboardRepository(db)
    try:
        personal = _item("same-hash")
        personal.is_starred = True
        team = _item("same-hash", "team-1")
        team.is_starred = True
        personal_id = repo.add_item(personal)
        team_id = repo.add_item(team)

        api = MagicMock()

        def upload(items):
            scope = items[0].get("space_id")
            return [{
                "id": 22 if scope else 11,
                "content_hash": "same-hash",
                "space_id": scope,
            }]

        api.upload_items.side_effect = upload
        worker = _SyncWorker(api, repo)
        worker.do_starred_sync()
        assert api.upload_items.call_count == 2
        assert repo.get_item_by_id(personal_id).cloud_id == 11
        assert repo.get_item_by_id(team_id).cloud_id == 22
    finally:
        db.close()


def test_team_pull_keeps_first_cloud_id_for_duplicate_author_rows(tmp_path, qapp):
    db = DatabaseManager(str(tmp_path / "team-duplicates.db"))
    repo = ClipboardRepository(db)
    try:
        api = MagicMock()
        api.sync.return_value = {"items": [
            {"id": server_id, "content_type": "text", "text_content": "same",
             "content_hash": "same-hash", "device_id": f"device-{server_id}",
             "device_name": "Other", "created_at": server_id,
             "space_id": "team-1", "user_id": f"author-{server_id}"}
            for server_id in (71, 72)
        ]}
        worker = _SyncWorker(api, repo)
        done = []
        worker.pull_done.connect(lambda _space, _items, cursor: done.append(cursor))
        worker.do_pull("team-1", 0)
        saved = repo.get_existing_hashes(
            ["same-hash"], space_id="team-1", space_scoped=True
        )["same-hash"]
        assert saved.cloud_id == 71
        assert done == [72]
    finally:
        db.close()


def test_existing_global_unique_db_upgrades_without_losing_rows_or_fts(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(DatabaseManager.CREATE_TABLE_SQL)
        conn.executescript(DatabaseManager.CREATE_FTS_SQL)
        for column in ("cloud_id INTEGER", "space_id TEXT", "source_app TEXT", "source_title TEXT"):
            conn.execute(f"ALTER TABLE clipboard_items ADD COLUMN {column}")
        conn.execute(
            "INSERT INTO clipboard_items (content_type, text_content, content_hash, "
            "device_id, created_at) VALUES ('text', 'searchable text', 'old-hash', 'd', 1)"
        )
        conn.execute(
            "INSERT INTO clipboard_items (id, content_type, text_content, "
            "content_hash, device_id, created_at) "
            "VALUES (100, 'text', 'deleted high water', 'deleted-hash', 'd', 2)"
        )
        conn.execute("DELETE FROM clipboard_items WHERE id = 100")
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES ('schema_version', '4')"
        )
        conn.execute(
            "CREATE TABLE clipboard_tags (item_id INTEGER REFERENCES "
            "clipboard_items(id) ON DELETE CASCADE, tag_id TEXT, created_at INTEGER)"
        )
        conn.execute(
            "INSERT INTO clipboard_tags (item_id, tag_id, created_at) "
            "VALUES (1, 'tag-1', 1)"
        )
        conn.execute("CREATE INDEX idx_old_custom ON clipboard_items(device_name)")
        conn.execute(
            "CREATE TRIGGER trg_old_custom AFTER INSERT ON clipboard_items "
            "BEGIN UPDATE app_meta SET value = value WHERE key = 'schema_version'; END"
        )
        conn.commit()
    finally:
        conn.close()

    create_connection = DatabaseManager._create_connection

    def with_foreign_keys(self):
        connection = create_connection(self)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    monkeypatch.setattr(DatabaseManager, "_create_connection", with_foreign_keys)
    db = DatabaseManager(str(path))
    repo = ClipboardRepository(db)
    try:
        assert repo.get_meta("schema_version") == "5"
        assert repo.get_by_hash("old-hash").text_content == "searchable text"
        assert repo.add_item(_item("old-hash", "team-1")) == 101
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT rowid FROM clipboard_fts WHERE clipboard_fts MATCH 'searchable'"
            ).fetchall()
            tags = conn.execute("SELECT item_id, tag_id FROM clipboard_tags").fetchall()
            restored_objects = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name IN "
                    "('idx_old_custom', 'trg_old_custom', 'clipboard_ai')"
                )
            }
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert len(rows) == 1
        assert [tuple(row) for row in tags] == [(1, "tag-1")]
        assert restored_objects == {"idx_old_custom", "trg_old_custom", "clipboard_ai"}
        assert foreign_key_errors == []
    finally:
        db.close()


def test_database_migration_preserves_same_hash_in_two_spaces(tmp_path):
    src_db = DatabaseManager(str(tmp_path / "src.db"))
    dst_db = DatabaseManager(str(tmp_path / "dst.db"))
    try:
        src = ClipboardRepository(src_db)
        dst = ClipboardRepository(dst_db)
        src.add_item(_item("same-hash"))
        src.add_item(_item("same-hash", "team-1"))
        assert DatabaseMigrator(src, dst).migrate() == 2
        assert dst.get_existing_hashes(
            ["same-hash"], space_id=None, space_scoped=True
        )
        assert dst.get_existing_hashes(
            ["same-hash"], space_id="team-1", space_scoped=True
        )
    finally:
        src_db.close()
        dst_db.close()


def test_mysql_v7_migration_replaces_global_hash_unique_index():
    from core.mysql_database import MySQLDatabaseManager

    class Cursor:
        def __init__(self):
            self.sql = []
            self.last = ""

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql):
            self.sql.append(sql)
            self.last = sql

        def fetchone(self):
            if "schema_version" in self.last:
                return {"value": "6"}
            if "SHOW COLUMNS" in self.last:
                return None
            raise AssertionError(self.last)

        def fetchall(self):
            if "SHOW INDEX" in self.last:
                return [
                    {"Non_unique": 0, "Key_name": "PRIMARY", "Column_name": "id"},
                    {"Non_unique": 0, "Key_name": "content_hash", "Column_name": "content_hash"},
                ]
            raise AssertionError(self.last)

    cursor = Cursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    db = MySQLDatabaseManager.__new__(MySQLDatabaseManager)
    db._migrate_schema(conn)
    alter = next(sql for sql in cursor.sql if sql.startswith("ALTER TABLE clipboard_items"))
    assert "DROP INDEX `content_hash`" in alter
    assert "COALESCE(space_id, '')" in alter
    assert "ADD UNIQUE KEY uq_clipboard_space_hash (space_scope, content_hash)" in alter


def test_file_cursor_waits_for_failed_earlier_row(qapp):
    worker = _FileSyncWorker(MagicMock(), MagicMock(), MagicMock())
    worker._apply_remote_file = lambda srv, cid, sha, deleted, parsed: cid == 5
    page = [
        {"id": 4, "change_id": 10, "sha256": "a" * 64},
        {"id": 5, "change_id": 11, "sha256": "b" * 64},
    ]
    _, cursor = worker._process_page(page, 0)
    assert cursor == 9  # 下一轮仍会取到待重试的 change_id=10
    assert worker._pull_skip[10] == 1


def test_file_change_events_apply_rename_and_delete(tmp_path, qapp):
    db = DatabaseManager(str(tmp_path / "file-events.db"))
    repo = CloudFileRepository(db)
    worker = _FileSyncWorker(MagicMock(), repo, MagicMock())
    sha = "c" * 64
    try:
        page = [
            {"id": 4, "change_id": 10, "sha256": sha, "name": "old.txt",
             "device_id": "remote", "created_at": 1},
            {"id": 4, "change_id": 11, "sha256": sha, "name": "new.txt",
             "device_id": "remote", "created_at": 1},
            {"id": 4, "change_id": 12, "is_deleted": True},
        ]
        _, cursor = worker._process_page(page, 0)
        saved = repo.get_by_cloud_id(4)
        assert cursor == 12
        assert saved.name == "new.txt"
        assert saved.is_deleted is True
    finally:
        db.close()


def test_old_file_tombstone_does_not_delete_new_file_with_same_sha(tmp_path, qapp):
    db = DatabaseManager(str(tmp_path / "file-tombstone.db"))
    repo = CloudFileRepository(db)
    worker = _FileSyncWorker(MagicMock(), repo, MagicMock())
    sha = "d" * 64
    try:
        page = [
            {"id": 200, "change_id": 1, "sha256": sha, "name": "live.txt"},
            {"id": 100, "change_id": 2, "sha256": sha, "is_deleted": True},
            {"id": 200, "change_id": 3, "sha256": sha, "name": "live.txt"},
        ]
        _, cursor = worker._process_page(page, 0)
        saved = repo.get_by_cloud_id(200)
        assert cursor == 3
        assert saved is not None
        assert saved.is_deleted is False
        assert repo.get_by_cloud_id(100) is None
    finally:
        db.close()


def test_file_pull_uses_change_cursor_and_accepts_empty_page_advance(qapp):
    api = MagicMock()
    api.files_list.return_value = {
        "items": [], "has_more": False, "next_since_change_id": 19,
    }
    worker = _FileSyncWorker(api, MagicMock(), MagicMock())
    completed = []
    worker.pull_done.connect(lambda _items, cursor: completed.append(cursor))
    worker.do_pull(10)
    api.files_list.assert_called_once_with(
        device_id=worker._device_id, since_change_id=10
    )
    assert completed == [19]


def test_file_pull_does_not_retry_failed_page_twenty_times_in_one_tick(qapp):
    api = MagicMock()
    api.files_list.return_value = {
        "items": [
            {"id": 4, "change_id": 10, "sha256": "bad"},
            {"id": 5, "change_id": 11, "sha256": "b" * 64},
        ],
        "has_more": True,
        "next_since_change_id": 11,
    }
    worker = _FileSyncWorker(api, MagicMock(), MagicMock())
    worker._apply_remote_file = lambda _srv, cid, *_: cid == 5
    completed = []
    worker.pull_done.connect(lambda _items, cursor: completed.append(cursor))
    worker.do_pull(0)
    assert api.files_list.call_count == 1
    assert worker._pull_skip[10] == 1
    assert completed == [9]


def test_file_change_cursor_starts_at_zero_instead_of_old_file_id_cursor():
    service = FileCloudSyncService.__new__(FileCloudSyncService)
    service._meta = MagicMock()
    service._meta.get_meta.side_effect = (
        lambda key, default: "500" if key == "files_last_sync_id" else None
    )
    assert service._load_cursor() == 0
    service._meta.get_meta.assert_called_once_with("files_last_change_id", None)


def test_distinct_images_with_same_thumbnail_both_get_processed(qapp, monkeypatch):
    from core.clipboard_monitor import ClipboardMonitor
    import core.clipboard_monitor as monitor_module

    image_a = QImage(128, 128, QImage.Format.Format_RGBA8888)
    image_a.fill(QColor("black"))
    image_b = image_a.copy()
    image_b.setPixelColor(0, 1, QColor("white"))
    monitor = ClipboardMonitor(MagicMock())
    monitor.clipboard = MagicMock()
    monitor._image_executor.submit = MagicMock()
    monkeypatch.setattr(monitor_module, "_capture_source", lambda *_: ("", ""))
    settings = MagicMock()
    settings.capture_source_title = False
    settings.excluded_source_apps = ()
    try:
        assert monitor._fast_image_hash(image_a) == monitor._fast_image_hash(image_b)
        monitor.clipboard.image.side_effect = [image_a, image_b]
        monitor._handle_image(settings)
        monitor._handle_image(settings)
        assert monitor._image_executor.submit.call_count == 2
    finally:
        monitor.stop()


def test_bad_cloud_item_does_not_log_clipboard_text(qapp, caplog):
    worker = _SyncWorker(MagicMock(), MagicMock())
    with caplog.at_level(logging.ERROR, logger="core.cloud_sync_service"):
        assert worker._server_item_to_local({
            "id": 123, "content_type": "future-type",
            "text_content": "SECRET_TOKEN_123", "preview": "SECRET_TOKEN_123",
        }) is None
    assert "id=123" in caplog.text
    assert "SECRET_TOKEN_123" not in caplog.text
