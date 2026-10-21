"""图片失败不能丢数据或挡住文字分页；使用真实 SQLite、假时间和内存 API。"""

import io
import json
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication

import core.cloud_sync_service as sync_module
from core.cloud_sync_service import CloudSyncService, CloudSyncState, _SyncWorker
from core.database import DatabaseManager
from core.models import ImageClipboardItem
from core.repository import ClipboardRepository


class FakeClock:
    def __init__(self):
        self.now = 1_900_000_000.0

    def advance_to(self, timestamp):
        assert timestamp >= self.now
        self.now = timestamp


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(sync_module.time, "time", lambda: fake.now)
    return fake


@pytest.fixture
def image_bytes():
    output = io.BytesIO()
    with Image.new("RGB", (4, 4), "#3279b8") as image:
        image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def repo(tmp_path):
    database = DatabaseManager(str(tmp_path / "image-recovery.db"))
    try:
        yield ClipboardRepository(database)
    finally:
        database.close()


def remote_image(server_id=77, *, content_hash="remote-image", space_id=None,
                 has_image=True, image_url=None):
    row = {
        "id": server_id,
        "content_type": "image",
        "content_hash": content_hash,
        "preview": "[图片]",
        "created_at": 1,
        "device_id": "other-device",
        "space_id": space_id,
        "has_image": has_image,
    }
    if image_url:
        row["image_url"] = image_url
    return row


def make_worker(repo, rows):
    api = MagicMock()
    api.sync.return_value = {"items": rows, "has_more": False}
    api.download_image.return_value = None
    worker = _SyncWorker(api, repo)
    errors = []
    worker.pull_error.connect(lambda *args: errors.append(args))
    return worker, api, errors


def next_retry(worker, clock, key=(None, 77)):
    clock.advance_to(worker._image_retries[key]["next_attempt_at"])
    worker.do_retry_images()


def assert_image_unavailable(repo, server_id):
    item = repo.get_by_cloud_id(server_id)
    assert item is None or not item.image_data


@pytest.mark.parametrize("has_image", [False, True])
def test_unavailable_first_page_image_does_not_delay_101st_text(repo, clock, has_image):
    rows = [remote_image(1, has_image=has_image)] + [{
        "id": number,
        "content_type": "text",
        "content_hash": f"text-{number}",
        "text_content": f"message {number}",
        "created_at": number,
    } for number in range(2, 102)]
    worker, api, errors = make_worker(repo, rows)

    def page(*, since_id, **_kwargs):
        remaining = [row for row in rows if row["id"] > since_id]
        return {"items": remaining[:100], "has_more": len(remaining) > 100}

    api.sync.side_effect = page
    pulled, backlog = [], []
    worker.pull_done.connect(lambda *args: pulled.append(args))
    worker.pull_backlog.connect(lambda *args: backlog.append(args))

    worker.do_pull(None, 0)
    assert not errors
    assert pulled[-1][2] == 100
    assert backlog == [(None, 100)]
    assert api.download_image.call_count == int(has_image)
    worker.do_pull(*backlog[0])

    assert not errors
    assert pulled[-1][2] == 101
    assert repo.get_by_cloud_id(101).text_content == "message 101"
    assert (None, 1) in worker._image_retries


def test_image_recovers_after_15_second_outage_and_refreshes_signed_url(
    repo, clock, image_bytes,
):
    stale_url = "https://storage.example/test.png?Signature=expired-secret"
    worker, api, errors = make_worker(repo, [remote_image(image_url=stale_url)])
    started = clock.now
    api.download_image.side_effect = lambda *_args, **_kwargs: (
        image_bytes if clock.now >= started + 15 else None
    )
    recovered = []
    worker.images_recovered.connect(lambda *args: recovered.append(args))

    worker.do_pull(None, 0)
    assert not errors
    assert worker._image_retries[(None, 77)]["next_attempt_at"] == started + 5
    next_retry(worker, clock)
    assert_image_unavailable(repo, 77)
    assert worker._image_retries[(None, 77)]["next_attempt_at"] == started + 15
    next_retry(worker, clock)

    saved = repo.get_by_cloud_id(77)
    assert saved.image_data == image_bytes and saved.image_thumbnail
    assert not worker._image_retries
    assert len(recovered) == 1
    assert recovered[0][0] is None and recovered[0][1][0].id == saved.id
    assert api.download_image.call_args_list[0].kwargs == {"image_url": stale_url}
    assert all("image_url" not in call.kwargs for call in api.download_image.call_args_list[1:])
    assert not json.loads(repo.get_meta(worker._META_IMAGE_RETRIES_KEY))


def test_more_than_five_failures_remain_recoverable_with_bounded_backoff(
    repo, clock, image_bytes,
):
    worker, api, errors = make_worker(repo, [remote_image()])
    worker.do_pull(None, 0)
    assert not errors
    delays = []
    for _ in range(7):
        next_retry(worker, clock)
        pending = worker._image_retries[(None, 77)]
        delays.append(pending["next_attempt_at"] - clock.now)
    assert pending["attempts"] > 5
    assert delays == sorted(delays)
    assert 0 < delays[-1] <= 300
    assert_image_unavailable(repo, 77)

    api.download_image.return_value = image_bytes
    next_retry(worker, clock)
    assert repo.get_by_cloud_id(77).image_data == image_bytes
    assert not worker._image_retries


def test_pending_retry_survives_database_and_worker_restart_without_signed_url(
    tmp_path, clock, image_bytes,
):
    path = str(tmp_path / "restart.db")
    database = DatabaseManager(path)
    repo = ClipboardRepository(database)
    worker, api, errors = make_worker(repo, [remote_image(
        has_image=False,
        image_url="https://storage.example/pending.png?Signature=secret",
    )])
    try:
        worker.do_pull(None, 0)
        assert not errors
        api.download_image.assert_not_called()
        persisted = repo.get_meta(worker._META_IMAGE_RETRIES_KEY)
        assert "Signature" not in persisted and "image_url" not in persisted
        assert "attempts" in persisted and "next_attempt_at" in persisted
        deadline = worker._image_retries[(None, 77)]["next_attempt_at"]
    finally:
        database.close()

    clock.advance_to(deadline)
    reopened = DatabaseManager(path)
    try:
        new_repo = ClipboardRepository(reopened)
        new_worker, new_api, _ = make_worker(new_repo, [])
        new_api.download_image.return_value = image_bytes
        new_worker.do_retry_images()
        assert new_repo.get_by_cloud_id(77).image_data == image_bytes
        new_api.download_image.assert_called_once_with(77)
        assert not new_worker._image_retries
        assert not json.loads(new_repo.get_meta(worker._META_IMAGE_RETRIES_KEY))
    finally:
        reopened.close()


@pytest.mark.parametrize("previously_acknowledged", [False, True])
def test_complete_local_image_is_not_acknowledged_before_cloud_upload(
    tmp_path, clock, image_bytes, previously_acknowledged,
):
    path = str(tmp_path / "local-upload.db")
    database = DatabaseManager(path)
    repo = ClipboardRepository(database)
    local_id = repo.add_item(ImageClipboardItem(
        content_hash="cached", image_data=image_bytes, created_at=1,
    ))
    if previously_acknowledged:
        repo.set_cloud_id(local_id, 77)
    worker, api, errors = make_worker(repo, [dict(
        remote_image(content_hash="cached", has_image=False), is_starred=True,
    )])
    try:
        worker.do_pull(None, 0)
        assert not errors
        api.download_image.assert_not_called()
        saved = repo.get_item_by_id(local_id)
        assert saved.image_data == image_bytes and saved.is_starred
        assert saved.cloud_id is None
        assert (None, 77) in worker._image_retries
    finally:
        database.close()

    reopened = DatabaseManager(path)
    try:
        restarted_repo = ClipboardRepository(reopened)
        assert [item.id for item in restarted_repo.get_unsynced_items()] == [local_id]
        restarted_worker, restarted_api, _ = make_worker(restarted_repo, [])
        restarted_api.download_image.return_value = None
        clock.advance_to(worker._image_retries[(None, 77)]["next_attempt_at"])
        restarted_worker.do_retry_images()
        assert restarted_repo.get_item_by_id(local_id).cloud_id is None
        assert [item.id for item in restarted_repo.get_unsynced_items()] == [local_id]
        restarted_api.download_image.return_value = image_bytes
        next_retry(restarted_worker, clock)
        assert restarted_repo.get_item_by_id(local_id).cloud_id == 77
        assert not restarted_repo.get_unsynced_items()
        assert restarted_repo.get_items(page_size=10)[1] == 1
    finally:
        reopened.close()


def test_personal_complete_cache_does_not_confirm_or_satisfy_team_image(
    repo, clock, image_bytes,
):
    personal_id = repo.add_item(ImageClipboardItem(
        content_hash="same-content", image_data=image_bytes, created_at=1,
    ))
    worker, api, errors = make_worker(repo, [remote_image(
        content_hash="same-content", space_id="team", has_image=False,
    )])
    worker.do_pull("team", 0)
    assert not errors
    api.download_image.assert_not_called()
    assert ("team", 77) in worker._image_retries
    assert repo.get_item_by_id(personal_id).cloud_id is None

    api.download_image.return_value = image_bytes
    next_retry(worker, clock, ("team", 77))
    team = repo.get_by_cloud_id(77)
    assert team.id != personal_id and team.space_id == "team"
    assert team.image_data == image_bytes
    assert repo.get_item_by_id(personal_id).cloud_id is None


def test_same_hash_retries_are_independent_for_personal_and_team_spaces(
    repo, clock, image_bytes,
):
    personal = remote_image(77, content_hash="shared", has_image=False)
    team = remote_image(88, content_hash="shared", space_id="team", has_image=False)
    worker, api, errors = make_worker(repo, [])
    api.sync.side_effect = lambda *, space_id, **_kwargs: {
        "items": [team if space_id else personal], "has_more": False,
    }
    worker.do_pull(None, 0)
    worker.do_pull("team", 0)
    assert not errors
    assert set(worker._image_retries) == {(None, 77), ("team", 88)}

    api.download_image.return_value = image_bytes
    deadline = max(entry["next_attempt_at"] for entry in worker._image_retries.values())
    clock.advance_to(deadline)
    worker.do_retry_images()
    worker.do_retry_images()
    assert not worker._image_retries
    assert repo.get_by_cloud_id(77).space_id is None
    assert repo.get_by_cloud_id(88).space_id == "team"
    assert repo.get_by_cloud_id(77).id != repo.get_by_cloud_id(88).id


def test_existing_empty_payload_recovers_same_row_and_hash_with_notification(
    repo, clock, image_bytes,
):
    expected_hash = "original-cloud-hash-before-compression"
    local_id = repo.add_item(ImageClipboardItem(
        content_hash=expected_hash, image_data=None, created_at=1,
    ))
    repo.set_cloud_id(local_id, 77)
    worker, api, errors = make_worker(repo, [remote_image(content_hash=expected_hash)])
    notifications = []
    worker.images_recovered.connect(lambda *args: notifications.append(args))
    worker.do_pull(None, 0)
    assert not errors
    api.download_image.assert_called_once_with(77)
    assert repo.get_item_by_id(local_id).image_data is None

    api.download_image.return_value = image_bytes
    next_retry(worker, clock)
    saved = repo.get_item_by_id(local_id)
    assert saved.image_data == image_bytes and saved.image_thumbnail
    assert saved.content_hash == expected_hash and saved.cloud_id == 77
    assert repo.get_items(page_size=10)[1] == 1
    assert len(notifications) == 1
    assert notifications[0][1][0].id == local_id


def test_image_retry_preserves_star_changed_after_queueing(repo, clock, image_bytes):
    local_id = repo.add_item(ImageClipboardItem(
        content_hash="star-changed", image_data=None, created_at=1, is_starred=False,
    ))
    repo.set_cloud_id(local_id, 77)
    worker, api, errors = make_worker(repo, [remote_image(content_hash="star-changed")])
    recovered = []
    worker.images_recovered.connect(lambda *args: recovered.append(args))
    worker.do_pull(None, 0)
    assert not errors and (None, 77) in worker._image_retries

    assert repo.toggle_star(local_id)
    assert repo.get_item_by_id(local_id).is_starred
    api.download_image.return_value = image_bytes
    next_retry(worker, clock)

    saved = repo.get_item_by_id(local_id)
    assert saved.image_data == image_bytes and saved.is_starred
    assert len(recovered) == 1 and recovered[0][1][0].is_starred
    assert not worker._image_retries


def test_deleted_placeholder_is_not_resurrected_by_pending_image_retry(
    repo, clock, image_bytes,
):
    content_hash = "deleted-while-pending"
    local_id = repo.add_item(ImageClipboardItem(
        content_hash=content_hash, image_data=None, created_at=1,
    ))
    repo.set_cloud_id(local_id, 77)
    worker, api, errors = make_worker(repo, [remote_image(content_hash=content_hash)])
    recovered = []
    worker.images_recovered.connect(lambda *args: recovered.append(args))
    worker.do_pull(None, 0)
    assert not errors and (None, 77) in worker._image_retries
    assert worker._image_retries[(None, 77)]["local_id"] == local_id

    assert repo.delete_item(local_id)
    api.download_image.return_value = image_bytes
    next_retry(worker, clock)

    assert repo.get_item_by_id(local_id) is None
    assert not repo.get_existing_hashes([content_hash], space_id=None, space_scoped=True)
    assert repo.get_items(page_size=10)[1] == 0
    assert not recovered and not worker._image_retries
    assert not json.loads(repo.get_meta(worker._META_IMAGE_RETRIES_KEY))
    api.download_image.assert_called_once_with(77)


def test_retry_queue_write_failure_blocks_cursor_until_durably_saved(repo, clock, monkeypatch):
    text = {
        "id": 78, "content_type": "text", "content_hash": "next-text",
        "text_content": "keep pagination available", "created_at": 2,
    }
    worker, api, errors = make_worker(repo, [remote_image(has_image=False), text])
    api.sync.return_value["has_more"] = True
    pulled, backlog = [], []
    worker.pull_done.connect(lambda *args: pulled.append(args))
    worker.pull_backlog.connect(lambda *args: backlog.append(args))
    write = repo.db.execute_write

    def fail_retry_queue_write(conn, sql, params=()):
        if ("INSERT" in sql.upper() and "app_meta" in sql
                and params and params[0] == worker._META_IMAGE_RETRIES_KEY):
            raise RuntimeError("simulated app_meta write failure")
        return write(conn, sql, params)

    monkeypatch.setattr(repo.db, "execute_write", fail_retry_queue_write)
    worker.do_pull(None, 0)
    assert len(errors) == 1
    assert not pulled and not backlog
    assert not json.loads(repo.get_meta(worker._META_IMAGE_RETRIES_KEY, "[]"))

    monkeypatch.setattr(repo.db, "execute_write", write)
    worker.do_pull(None, 0)
    assert len(errors) == 1
    assert pulled[-1][2] == 78 and backlog == [(None, 78)]
    persisted = json.loads(repo.get_meta(worker._META_IMAGE_RETRIES_KEY))
    assert len(persisted) == 1 and persisted[0]["item"]["id"] == 77
    assert repo.get_by_cloud_id(78).text_content == text["text_content"]
    api.download_image.assert_not_called()


def test_retry_queue_read_failure_does_not_replace_persisted_targets_with_empty_queue(
    repo, clock, monkeypatch,
):
    original_worker, _, original_errors = make_worker(repo, [remote_image(has_image=False)])
    original_worker.do_pull(None, 0)
    assert not original_errors
    assert repo.get_meta(original_worker._META_IMAGE_RETRIES_KEY)

    worker, api, errors = make_worker(repo, [])
    pulled, backlog = [], []
    worker.pull_done.connect(lambda *args: pulled.append(args))
    worker.pull_backlog.connect(lambda *args: backlog.append(args))
    read = repo.db.fetch_one

    def fail_retry_queue_read(conn, sql, params=()):
        if "app_meta" in sql and params and params[0] == worker._META_IMAGE_RETRIES_KEY:
            raise RuntimeError("simulated app_meta read failure")
        return read(conn, sql, params)

    monkeypatch.setattr(repo.db, "fetch_one", fail_retry_queue_read)
    worker.do_pull(None, 0)
    assert len(errors) == 1
    assert not pulled and not backlog and not worker._image_retries_loaded
    api.sync.assert_not_called()

    monkeypatch.setattr(repo.db, "fetch_one", read)
    worker.do_pull(None, 0)
    assert len(errors) == 1 and pulled[-1][2] == 0
    assert (None, 77) in worker._image_retries
    persisted = json.loads(repo.get_meta(worker._META_IMAGE_RETRIES_KEY))
    assert len(persisted) == 1 and persisted[0]["item"]["id"] == 77


def test_duplicate_pull_and_retry_do_not_reset_backoff_or_duplicate_rows(
    repo, clock, image_bytes,
):
    worker, api, errors = make_worker(repo, [remote_image(has_image=False)])
    worker.do_pull(None, 0)
    initial = dict(worker._image_retries[(None, 77)])
    for _ in range(4):
        worker.do_pull(None, 0)
        worker.do_retry_images()
    assert not errors
    assert worker._image_retries[(None, 77)]["next_attempt_at"] == initial["next_attempt_at"]
    assert worker._image_retries[(None, 77)]["attempts"] == initial["attempts"]
    api.download_image.assert_not_called()

    next_retry(worker, clock)
    after_failure = dict(worker._image_retries[(None, 77)])
    worker.do_pull(None, 0)
    assert worker._image_retries[(None, 77)]["next_attempt_at"] == after_failure["next_attempt_at"]
    assert worker._image_retries[(None, 77)]["attempts"] == after_failure["attempts"]

    api.download_image.return_value = image_bytes
    next_retry(worker, clock)
    api.sync.return_value = {"items": [remote_image(has_image=True)], "has_more": False}
    for _ in range(3):
        worker.do_pull(None, 0)
        worker.do_retry_images()
    assert not errors
    assert api.download_image.call_count == 2
    assert repo.get_items(page_size=10)[1] == 1
    assert repo.get_by_cloud_id(77).image_data == image_bytes
    assert not worker._image_retries


def test_service_forwards_recovered_images_to_existing_ui_signal(repo, image_bytes):
    api = MagicMock()
    service = CloudSyncService(repo, api)
    service._transition(CloudSyncState.RUNNING)
    item = ImageClipboardItem(id=1, content_hash="recovered", image_data=image_bytes)
    received = []
    service.new_items_available.connect(received.append)
    try:
        service._worker.images_recovered.emit("team", [item])
        QCoreApplication.processEvents()
        assert received == [[item]]
    finally:
        service.stop()
