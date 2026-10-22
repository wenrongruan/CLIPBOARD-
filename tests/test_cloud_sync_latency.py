"""云同步调度及双客户端回归；HTTP 使用内存云端，不访问真实账号。"""

import json
import threading
import time
from unittest.mock import MagicMock

import httpx
import pytest
from PySide6.QtCore import QCoreApplication

from core.cloud_api import CloudAPIClient
from core.cloud_sync_service import CloudSyncService, CloudSyncState, _SyncWorker
from core.database import DatabaseManager
from core.models import ImageClipboardItem, TextClipboardItem
from core.repository import ClipboardRepository


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "Qt 同步回调未在期限内完成"


def item(number, device="sender"):
    return TextClipboardItem(
        text_content=f"message-{number}", content_hash=f"hash-{number}",
        preview=f"message-{number}", device_id=device, device_name=device,
        created_at=number,
    )


@pytest.fixture
def service():
    repo = MagicMock()
    repo.get_meta.return_value = None
    repo.get_unsynced_items.return_value = []
    svc = CloudSyncService(repo, MagicMock())
    svc._transition(CloudSyncState.RUNNING)
    svc._trigger_push = MagicMock()
    svc._trigger_pull = MagicMock()
    yield svc
    svc.stop()


def test_copy_triggers_upload_without_periodic_tick_and_batches_burst(service):
    for n in range(4):
        service.enqueue_upload(item(n))
    wait_until(lambda: service._trigger_push.emit.called)
    service._trigger_push.emit.assert_called_once()
    assert [it.content_hash for it in service._trigger_push.emit.call_args.args[1]] == [
        f"hash-{n}" for n in range(4)
    ]


def test_inflight_upload_keeps_new_items_and_does_not_rescan_database(service):
    service._pushing_spaces.add(None)
    service._push_to_cloud()
    service.repository.get_unsynced_items.assert_not_called()
    service.enqueue_upload(item(1))
    service._push_to_cloud()
    assert len(service._pending_upload_queue) == 1
    assert not service._retry_queue
    service._on_push_done(None, 1)
    wait_until(lambda: service._trigger_push.emit.called)


def test_new_copies_are_not_stuck_behind_retry_backlog(service):
    service._retry_queue.extend(item(n) for n in range(40))
    service.enqueue_upload(item(99))
    service._push_to_cloud()
    batch = service._trigger_push.emit.call_args.args[1]
    assert batch[0].content_hash == "hash-99"
    assert len(batch) == service._UPLOAD_BATCH_SIZE


def test_manual_sync_preserves_inflight_guards(service):
    service._pulling_spaces.add(None)
    service._pushing_spaces.add(None)
    service.enqueue_upload(item(1))
    service.force_sync()
    service._trigger_push.emit.assert_not_called()
    service._trigger_pull.emit.assert_not_called()
    assert len(service._pending_upload_queue) == 1


def test_stop_cancels_pending_upload(service):
    service.enqueue_upload(item(1))
    assert service._upload_timer.isActive()
    service.stop()
    assert not service._upload_timer.isActive()
    service._push_to_cloud()
    service._on_pull_backlog(None, 1)
    service._trigger_push.emit.assert_not_called()
    service._trigger_pull.emit.assert_not_called()


def test_next_page_requires_matching_cursor_and_running_state(service):
    service._space_cursors["team"] = 100
    service._on_pull_backlog("team", 99)
    service._trigger_pull.emit.assert_not_called()
    service._on_pull_backlog("team", 100)
    service._on_pull_backlog("team", 100)
    service._trigger_pull.emit.assert_called_once_with("team", 100)


def test_failed_image_is_deferred_without_blocking_next_page(tmp_path):
    db = DatabaseManager(str(tmp_path / "failed-image.db"))
    try:
        api = MagicMock()
        api.download_image.return_value = None
        api.sync.return_value = {
            "items": [{"id": 1, "content_type": "image", "content_hash": "image"}],
            "has_more": True,
        }
        worker = _SyncWorker(api, ClipboardRepository(db))
        backlog = []
        worker.pull_backlog.connect(lambda *args: backlog.append(args))
        worker.do_pull(None, 0)
        assert backlog == [(None, 1)]
        assert not worker._skip_counter
        assert (None, 1) in worker._image_retries
    finally:
        db.close()


def test_existing_image_merges_metadata_without_downloading_again(tmp_path):
    db = DatabaseManager(str(tmp_path / "cached-image.db"))
    try:
        repo = ClipboardRepository(db)
        local_id = repo.add_item(ImageClipboardItem(
            content_hash="cached", image_data=b"saved-image", created_at=1,
        ))
        api = MagicMock()
        api.sync.return_value = {"items": [{
            "id": 77, "content_type": "image", "content_hash": "cached",
            "is_starred": True, "created_at": 1,
        }]}
        worker = _SyncWorker(api, repo)
        worker.do_pull(None, 0)
        api.download_image.assert_not_called()
        saved = repo.get_item_by_id(local_id)
        assert saved.image_data == b"saved-image"
        assert saved.cloud_id == 77 and saved.is_starred
    finally:
        db.close()


def test_pending_image_upload_does_not_exhaust_download_retries(tmp_path):
    db = DatabaseManager(str(tmp_path / "pending-image.db"))
    try:
        api = MagicMock()
        api.sync.return_value = {"items": [{
            "id": 1, "content_type": "image", "content_hash": "pending", "has_image": False,
        }], "has_more": True}
        worker = _SyncWorker(api, ClipboardRepository(db))
        backlog = []
        worker.pull_backlog.connect(lambda *args: backlog.append(args))
        for _ in range(worker._MAX_IMAGE_RETRY + 1):
            worker.do_pull(None, 0)
        api.download_image.assert_not_called()
        assert not worker._skip_counter and (None, 1) in worker._image_retries
        assert backlog and all(cursor == 1 for _, cursor in backlog)
        worker._image_retries[(None, 1)]["next_attempt_at"] = time.time() - 1
        api.download_image.return_value = None
        worker.do_retry_images()
        api.download_image.assert_called_once_with(1)
        assert not worker._skip_counter
        assert worker._image_retries[(None, 1)]["attempts"] == 1
    finally:
        db.close()


def test_personal_image_cache_does_not_suppress_team_image_download(tmp_path):
    db = DatabaseManager(str(tmp_path / "image-spaces.db"))
    try:
        repo = ClipboardRepository(db)
        personal_id = repo.add_item(ImageClipboardItem(
            content_hash="same-image", image_data=b"personal-image", created_at=1,
        ))
        api = MagicMock()
        api.sync.return_value = {"items": [{
            "id": 77, "content_type": "image", "content_hash": "same-image",
            "space_id": "team", "created_at": 1,
        }]}
        worker = _SyncWorker(api, repo)

        def download(remote_item, _server_id, **_kwargs):
            remote_item.image_data = b"team-image"
            return True

        worker._download_image = MagicMock(side_effect=download)
        worker.do_pull("team", 0)
        worker._download_image.assert_called_once()
        assert repo.get_item_by_id(personal_id).cloud_id is None
        assert repo.get_by_cloud_id(77).space_id == "team"
        assert repo.get_by_cloud_id(77).image_data == b"team-image"
    finally:
        db.close()


def test_retry_binds_later_local_placeholder_and_respects_its_deletion(tmp_path):
    db = DatabaseManager(str(tmp_path / "late-placeholder.db"))
    try:
        repo = ClipboardRepository(db)
        api = MagicMock()
        api.sync.return_value = {"items": [{
            "id": 77, "content_type": "image", "content_hash": "late-local",
            "has_image": False, "created_at": 1,
        }]}
        worker = _SyncWorker(api, repo)
        worker.do_pull(None, 0)
        local_id = repo.add_item(ImageClipboardItem(content_hash="late-local", created_at=1))
        worker.do_pull(None, 0)
        entry = worker._image_retries[(None, 77)]
        assert entry["local_id"] == local_id
        repo.delete_item(local_id)
        entry["next_attempt_at"] = time.time() - 1
        worker.do_retry_images()
        api.download_image.assert_not_called()
        assert not worker._image_retries
        assert not repo.get_existing_hashes(["late-local"], space_id=None, space_scoped=True)
    finally:
        db.close()


@pytest.mark.parametrize("direct_url", [True, False])
def test_image_url_reuse_and_legacy_fallback(direct_url):
    client = CloudAPIClient("https://sync.example.com")
    url = "https://sharedclipboard.oss-cn-shanghai.aliyuncs.com/test.png?Signature=test"
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path.endswith("/image-url"):
            return httpx.Response(200, json={"url": url})
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"image-bytes")

    client.set_tokens("test-token", "")
    client._client.close()
    client._client = httpx.Client(base_url=client.base_url, transport=httpx.MockTransport(handle))
    try:
        result = client.download_image(1, image_url=url if direct_url else None)
        assert result == b"image-bytes"
        assert len(requests) == (1 if direct_url else 2)
        assert "Authorization" not in requests[-1].headers
    finally:
        client.close()


def test_sync_image_url_keeps_storage_domain_validation():
    client = CloudAPIClient("https://sync.example.com")
    try:
        client._client.stream = MagicMock()
        assert client.download_image(1, image_url="https://untrusted.example/image.png") is None
        client._client.stream.assert_not_called()
    finally:
        client.close()


class MemoryCloud:
    def __init__(self):
        self.rows = []
        self.calls = []
        self.uploaded_at = None
        self.lock = threading.Lock()

    def handle(self, request):
        with self.lock:
            path = request.url.path
            self.calls.append((path, dict(request.url.params)))
            if path == "/api/v1/clipboard/batch":
                saved = []
                for row in json.loads(request.content)["items"]:
                    row = dict(row, id=len(self.rows) + 1)
                    self.rows.append(row)
                    saved.append(row)
                self.uploaded_at = time.monotonic()
                payload = {"items": saved}
            elif path == "/api/v1/clipboard/sync":
                since = int(request.url.params["since_id"])
                limit = int(request.url.params["limit"])
                rows = [row for row in self.rows if row["id"] > since
                        and row["device_id"] != request.url.params["device_id"]]
                payload = {"items": rows[:limit], "has_more": len(rows) > limit}
            elif path == "/api/v1/spaces":
                payload = {"spaces": []}
            elif path in ("/api/v1/devices", "/api/v1/subscription"):
                payload = {}
            else:
                raise AssertionError(f"Unexpected HTTP path: {path}")
            return httpx.Response(200, json=payload)


def connected_service(tmp_path, cloud, device):
    db = DatabaseManager(str(tmp_path / f"{device}.db"))
    repo = ClipboardRepository(db)
    client = CloudAPIClient("https://sync.example.com")
    client.set_tokens("test-token", "")
    client._client.close()
    client._client = httpx.Client(
        base_url=client.base_url, transport=httpx.MockTransport(cloud.handle),
    )
    svc = CloudSyncService(repo, client)
    svc._worker._device_id = device
    return svc, repo, client, db


def test_two_clients_receive_copy_after_idle_within_poll_cap(tmp_path, record_property):
    cloud = MemoryCloud()
    clients = [connected_service(tmp_path, cloud, device) for device in ("sender", "receiver")]
    try:
        sender, sender_repo, _, _ = clients[0]
        receiver, receiver_repo, _, _ = clients[1]
        for svc, *_ in clients:
            svc.start()
        wait_until(lambda: len([call for call in cloud.calls
                                if call[0].endswith("/sync")]) >= 2
                   and not sender._pulling and not receiver._pulling)
        for _ in range(30):
            receiver._increase_interval()
        assert receiver._pull_timer.interval() <= 3000
        receiver._pull_timer.start(receiver._current_interval)
        sender._push_timer.setInterval(60000)  # 只能通过新内容事件触发上传。
        copied = item(1)
        copied.id = sender_repo.add_item(copied)
        started = time.monotonic()
        sender.enqueue_upload(copied)
        received = []
        receiver.new_items_available.connect(received.extend)
        wait_until(lambda: bool(received), timeout=4.0)
        upload_ms = round((cloud.uploaded_at - started) * 1000)
        receive_ms = round((time.monotonic() - started) * 1000)
        assert upload_ms < 1000
        assert receiver_repo.get_by_cloud_id(1).text_content == copied.text_content
        record_property("upload_ms", upload_ms)
        record_property("receive_ms", receive_ms)
        print(f"memory-cloud: upload={upload_ms}ms receive={receive_ms}ms")
    finally:
        for svc, _, client, db in clients:
            svc.stop()
            client.close()
            db.close()


def test_startup_drains_multiple_pages_without_periodic_ticks(tmp_path):
    cloud = MemoryCloud()
    cloud.rows = [{
        "id": n, "content_type": "text", "text_content": f"remote-{n}",
        "content_hash": f"remote-{n}", "device_id": "other", "created_at": n,
    } for n in range(1, 206)]
    svc, repo, client, db = connected_service(tmp_path, cloud, "receiver")
    try:
        received = []
        svc.new_items_available.connect(received.extend)
        svc.start()
        svc._pull_timer.setInterval(60000)
        wait_until(lambda: len(received) == 205)
        cursors = [int(params["since_id"]) for path, params in cloud.calls
                   if path.endswith("/sync")]
        assert cursors == [0, 100, 200]
        assert svc._space_cursors[None] == 205
        assert repo.get_by_cloud_id(205) is not None
    finally:
        svc.stop()
        client.close()
        db.close()
