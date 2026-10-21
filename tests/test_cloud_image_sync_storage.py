"""Cloud image cache checks and restoration against a real SQLite database."""

import sqlite3

import pytest

from core.database import DatabaseManager
from core.models import ImageClipboardItem, TextClipboardItem
from core.repository import ClipboardRepository


@pytest.fixture
def repository(tmp_path):
    db = DatabaseManager(str(tmp_path / "cloud-images.db"))
    yield ClipboardRepository(db)
    db.close()


def _image(content_hash, *, data=b"complete-image", space_id=None):
    return ImageClipboardItem(
        content_hash=content_hash,
        image_data=data,
        image_thumbnail=b"thumbnail",
        preview="Original preview",
        device_id="source-device",
        device_name="Source Mac",
        created_at=123456789,
        space_id=space_id,
        source_app="com.example.source",
        source_title="Original window",
        is_starred=True,
    )


def _row(repository, item_id):
    return repository.db.execute_read(lambda conn: dict(repository.db.fetch_one(
        conn, "SELECT * FROM clipboard_items WHERE id = ?", (item_id,)
    )))


@pytest.mark.parametrize("personal_scope", [None, ""])
def test_image_presence_is_space_scoped_and_normalizes_personal_space(
    repository, personal_scope
):
    repository.add_item(_image("personal-null", space_id=None))
    repository.add_item(_image("personal-empty", space_id=""))
    repository.add_item(_image("shared", data=None, space_id=None))
    repository.add_item(_image("shared", space_id="team-a"))
    repository.add_item(_image("other-team", space_id="team-b"))
    hashes = ["personal-null", "personal-empty", "shared", "other-team"]

    assert repository.get_image_hashes_with_data(hashes, personal_scope) == {
        "personal-null", "personal-empty"
    }
    assert repository.get_image_hashes_with_data(hashes, "team-a") == {"shared"}
    assert repository.get_image_hashes_with_data(hashes, "team-b") == {"other-team"}


def test_missing_empty_and_text_payloads_do_not_count_as_complete_images(repository):
    repository.add_item(_image("null-image", data=None))
    repository.add_item(_image("empty-image", data=b""))
    repository.add_item(_image("complete-image"))
    text_id = repository.add_item(TextClipboardItem(
        content_hash="text-with-blob", text_content="Keep this text", device_id="dev"
    ))
    repository.db.execute_with_retry(lambda conn: repository.db.execute_write(
        conn, "UPDATE clipboard_items SET image_data = ? WHERE id = ?",
        (b"unexpected-text-blob", text_id),
    ))

    assert repository.get_image_hashes_with_data([
        "null-image", "empty-image", "complete-image", "text-with-blob", "absent"
    ]) == {"complete-image"}
    assert repository.get_image_hashes_with_data([]) == set()


def test_presence_query_batches_parameters_and_never_returns_blobs(repository, monkeypatch):
    hashes = [f"image-{index}" for index in range(1201)]
    items = [_image(content_hash) for content_hash in hashes]
    repository.db.execute_with_retry(lambda conn: repository.db.execute_many(
        conn,
        """INSERT INTO clipboard_items (
            content_type, text_content, image_data, image_thumbnail,
            content_hash, preview, device_id, device_name, created_at,
            is_starred, space_id, source_app, source_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [item.to_db_tuple() for item in items],
    ))
    with repository.db.get_connection() as conn:
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 500)

    original_fetch = repository.db.fetch_all
    parameter_counts = []

    def fetch_hashes(conn, sql, params=()):
        parameter_counts.append(len(params))
        rows = original_fetch(conn, sql, params)
        # Real returned rows must contain only hashes, never image payloads.
        assert all(row.keys() == ["content_hash"] for row in rows)
        return rows

    monkeypatch.setattr(repository.db, "fetch_all", fetch_hashes)

    assert repository.get_image_hashes_with_data(hashes) == set(hashes)
    assert len(parameter_counts) == 3
    assert max(parameter_counts) <= 500


def test_restore_preserves_original_hash_body_space_and_metadata(repository):
    item_id = repository.add_item(_image("hash-of-uncompressed-source", data=None, space_id="team"))
    repository.add_tags_to_item(item_id, ["tag-a", "tag-b"])
    repository.db.execute_with_retry(lambda conn: repository.db.execute_write(
        conn, "UPDATE clipboard_items SET text_content = ? WHERE id = ?",
        ("Existing image notes", item_id),
    ))
    before = _row(repository, item_id)

    assert repository.restore_cloud_image(item_id, b"compressed-cloud-image", b"cloud-thumb", 42)

    after = _row(repository, item_id)
    expected = dict(before, image_data=b"compressed-cloud-image", image_thumbnail=b"cloud-thumb", cloud_id=42)
    assert after == expected
    assert set(repository.get_tags_for_item(item_id)) == {"tag-a", "tag-b"}
    assert repository.get_image_hashes_with_data([before["content_hash"]], "team") == {before["content_hash"]}


@pytest.mark.parametrize("empty_payload", [None, b""])
def test_restore_rejects_empty_payload_without_marking_synced(repository, empty_payload):
    item_id = repository.add_item(_image("original-image"))
    before = _row(repository, item_id)

    assert repository.restore_cloud_image(item_id, empty_payload, None, 42) is False
    assert _row(repository, item_id) == before


def test_restore_does_not_revive_deleted_images(repository):
    item_id = repository.add_item(_image("deleted-image", data=None))
    assert repository.delete_item(item_id)

    assert repository.restore_cloud_image(item_id, b"late-download", None, 42) is False
    assert repository.get_item_by_id(item_id) is None
    assert repository.get_image_hashes_with_data(["deleted-image"]) == set()


def test_restore_does_not_overwrite_a_text_row(repository):
    item_id = repository.add_item(TextClipboardItem(
        content_hash="text-hash", text_content="Original text", device_id="dev"
    ))
    before = _row(repository, item_id)

    assert repository.restore_cloud_image(item_id, b"late-download", b"thumb", 42) is False
    assert _row(repository, item_id) == before


def test_restore_accepts_absent_thumbnail_and_is_idempotent(repository):
    item_id = repository.add_item(_image("cloud-image", data=None))

    assert repository.restore_cloud_image(item_id, b"download", None, 42) is True
    assert repository.restore_cloud_image(item_id, b"download", None, 42) is True
    assert _row(repository, item_id)["image_thumbnail"] is None


def test_strict_meta_reads_and_writes_with_legacy_compatibility(repository):
    assert repository.get_meta_strict("pending-images") is None
    assert repository.get_meta_strict("pending-images", "[]") == "[]"

    repository.set_meta_strict("pending-images", '[{"server_id": 42}]')
    assert repository.get_meta_strict("pending-images") == '[{"server_id": 42}]'
    assert repository.get_meta("pending-images") == '[{"server_id": 42}]'

    repository.set_meta("pending-images", "[]")
    assert repository.get_meta_strict("pending-images") == "[]"


def test_strict_meta_read_propagates_database_failure(repository, monkeypatch):
    repository.set_meta_strict("pending-images", '[{"server_id": 42}]')
    failure = sqlite3.OperationalError("injected database read failure")

    def fail_read(operation):
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(repository.db, "execute_read", fail_read)
        with pytest.raises(sqlite3.OperationalError) as raised:
            repository.get_meta_strict("pending-images", "[]")
        assert raised.value is failure
        # Preserve the existing API's tolerated-error behavior for other callers.
        assert repository.get_meta("pending-images", "[]") == "[]"

    assert repository.get_meta_strict("pending-images") == '[{"server_id": 42}]'


def test_strict_meta_write_propagates_database_failure(repository, monkeypatch):
    repository.set_meta_strict("pending-images", '[{"server_id": 42}]')
    failure = sqlite3.OperationalError("injected database commit failure")

    def fail_write(operation, max_retries=5):
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(repository.db, "execute_with_retry", fail_write)
        with pytest.raises(sqlite3.OperationalError) as raised:
            repository.set_meta_strict("pending-images", "[]")
        assert raised.value is failure
        assert repository.set_meta("pending-images", "[]") is None

    # Neither failed call may claim the old queue has been replaced on disk.
    assert repository.get_meta_strict("pending-images") == '[{"server_id": 42}]'
