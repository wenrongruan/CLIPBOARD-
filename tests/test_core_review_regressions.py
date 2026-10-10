"""Core 审查回归：临时数据库/假云端，不访问真实配置、账户或网络。"""

import hashlib
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from config import AppSettings
from core.database import DatabaseManager
from core.file_models import CloudFile, FileSyncState
from core.file_repository import CloudFileRepository
from core.repository import ClipboardRepository


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def repositories(tmp_path):
    db = DatabaseManager(str(tmp_path / "review.db"))
    yield CloudFileRepository(db), ClipboardRepository(db)
    db.close()


def wait_for(predicate, qapp=None, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if qapp is not None:
            qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "后台任务未在期限内完成"


def test_open_copy_detaches_legacy_hardlink_and_refreshes_same_size_edits(tmp_path, monkeypatch):
    from core.file_storage import materialize_for_open, sandbox_path_for
    monkeypatch.setattr("config.get_files_local_dir", lambda: tmp_path / "files")
    content = b"original"
    original = sandbox_path_for(hashlib.sha256(content).hexdigest())
    original.write_bytes(content)
    old_view = original.parent.parent / "open_view" / original.stem / "report.txt"
    old_view.parent.mkdir(parents=True)
    os.link(original, old_view)

    view = Path(materialize_for_open(str(original), "report.txt"))
    assert not os.path.samefile(original, view)
    view.write_bytes(b"changed!")
    assert original.read_bytes() == content
    assert Path(materialize_for_open(str(original), "report.txt")).read_bytes() == content


@pytest.mark.parametrize("portable", [False, True])
def test_global_migration_removes_two_files_and_unselected_old_names(tmp_path, monkeypatch, portable):
    from core import file_storage
    root = tmp_path / "files"
    monkeypatch.setattr("config.get_files_local_dir", lambda: root)
    if portable:
        monkeypatch.setattr(file_storage, "_cleanup_legacy_open_views_posix", file_storage._cleanup_legacy_open_views_portable)
    originals = []
    views = []
    for i, content in enumerate([b"first original", b"second original"]):
        source = file_storage.sandbox_path_for(hashlib.sha256(content).hexdigest())
        source.write_bytes(content)
        directory = root / "open_view" / source.stem
        directory.mkdir(parents=True)
        for name in (f"old-name-{i}.txt", f"renamed-{i}.txt"):
            view = directory / name
            os.link(source, view)
            views.append(view)
        originals.append((source, content))
    edited_view = views[0].parent / "edited-independent.txt"
    edited_view.write_bytes(b"user edited this independent view")

    assert file_storage.cleanup_legacy_open_views() == 4
    assert all(not view.exists() for view in views)
    for source, content in originals:
        assert source.read_bytes() == content
        assert source.stat().st_nlink == 1
    assert edited_view.read_bytes() == b"user edited this independent view"
    assert file_storage.cleanup_legacy_open_views() == 0


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.skipif(os.name != "posix", reason="验证 POSIX 已打开 FD 的 unlink/replace 语义")
def test_legacy_editor_open_fd_cannot_modify_detached_original_after_migration(tmp_path, monkeypatch, portable):
    from core import file_storage
    root = tmp_path / "files"
    monkeypatch.setattr("config.get_files_local_dir", lambda: root)
    if portable:
        monkeypatch.setattr(file_storage, "_cleanup_legacy_open_views_posix", file_storage._cleanup_legacy_open_views_portable)
    content = b"original"
    source = file_storage.sandbox_path_for(hashlib.sha256(content).hexdigest())
    source.write_bytes(content)
    view = root / "open_view" / source.stem / "old-open-document.txt"
    view.parent.mkdir(parents=True)
    os.link(source, view)
    with view.open("r+b") as editor:
        inode_before = os.fstat(editor.fileno()).st_ino
        assert file_storage.cleanup_legacy_open_views() == 1
        assert not view.exists()
        assert source.stat().st_ino != inode_before
        editor.seek(0)
        editor.write(b"changed!")
        editor.flush()
    assert source.read_bytes() == content


def test_legacy_cleanup_does_not_follow_view_or_original_directory_symlinks(tmp_path, monkeypatch):
    from core import file_storage
    root = tmp_path / "files"
    monkeypatch.setattr("config.get_files_local_dir", lambda: root)
    content = b"stay inside the container"
    source = file_storage.sandbox_path_for(hashlib.sha256(content).hexdigest())
    source.write_bytes(content)
    outside = tmp_path / "outside"
    outside.mkdir()
    external_link = outside / "external.txt"
    os.link(source, external_link)
    views = root / "open_view"
    views.mkdir()
    (views / "linked-directory").symlink_to(outside, target_is_directory=True)
    (views / "linked-file").symlink_to(external_link)
    prefix = next(value for value in ("00", "ff", "aa") if value != source.parent.name)
    external_original = outside / f"{prefix}{'0' * 62}.bin"
    external_original.write_bytes(b"external canonical-shaped name")
    (root / prefix).symlink_to(outside, target_is_directory=True)

    assert file_storage.cleanup_legacy_open_views() == 0
    assert external_link.read_bytes() == content
    assert external_original.read_bytes() == b"external canonical-shaped name"
    assert (views / "linked-file").is_symlink()
    assert source.stat().st_ino != external_link.stat().st_ino


def test_previously_corrupted_legacy_original_is_quarantined_not_reused(tmp_path, monkeypatch):
    from core import file_storage
    root = tmp_path / "files"
    monkeypatch.setattr("config.get_files_local_dir", lambda: root)
    source = file_storage.sandbox_path_for(hashlib.sha256(b"original").hexdigest())
    source.write_bytes(b"original")
    view = root / "open_view" / source.stem / "already-edited.txt"
    view.parent.mkdir(parents=True)
    os.link(source, view)
    view.write_bytes(b"changed!")
    assert file_storage.cleanup_legacy_open_views() == 1
    assert not source.exists()
    quarantined = list(source.parent.glob(".legacy-corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"changed!"
    assert not list(source.parent.glob(".detach-*.tmp"))


@pytest.mark.parametrize("cancel_at", ["start", "after_chunk", "before_replace"])
def test_cancelled_import_removes_temp_and_keeps_existing_content(tmp_path, monkeypatch, cancel_at):
    from core import file_storage
    monkeypatch.setattr("config.get_files_local_dir", lambda: tmp_path / "files")
    monkeypatch.setattr(file_storage, "_CHUNK", 4)
    src = tmp_path / "中文 source.txt"
    content = b"abcdefgh"
    src.write_bytes(content)
    expected = file_storage.sandbox_path_for(hashlib.sha256(content).hexdigest())
    expected.write_bytes(b"existing cached file")
    cancelled = cancel_at == "start"
    calls = 0

    def is_cancelled():
        nonlocal calls
        calls += 1
        # 1 entry + 2 checks per chunk + EOF read check + final replace check.
        return cancelled or (cancel_at == "before_replace" and calls == 7)

    def progress(_done, _total):
        nonlocal cancelled
        cancelled = cancel_at == "after_chunk"

    with pytest.raises(file_storage.FileCopyCancelledError):
        file_storage.hash_and_copy_into_container(str(src), progress, is_cancelled=is_cancelled)
    assert expected.read_bytes() == b"existing cached file"
    assert not list((tmp_path / "files").glob(".import-*.tmp"))


def test_account_switch_resets_change_cursor_with_index_and_parts(repositories):
    files, meta = repositories
    files.bind_account("account-a@example.com")
    fid = files.add_file(CloudFile(name="a", content_sha256="a" * 64, device_id="d"))
    files.record_part(fid, 1, "old-etag")
    meta.set_meta("files_last_change_id", "500")
    assert not files.bind_account("ACCOUNT-A@example.com")
    assert meta.get_meta("files_last_change_id") == "500"
    assert files.bind_account("account-b@example.com")
    assert files.list_files() == []
    assert files.get_parts(fid) == {}
    assert meta.get_meta("files_last_change_id", None) is None


def test_fresh_multipart_session_reuploads_old_parts_and_rebinds_cloud_id(repositories, tmp_path):
    from core.file_sync_service import _FileSyncWorker
    files, _ = repositories
    src = tmp_path / "parts.bin"
    src.write_bytes(b"12345678")
    fid = files.add_file(CloudFile(
        cloud_id=10, name="parts.bin", local_path=str(src), size_bytes=8,
        content_sha256=hashlib.sha256(src.read_bytes()).hexdigest(), device_id="d",
    ))
    files.record_part(fid, 1, "old-session-part")
    files.record_part(fid, 99, "old-unexpected-part")
    api = MagicMock()
    api.files_request_upload.return_value = {
        "cloud_id": 20, "upload_id": "new-session", "upload_mode": "multipart",
        "part_size": 4, "parts": [
            {"part_number": 1, "url": "https://fake/part-1"},
            {"part_number": 2, "url": "https://fake/part-2"},
        ],
    }
    api.upload_file_to_url.side_effect = ["new-etag-1", "new-etag-2"]
    entitlement = MagicMock()
    entitlement.can_upload.return_value = (True, "")
    worker = _FileSyncWorker(api, files, entitlement)
    worker.do_upload(fid)
    assert api.upload_file_to_url.call_count == 2
    api.files_complete_upload.assert_called_once_with(20, [
        {"part_number": 1, "etag": "new-etag-1"},
        {"part_number": 2, "etag": "new-etag-2"},
    ])
    assert files.get_by_id(fid).cloud_id == 20
    assert files.get_by_id(fid).sync_state == FileSyncState.SYNCED.value
    assert files.get_parts(fid) == {}


def test_old_update_then_tombstone_cannot_rebind_or_delete_new_upload(repositories, tmp_path):
    from core.file_sync_service import _FileSyncWorker
    files, _ = repositories
    src = tmp_path / "new.bin"
    src.write_bytes(b"current")
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    fid = files.add_file(CloudFile(
        cloud_id=20, name="new.bin", content_sha256=sha, local_path=str(src),
        size_bytes=7, device_id="d", sync_state=FileSyncState.SYNCED.value,
    ))
    worker = _FileSyncWorker(MagicMock(), files, MagicMock())
    parsed, cursor = worker._process_page([
        {"id": 10, "change_id": 1, "sha256": sha, "name": "old.bin"},
        {"id": 10, "change_id": 2, "sha256": sha, "is_deleted": True},
    ], 0)
    assert cursor == 2 and parsed == []
    assert files.get_by_id(fid).cloud_id == 20
    assert not files.get_by_id(fid).is_deleted
    assert src.read_bytes() == b"current"


def test_file_service_stop_start_restores_work_and_busy_flags(qapp, repositories):
    from core.file_sync_service import FileCloudSyncService
    files, meta = repositories
    api = MagicMock()
    api.files_list_page.return_value = {"items": [], "total": 0}
    entitlement = MagicMock()
    entitlement.can_use_files.return_value = (False, "test")
    service = FileCloudSyncService(files, api, entitlement, meta)
    finished = []
    service.inventory_finished.connect(lambda *_: finished.append(True))
    try:
        service.start()
        assert service.refresh_inventory()
        wait_for(lambda: len(finished) == 1, qapp)
        assert service.stop()
        assert not service._worker_thread.isRunning()
        service._pulling = service._uploading = service._downloading = True
        service._deleting = service._inventory_refreshing = True
        service.start()
        assert service._worker_thread.isRunning()
        assert not any([service._pulling, service._uploading, service._downloading,
                        service._deleting, service._inventory_refreshing])
        assert service.refresh_inventory()
        wait_for(lambda: len(finished) == 2, qapp)
    finally:
        service.stop()


def test_stop_drains_constructed_worker_without_start(qapp, repositories):
    from core.file_sync_service import FileCloudSyncService
    files, meta = repositories
    service = FileCloudSyncService(files, MagicMock(), MagicMock(), meta)
    assert service.stop()
    assert not service._worker_thread.isRunning()


def test_clipboard_cloud_service_stop_start_restores_worker(qapp, repositories):
    from core.cloud_sync_service import CloudSyncService
    _, meta = repositories
    service = CloudSyncService(meta, MagicMock())
    try:
        assert service.stop()
        assert not service._worker_thread.isRunning()
        service._pulling_spaces.add("old-space")
        service._pushing_spaces.add("old-space")
        service.start(interval_ms=60000)
        assert service._worker_thread.isRunning()
        assert not service._pulling_spaces and not service._pushing_spaces
        assert service.stop()
    finally:
        service.stop()


def test_nonblocking_stop_keeps_active_worker_until_task_finishes(qapp, repositories):
    from core.file_sync_service import FileCloudSyncService
    files, meta = repositories
    entered, release = threading.Event(), threading.Event()
    api = MagicMock()

    def inventory(*_):
        entered.set()
        assert release.wait(3)
        return {"items": [], "total": 0}

    api.files_list_page.side_effect = inventory
    service = FileCloudSyncService(files, api, MagicMock(), meta)
    try:
        service.start()
        service.refresh_inventory()
        assert entered.wait(2)
        assert not service.stop(timeout_ms=0)
        assert service._worker_thread.isRunning()
    finally:
        release.set()
        assert service.stop()
    assert not service._worker_thread.isRunning()


@pytest.fixture
def monitor(qapp, monkeypatch):
    from core import clipboard_monitor as module
    repo = MagicMock()
    repo.get_existing_hashes.return_value = {}
    repo.add_item.return_value = 1
    monitor = module.ClipboardMonitor(repo)
    monitor.clipboard = MagicMock()
    monkeypatch.setattr(module, "_capture_source", lambda *_: ("", ""))
    monkeypatch.setattr(module, "settings", lambda: AppSettings(device_id="test"))
    monkeypatch.setattr(monitor, "_threadsafe_emit_item_added", lambda *_: None)
    monkeypatch.setattr(monitor, "_threadsafe_emit_error_occurred", lambda *_: None)
    yield monitor, repo
    monitor.stop()
    monitor._image_executor.shutdown(wait=True)


@pytest.mark.parametrize("failure", ["lookup", "add", "touch"])
def test_text_db_failure_retries_unchanged_clipboard(monitor, failure):
    monitor, repo = monitor
    monitor.clipboard.text.return_value = "retry this text"
    if failure == "lookup":
        repo.get_existing_hashes.side_effect = [RuntimeError("busy"), {}]
        with pytest.raises(RuntimeError):
            monitor._handle_text(AppSettings())
    elif failure == "add":
        repo.add_item.side_effect = [RuntimeError("busy"), 1]
        monitor._handle_text(AppSettings())
    else:
        from core.models import TextClipboardItem
        from utils.hash_utils import compute_content_hash
        item = TextClipboardItem(text_content="retry this text", id=1)
        repo.get_existing_hashes.return_value = {compute_content_hash(item.text_content): item}
        repo.touch_item.side_effect = [RuntimeError("busy"), True]
        monitor._handle_text(AppSettings())
    assert monitor._last_text is None
    monitor._handle_text(AppSettings())
    assert monitor._last_text == "retry this text"
    assert repo.get_existing_hashes.call_count == 2


def test_image_db_failure_retries_same_pixels(monitor):
    monitor, repo = monitor
    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    image.fill(0xff112233)
    monitor.clipboard.image.return_value = image
    repo.get_existing_hashes.side_effect = [RuntimeError("busy"), {}]
    monitor._handle_image(AppSettings())
    wait_for(lambda: not monitor._pending_image_hashes)
    assert monitor._last_image_full_hash is None
    monitor._handle_image(AppSettings())
    wait_for(lambda: monitor._last_image_full_hash is not None)
    assert repo.add_item.call_count == 1
    assert repo.get_existing_hashes.call_count == 2


def test_monitor_start_recreates_executor_after_stop(monitor):
    monitor, _ = monitor
    monitor.start()
    previous = monitor._image_executor
    monitor.stop()
    monitor.start()
    assert monitor._image_executor is not previous
    assert monitor._image_executor.submit(lambda: "alive").result(timeout=2) == "alive"


def test_short_lived_mysql_threads_close_connections_and_retire_pool():
    from core.mysql_database import MySQLDatabaseManager
    manager = MySQLDatabaseManager.__new__(MySQLDatabaseManager)
    manager._tls = threading.local()
    manager._conns_lock = threading.Lock()
    manager._all_conns = []
    connections = []

    def create():
        connection = MagicMock()
        connections.append(connection)
        return connection

    manager._create_connection = create
    barrier, release = threading.Barrier(5), threading.Event()

    def task():
        first = manager._get_thread_conn()
        assert manager._get_thread_conn() is first
        barrier.wait(timeout=2)
        assert release.wait(2)

    threads = [threading.Thread(target=task) for _ in range(4)]
    for thread in threads:
        thread.start()
    try:
        barrier.wait(timeout=2)
        assert len(manager._all_conns) == 4
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=2)
    assert len(connections) == 4 and manager._all_conns == []
    for connection in connections:
        connection.close.assert_called_once()
    manager.close()


@pytest.mark.parametrize("old_error", [False, True])
def test_old_entitlement_refresh_cannot_overwrite_new_account(repositories, old_error):
    from core.entitlement_service import EntitlementService, Plan
    _, meta = repositories
    entered, release = threading.Event(), threading.Event()

    class OldAPI:
        is_authenticated = True

        def get_subscription(self):
            entered.set()
            assert release.wait(3)
            if old_error:
                raise RuntimeError("old account offline")
            return {"plan": "basic", "status": "active"}

    new_api = MagicMock()
    new_api.get_subscription.return_value = {"plan": "super", "status": "active"}
    service = EntitlementService(OldAPI(), meta)
    service.refresh_async()
    old_thread = service._refresh_thread
    try:
        assert entered.wait(2)
        service.invalidate()
        service.set_cloud_api(new_api)
        service.refresh_async()
        wait_for(lambda: service.current().plan == Plan.SUPER)
        service._refresh_thread.join(timeout=2)
        assert old_thread in service.active_refresh_threads()
        assert not service.wait_for_refresh(timeout=0)
    finally:
        release.set()
        old_thread.join(timeout=2)
    assert service.wait_for_refresh(timeout=1)
    assert service.current().plan == Plan.SUPER
    assert service.refresh_state() == (False, False)
    assert '"plan": "super"' in meta.get_meta("entitlement_cache")


def test_shutdown_observes_both_old_and_new_entitlement_requests(repositories):
    from core.entitlement_service import EntitlementService, Plan
    _, meta = repositories
    entered_a, entered_b = threading.Event(), threading.Event()
    release_a, release_b = threading.Event(), threading.Event()

    def api(plan, entered, release):
        client = MagicMock()

        def request():
            entered.set()
            assert release.wait(3)
            return {"plan": plan, "status": "active"}

        client.get_subscription.side_effect = request
        return client

    service = EntitlementService(api("basic", entered_a, release_a), meta)
    service.refresh_async()
    try:
        assert entered_a.wait(2)
        service.set_cloud_api(api("super", entered_b, release_b))
        service.refresh_async()
        assert entered_b.wait(2)
        assert len(service.active_refresh_threads()) == 2
        assert not service.wait_for_refresh(timeout=0)
        release_a.set()
        wait_for(lambda: len(service.active_refresh_threads()) == 1)
        assert service.current().plan == Plan.FREE
    finally:
        release_a.set()
        release_b.set()
        assert service.wait_for_refresh(timeout=3)
    assert service.current().plan == Plan.SUPER


def test_entitlement_bad_payload_exits_refreshing_state(repositories):
    from core.entitlement_service import EntitlementService
    _, meta = repositories
    api = MagicMock()
    api.get_subscription.return_value = {"plan": "basic", "files": {"quota_bytes": "invalid"}}
    service = EntitlementService(api, meta)
    service.refresh_async()
    assert service.wait_for_refresh(timeout=2)
    assert service.refresh_state() == (False, True)


def test_entitlement_failed_thread_start_is_not_left_in_shutdown_set(repositories, monkeypatch):
    from core.entitlement_service import EntitlementService
    _, meta = repositories
    service = EntitlementService(MagicMock(), meta)

    def denied(_thread):
        raise RuntimeError("cannot start thread")

    monkeypatch.setattr(threading.Thread, "start", denied)
    service.refresh_async()
    assert service.active_refresh_threads() == ()
    assert service.wait_for_refresh(timeout=0)
    assert service.refresh_state() == (False, True)


@pytest.mark.parametrize("result_type", ["finished", "error"])
def test_plugin_result_keeps_retiring_worker_until_native_thread_exit(qapp, monkeypatch, result_type):
    from core import plugin_manager as module
    from core.plugin_api import PluginResult
    release = threading.Event()

    class RetiringWorker(module.PluginWorker):
        def run(self):
            if result_type == "finished":
                self.finished.emit(PluginResult(success=True, text_content="result"))
            else:
                self.error.emit("example error")
            assert release.wait(3)

    monkeypatch.setattr(module, "PluginWorker", RetiringWorker)
    manager = module.PluginManager()
    manager._plugins["test"] = MagicMock()
    manager._manifests["test"] = {"timeout": 30}
    try:
        assert manager.run_action("test", "action", MagicMock())
        worker = manager._active_worker
        worker.terminate = MagicMock(side_effect=AssertionError("不得 terminate worker"))
        wait_for(lambda: manager._active_worker is None, qapp)
        assert worker.isRunning()
        assert manager.active_workers() == (worker,)
        assert worker in manager._retiring_workers
        assert not manager.run_action("test", "another-action", MagicMock())
        manager.cancel_action()
        assert worker.is_cancelled
        assert worker.isRunning()
    finally:
        release.set()
        assert worker.wait(3000)
        wait_for(lambda: manager.active_workers() == (), qapp)
    worker.terminate.assert_not_called()


def test_stopped_file_callbacks_cannot_write_new_account_cursor_or_emit(qapp, repositories):
    from core.file_sync_service import FileCloudSyncService
    from core.cloud_sync_service import CloudSyncState
    files, meta = repositories
    service = FileCloudSyncService(files, MagicMock(), MagicMock(), meta)
    service.stop()
    service._meta = MagicMock()
    signals = []
    service.upload_finished.connect(lambda *_: signals.append("upload"))
    service.download_finished.connect(lambda *_: signals.append("download"))
    service.delete_finished.connect(lambda *_: signals.append("delete"))
    service.sync_error.connect(lambda *_: signals.append("error"))
    service._on_pull_done([], 900)
    service._on_pull_error("old unauthorized", 401)
    service._on_upload_finished(1, True, "")
    service._on_download_finished(1, True, "")
    service._on_delete_finished(1, True, "")
    assert service._state == CloudSyncState.STOPPED
    service._meta.set_meta.assert_not_called()
    assert signals == []


def test_stopped_clipboard_cloud_callbacks_cannot_write_new_account_metadata(qapp, repositories):
    from core.cloud_sync_service import CloudSyncService, CloudSyncState
    _, meta = repositories
    service = CloudSyncService(meta, MagicMock())
    service.stop()
    service.repository = MagicMock()
    signals = []
    service.spaces_pulled.connect(lambda *_: signals.append("spaces"))
    service.upload_completed.connect(lambda *_: signals.append("upload"))
    service.sync_error.connect(lambda *_: signals.append("error"))
    service._on_spaces_pulled([{"id": "old-private-team"}])
    service._on_pull_done(None, [], 900)
    service._on_pull_error(None, "old unauthorized", 401)
    service._on_push_done(None, 1)
    service._on_push_error(None, "old offline", 0, [])
    assert service._state == CloudSyncState.STOPPED
    service.repository.set_meta.assert_not_called()
    assert signals == []


def test_logout_clears_legacy_plaintext_credential(monkeypatch):
    import config
    from utils import secure_store
    store = {"token": "legacy-secret", "_secure_token": ""}
    monkeypatch.setattr(config, "get_raw_setting", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(config, "set_raw_setting", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(secure_store, "_HAS_KEYRING", False)
    assert secure_store.retrieve_credential("token") == "legacy-secret"
    secure_store.delete_credential("token")
    assert secure_store.retrieve_credential("token") == ""
    assert store["token"] == store["_secure_token"] == ""


@pytest.mark.parametrize("has_fts", [True, False])
@pytest.mark.parametrize("keyword, expected", [
    ("ock", "hello rocket world"), ("共享", "你好共享剪贴板"),
    ("剪", "你好共享剪贴板"), ("XYZ", "abcXYZdef"),
    ("100%", "value 100% literal"), ("_", "value_with_underscore"),
    ("!", "look!literal"), ('"rocket world"', "hello rocket world"),
])
def test_substring_search_and_literal_wildcards_match_with_or_without_fts(repositories, has_fts, keyword, expected):
    from core.models import TextClipboardItem
    _, meta = repositories
    for i, text in enumerate([
        "hello rocket world", "你好共享剪贴板", "abcXYZdef",
        "value 100% literal", "value_with_underscore", "look!literal", "1000 distractor",
    ]):
        meta.add_item(TextClipboardItem(text_content=text, preview=text, content_hash=f"hash-{i}", device_id="d"))
    meta._query._has_fts = has_fts
    items, total = meta.search_by_keyword(keyword)
    assert total == 1
    assert [item.text_content for item in items] == [expected]


def test_search_count_and_zero_based_pagination_include_token_and_middle_matches(repositories):
    from core.models import TextClipboardItem
    _, meta = repositories
    for i, text in enumerate(["rockets", "xxrocket", "another rocket", "rocket"]):
        meta.add_item(TextClipboardItem(text_content=text, preview=text, content_hash=f"h-{i}", device_id="d", created_at=i))
    first, total = meta.search_by_keyword("rocket", page=0, page_size=2)
    second, other_total = meta.search_by_keyword("rocket", page=1, page_size=2)
    assert total == other_total == 4
    assert len(first) == len(second) == 2
    assert {item.id for item in first}.isdisjoint(item.id for item in second)
