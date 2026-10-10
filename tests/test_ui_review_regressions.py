"""导入账号隔离、分享契约和视图操作的回归。"""

from __future__ import annotations

import subprocess
import runpy
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QThread, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QPushButton, QStyleFactory, QWidget

from core.file_models import CloudFile
from core.file_storage import FileCopyCancelledError
from core.models import ImageClipboardItem, TextClipboardItem
from core.share_service import ShareService
from ui.clipboard_item import ClipboardItemWidget
from ui.controllers.clipboard_list_controller import ClipboardListController
from ui.file_list_widget import FileListWidget
from ui.share_dialog import ShareLinkDialog
from ui.timeline_view import TimelineView


@pytest.fixture
def qapp(_qt_application):
    return _qt_application


@pytest.fixture
def login_pool(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import ui.cloud_login_widget as module
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(module, "_executor", executor)
    yield
    executor.shutdown(wait=True, cancel_futures=True)


class _Repo:
    def __init__(self):
        self.files = []

    def list_files(self, include_deleted=False):
        return list(self.files)

    def get_by_sha(self, sha, include_deleted=False):
        return next((f for f in self.files if f.content_sha256 == sha), None)

    def add_file(self, file):
        file.id = len(self.files) + 1
        self.files.append(file)
        return file.id


class _Sync(QObject):
    file_added = Signal(object)
    file_updated = Signal(object)
    file_deleted = Signal(int)
    upload_progress = Signal(int, int, int)
    download_progress = Signal(int, int, int)
    upload_finished = Signal(int, bool, str)
    download_finished = Signal(int, bool, str)
    delete_finished = Signal(int, bool, str)
    inventory_finished = Signal(int, bool, str)
    sync_error = Signal(str, int)

    def __init__(self):
        super().__init__()
        self.uploads = []

    def enqueue_upload(self, local_id):
        self.uploads.append(local_id)

    def refresh_inventory(self):
        return True


class _Entitlement(QObject):
    entitlement_changed = Signal(object)

    def current(self):
        from core.entitlement_service import Plan
        return SimpleNamespace(plan=Plan.BASIC, files_quota_bytes=1 << 30,
                               files_used_bytes=0, team_spaces=0)

    def can_use_files(self):
        return True, ""

    def can_upload(self, size):
        return True, ""


@pytest.fixture
def file_widget(qapp, monkeypatch):
    import ui.file_list_widget as module
    config = SimpleNamespace(cloud_user_email="a@example.com", device_id="device",
                             device_name="device")
    monkeypatch.setattr(module, "settings", lambda: config)
    monkeypatch.setattr(module, "make_bookmark", lambda path: None)
    repo, sync, ent = _Repo(), _Sync(), _Entitlement()
    widget = FileListWidget(repo, sync, ent, SimpleNamespace(is_authenticated=True))
    yield widget, config
    assert widget.stop_imports(3000)
    qapp.processEvents()
    widget.close()
    widget.deleteLater()


def _process_until(qapp, condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.001)
    assert condition()


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
@pytest.mark.parametrize("font_pixels", [13, 20, 26])
def test_file_names_remain_readable_in_narrow_window(
    qapp, file_widget, monkeypatch, style_name, font_pixels,
):
    widget, _ = file_widget
    style = QStyleFactory.create(style_name)
    if style is None:
        pytest.skip(f"Qt style {style_name} is unavailable")
    style.setParent(widget)
    widget.table.setStyle(style)
    widget.table.horizontalHeader().setStyle(style)
    # Load the real Windows stylesheet without changing ui.styles for other tests.
    with monkeypatch.context() as patch:
        patch.setattr("platform.system", lambda: "Windows")
        stylesheet = runpy.run_path(str(Path(__file__).parents[1] / "ui" / "styles.py"))
    widget.setStyleSheet(
        stylesheet["MAIN_STYLE"] + f"\nQWidget {{ font-size: {font_pixels}px; }}"
    )
    name = "项目资料-最终确认版本-2026-10-10.pdf"
    file = CloudFile(
        id=1, name=name, size_bytes=11 << 20,
        device_id="12345678-1234-1234-1234-123456789abc",
    )
    widget.repo.files.append(file)
    widget.reload()
    widget.resize(560, 400)
    widget.show()
    qapp.processEvents()

    name_index = widget.model.index(0, widget.model.COL_NAME)
    assert widget.table.columnWidth(widget.model.COL_NAME) >= 240
    assert widget.table.visualRect(name_index).left() == 0
    assert widget.table.horizontalScrollBar().maximum() > 0
    assert widget.model.data(name_index, Qt.ToolTipRole) == name

    widget.resize(1000, 400)
    widget.reload()
    qapp.processEvents()
    assert widget.table.columnWidth(widget.model.COL_NAME) >= 240


def test_local_file_name_tooltip_includes_name_and_path(file_widget):
    widget, _ = file_widget
    file = CloudFile(id=1, name="合同.pdf", local_path="/files/abc123")
    widget.model.load([file])
    tooltip = widget.model.data(widget.model.index(0, 0), Qt.ToolTipRole)
    assert tooltip == "合同.pdf\n/files/abc123"


def test_late_import_after_account_switch_does_not_upload_and_removes_copy(
    qapp, file_widget, tmp_path, monkeypatch,
):
    widget, config = file_widget
    source = tmp_path / "private.txt"
    source.write_bytes(b"private")
    copied = tmp_path / "orphan"
    started, release = threading.Event(), threading.Event()
    removed = []

    def copy(path, *, is_cancelled):
        started.set()
        assert release.wait(3)
        copied.write_bytes(b"private")
        return "a" * 64, 7, copied

    def remove(sha, path):
        removed.append((sha, path))
        copied.unlink(missing_ok=True)

    monkeypatch.setattr("ui.file_list_widget.hash_and_copy_into_container", copy)
    monkeypatch.setattr("ui.file_list_widget.remove_from_container", remove)
    widget._start_import(str(source))
    assert started.wait(3)
    old_repo, old_sync = widget.repo, widget.sync_service
    new_repo, new_sync = _Repo(), _Sync()
    try:
        config.cloud_user_email = "b@example.com"
        widget.rebind_services(new_repo, new_sync, widget.entitlement, widget.cloud_api)
    finally:
        release.set()
    _process_until(qapp, lambda: not widget._import_threads)
    assert not old_repo.files and not new_repo.files
    assert not old_sync.uploads and not new_sync.uploads
    assert removed == [("a" * 64, str(copied))]
    assert not copied.exists()


def test_import_copy_receives_cancellation_and_finishes_without_error_popup(
    qapp, file_widget, tmp_path, monkeypatch,
):
    widget, _ = file_widget
    source = tmp_path / "cancel.txt"
    source.write_bytes(b"cancel")
    started, cancelled = threading.Event(), threading.Event()
    errors = []

    def copy(path, *, is_cancelled):
        started.set()
        while not is_cancelled():
            time.sleep(0.001)
        cancelled.set()
        raise FileCopyCancelledError("cancelled")

    monkeypatch.setattr("ui.file_list_widget.hash_and_copy_into_container", copy)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args))
    widget._start_import(str(source))
    assert started.wait(3)
    assert widget.stop_imports(3000)
    _process_until(qapp, lambda: not widget._import_threads)
    assert cancelled.is_set()
    assert not errors and not widget.repo.files and not widget.sync_service.uploads


def test_import_timeout_keeps_thread_reference_for_later_drain(
    qapp, file_widget, tmp_path, monkeypatch,
):
    widget, _ = file_widget
    source = tmp_path / "blocked.txt"
    source.write_bytes(b"blocked")
    started, release = threading.Event(), threading.Event()

    def copy(path, *, is_cancelled):
        started.set()
        assert release.wait(3)
        raise FileCopyCancelledError("cancelled")

    monkeypatch.setattr("ui.file_list_widget.hash_and_copy_into_container", copy)
    widget._start_import(str(source))
    assert started.wait(3)
    try:
        worker = widget._import_threads[0]
        assert not widget.stop_imports(0)
        assert worker in widget._import_threads and worker.isRunning()
    finally:
        release.set()
    assert widget.stop_imports(3000)
    _process_until(qapp, lambda: not widget._import_threads)


def test_stale_copy_cleanup_preserves_same_content_committed_by_new_account(
    file_widget, tmp_path, monkeypatch,
):
    widget, config = file_widget
    sha = "b" * 64
    path = tmp_path / "shared-content"
    path.write_bytes(b"shared")
    fresh = CloudFile(id=2, name="new.txt", content_sha256=sha, local_path=str(path))
    widget.repo.files.append(fresh)
    stale = CloudFile(name="old.txt", content_sha256=sha, local_path=str(path))
    removed = []
    monkeypatch.setattr("ui.file_list_widget.remove_from_container", lambda *args: removed.append(args))
    widget._import_generation = 1
    config.cloud_user_email = "b@example.com"
    widget._account_identifier = "b@example.com"
    widget._after_import(stale, "", SimpleNamespace(generation=0, account_identifier="a@example.com"))
    assert not removed and path.exists()
    assert widget.repo.files == [fresh]
    assert not widget.sync_service.uploads


def test_file_open_copy_failure_never_opens_stored_original(qapp, file_widget, tmp_path, monkeypatch):
    widget, _ = file_widget
    stored = tmp_path / "stored"
    stored.write_bytes(b"must stay immutable")
    widget.model.load([CloudFile(id=1, name="example.txt", local_path=str(stored))])
    messages, opened = [], []

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("ui.file_list_widget.materialize_for_open", fail)
    monkeypatch.setattr("ui.file_list_widget.QDesktopServices.openUrl", lambda url: opened.append(url))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    widget._on_double_click(widget.model.index(0, 0))
    _process_until(qapp, lambda: bool(messages))
    assert "disk full" in messages[0] and not opened
    assert stored.read_bytes() == b"must stay immutable"


def test_file_page_delayed_status_and_inventory_do_not_run_after_destruction(qapp):
    from PySide6.QtTest import QTest
    widget = FileListWidget(_Repo(), _Sync(), _Entitlement(), None)
    widget._show_sync_status("temporary status")
    widget._status_hide_timer.start(5)
    widget._inventory_timer.start(5)
    destroyed = []
    widget.destroyed.connect(lambda: destroyed.append(True))
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert destroyed
    QTest.qWait(20)


def test_large_file_open_copy_runs_outside_gui_thread(qapp, file_widget, tmp_path, monkeypatch):
    widget, _ = file_widget
    stored, opened_copy = tmp_path / "stored", tmp_path / "editable.txt"
    stored.write_bytes(b"content")
    widget.model.load([CloudFile(id=1, name="editable.txt", local_path=str(stored))])
    started, release = threading.Event(), threading.Event()
    copied_threads, opened = [], []

    def copy(*args):
        copied_threads.append(threading.get_ident())
        started.set()
        assert release.wait(3)
        opened_copy.write_bytes(stored.read_bytes())
        return str(opened_copy)

    monkeypatch.setattr("ui.file_list_widget.materialize_for_open", copy)
    monkeypatch.setattr("ui.file_list_widget.QDesktopServices.openUrl", lambda url: opened.append(url.toLocalFile()))
    widget._on_double_click(widget.model.index(0, 0))
    assert started.wait(3)
    try:
        assert len(copied_threads) == 1
        assert copied_threads[0] != threading.get_ident()
        assert not opened
    finally:
        release.set()
    _process_until(qapp, lambda: bool(opened))
    assert opened == [str(opened_copy)]


class _BlockingWorker(QThread):
    def __init__(self, started, release, events):
        super().__init__()
        self.started, self.release, self.events = started, release, events

    def run(self):
        self.started.set()
        self.release.wait(3)
        self.events.append("old-write-finished")


class _RetiringSync(_Sync):
    def __init__(self, worker):
        super().__init__()
        self._worker_thread = worker

    def stop(self, timeout_ms=3000):
        self._worker_thread.requestInterruption()
        self._worker_thread.quit()
        return self._worker_thread.wait(timeout_ms)

    def persist_sync_cursor(self):
        pass


def _lifecycle_parent(api, sync, ent):
    parent = QWidget()
    parent.cloud_api = api
    parent.repository = SimpleNamespace(db=object())
    parent.cloud_sync_service = None
    parent.file_sync_service = sync
    parent.entitlement_service = ent
    parent.file_repository = _Repo()
    parent.file_list_widget = None
    parent.plugin_manager = None
    parent._cloud_sync_item_added_connected = False
    parent._cloud_sync_ui_connected = False
    return parent


def test_account_scope_binding_waits_until_old_service_finishes(qapp, monkeypatch):
    from ui.controllers.cloud_lifecycle_controller import CloudLifecycleController
    config = SimpleNamespace(cloud_user_email="a@example.com", files_sync_enabled=False)
    monkeypatch.setattr("ui.controllers.cloud_lifecycle_controller.settings", lambda: config)
    events = []
    started, release = threading.Event(), threading.Event()
    worker = _BlockingWorker(started, release, events)
    worker.start()
    assert started.wait(3)
    ent = _Entitlement()
    ent.set_cloud_api = lambda api: None
    ent.refresh_async = lambda: None
    monkeypatch.setattr("core.entitlement_service.get_entitlement_service", lambda **kwargs: ent)

    def new_repo(db, *, account_identifier):
        events.append("bind:" + account_identifier)
        return _Repo()

    monkeypatch.setattr("core.file_repository.CloudFileRepository", new_repo)
    parent = _lifecycle_parent(SimpleNamespace(is_authenticated=True), _RetiringSync(worker), ent)
    controller = CloudLifecycleController(parent, None)
    config.cloud_user_email = "b@example.com"
    try:
        controller.bootstrap_files_stack_after_login()
        assert controller.retiring_resources()[0]
        assert parent.file_repository is None and not events
    finally:
        release.set()
    _process_until(qapp, lambda: "bind:b@example.com" in events)
    assert events == ["old-write-finished", "bind:b@example.com"]
    assert not controller.retiring_resources()[0]
    assert worker.wait(3000)
    controller.begin_shutdown()
    parent.deleteLater()


@pytest.mark.parametrize("replace_server", [False, True])
def test_login_does_not_mutate_tokens_until_old_file_worker_is_drained(
    qapp, monkeypatch, login_pool, replace_server,
):
    from ui.cloud_login_widget import CloudLoginWidget
    from ui.controllers.cloud_lifecycle_controller import CloudLifecycleController
    config = SimpleNamespace(cloud_user_email="a@example.com", cloud_api_url="https://example.test",
                             files_sync_enabled=False)
    monkeypatch.setattr("ui.controllers.cloud_lifecycle_controller.settings", lambda: config)
    monkeypatch.setattr("ui.cloud_login_widget.settings", lambda: config)
    started, release = threading.Event(), threading.Event()
    events = []
    worker = _BlockingWorker(started, release, events)
    worker.start()
    assert started.wait(3)

    class API:
        is_authenticated = True
        base_url = config.cloud_api_url

        def login(self, email, password):
            events.append("set-token:" + email)
            config.cloud_user_email = email
            return {"user": email}

    parent = _lifecycle_parent(API(), _RetiringSync(worker), _Entitlement())
    controller = CloudLifecycleController(parent, None)
    login = CloudLoginWidget(parent.cloud_api, parent, controller.prepare_auth_change)
    if replace_server:
        login.url_edit.setText("https://new.example.test")

        def set_url(url):
            events.append("set-url")
            config.cloud_api_url = url

        def rebuild(url):
            events.append("rebuild-client")
            return API()

        monkeypatch.setattr("ui.cloud_login_widget.set_cloud_api_url", set_url)
        monkeypatch.setattr("ui.cloud_login_widget.rebuild_cloud_client_for_url", rebuild)
    login.email_edit.setText("b@example.com")
    login.password_edit.setText("password")
    received = []
    login.login_succeeded.connect(received.append)
    try:
        login._do_login()
        qapp.processEvents()
        assert events == []
        assert config.cloud_user_email == "a@example.com"
        assert controller.retiring_resources()[0]
    finally:
        release.set()
    _process_until(qapp, lambda: bool(received))
    expected = ["old-write-finished"]
    if replace_server:
        expected += ["set-url", "rebuild-client"]
    assert events == expected + ["set-token:b@example.com"]
    assert worker.wait(3000)
    controller.begin_shutdown()
    parent.deleteLater()


def test_login_timeout_keeps_attempt_serial_and_ignores_other_request_result(qapp, monkeypatch, login_pool):
    from ui.cloud_login_widget import CloudLoginWidget
    config = SimpleNamespace(cloud_api_url="https://example.test")
    monkeypatch.setattr("ui.cloud_login_widget.settings", lambda: config)
    started, release = threading.Event(), threading.Event()
    calls = []

    class API:
        base_url = config.cloud_api_url

        def login(self, email, password):
            calls.append(email)
            started.set()
            assert release.wait(3)
            return {"email": email}

    widget = CloudLoginWidget(API())
    widget.email_edit.setText("a@example.com")
    widget.password_edit.setText("password")
    results = []
    widget.login_succeeded.connect(results.append)
    widget._do_login()
    assert started.wait(3)
    try:
        widget._on_login_timeout()
        widget.email_edit.setText("b@example.com")
        widget._do_login()
        widget._handle_login_result(widget._current_request_id + 1, {"email": "wrong"}, "")
        assert calls == ["a@example.com"]
        assert widget._login_in_flight and not widget.login_btn.isEnabled()
        assert not results
    finally:
        release.set()
    _process_until(qapp, lambda: bool(results))
    assert results == [{"email": "a@example.com"}]
    widget.deleteLater()


def test_logout_does_not_clear_tokens_before_old_worker_finishes(qapp, monkeypatch):
    from ui.controllers.cloud_lifecycle_controller import CloudLifecycleController
    from ui.subscription_widget import SubscriptionWidget
    events = []
    started, release = threading.Event(), threading.Event()
    worker = _BlockingWorker(started, release, events)
    worker.start()
    assert started.wait(3)

    class API:
        is_authenticated = True

        def logout(self):
            events.append("clear-token")
            self.is_authenticated = False

    parent = _lifecycle_parent(API(), _RetiringSync(worker), _Entitlement())
    controller = CloudLifecycleController(parent, None)
    monkeypatch.setattr(SubscriptionWidget, "_load_subscription", lambda self: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    widget = SubscriptionWidget(parent.cloud_api, parent, controller.prepare_auth_change)
    finished = []
    widget.logout_completed.connect(lambda: finished.append(True))
    try:
        widget._do_logout()
        qapp.processEvents()
        assert parent.cloud_api.is_authenticated and not events
        assert not finished
    finally:
        release.set()
    _process_until(qapp, lambda: bool(finished))
    assert events == ["old-write-finished", "clear-token"]
    assert worker.wait(3000)
    controller.begin_shutdown()
    parent.deleteLater()


def test_deferred_cloud_start_does_not_restart_worker_after_shutdown(qapp):
    from ui.controllers.cloud_lifecycle_controller import CloudLifecycleController

    class Monitor(QObject):
        item_added = Signal(object)

    class Sync(QObject):
        new_items_available = Signal(list)
        upload_completed = Signal(int)

        def __init__(self):
            super().__init__()
            self.starts = 0

        def enqueue_upload(self, item):
            pass

        def start(self):
            self.starts += 1

    parent = _lifecycle_parent(SimpleNamespace(is_authenticated=True), None, None)
    service = Sync()
    parent.cloud_sync_service = service
    parent.clipboard_monitor = Monitor()
    parent.list_controller = SimpleNamespace(on_new_items=lambda items: None,
                                             refresh_cloud_state=lambda: None)
    controller = CloudLifecycleController(parent, None)
    controller.bootstrap_cloud_sync_after_login()
    controller.begin_shutdown()
    qapp.processEvents()
    assert not service.starts
    parent.deleteLater()


class _ShareAPI:
    is_authenticated = True
    user_id = "user"

    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.requests = []

    def create_share_link(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


class _ShareDB:
    def __init__(self):
        self.writes = []

    def execute_with_retry(self, operation):
        operation(None)

    def execute_write(self, conn, sql, values):
        self.writes.append(values)


def test_share_dialog_sends_cloud_ids_from_current_repository(qapp, monkeypatch):
    db = _ShareDB()
    repo = SimpleNamespace(db=db, get_cloud_ids_for_ids=lambda ids: {7: 101})
    api = _ShareAPI({"id": "share", "token": "token", "share_url": "https://example.test/share"})
    service = ShareService(repo, lambda: api)
    item = TextClipboardItem(id=7, cloud_id=None, space_id="space", text_content="selected")
    dialog = ShareLinkDialog([item], service, "space")
    monkeypatch.setattr(dialog, "_render_qr", lambda text: None)
    try:
        dialog._on_create_clicked()
        assert api.requests[0]["item_ids"] == [101]
        assert api.requests[0]["space_id"] == "space"
        assert dialog._stack.currentIndex() == 1
        assert dialog._url_edit.text() == "https://example.test/share"
        assert db.writes[0][4] == "[101]"
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("cloud_id,item_space,target_space,reason", [
    (None, "space", "space", "完成云端同步"),
    (101, "other", "space", "目标空间"),
    (101, None, "", "请选择云端空间"),
])
def test_share_dialog_blocks_unsynced_or_wrong_space_selection(
    qapp, monkeypatch, cloud_id, item_space, target_space, reason,
):
    db = _ShareDB()
    repo = SimpleNamespace(db=db, get_cloud_ids_for_ids=lambda ids: {7: cloud_id})
    api = _ShareAPI()
    dialog = ShareLinkDialog(
        [TextClipboardItem(id=7, cloud_id=101, space_id=item_space)],
        ShareService(repo, lambda: api), target_space,
    )
    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: messages.append(args[-1]))
    try:
        dialog._on_create_clicked()
        assert reason in messages[0]
        assert not api.requests and not db.writes
        assert dialog._stack.currentIndex() == 0
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("response,error", [
    (None, RuntimeError("backend failure")),
    (None, None),
    ({"token": "no-url"}, None),
])
def test_share_service_cloud_failure_never_creates_local_success(response, error):
    db = _ShareDB()
    api = _ShareAPI(response, error)
    service = ShareService(SimpleNamespace(db=db), lambda: api)
    with pytest.raises((RuntimeError, ValueError)):
        service.create_share_link("space", [101], 3600)
    assert not db.writes


def test_share_local_simulation_requires_explicit_opt_in():
    db = _ShareDB()
    repo = SimpleNamespace(db=db)
    with pytest.raises(RuntimeError):
        ShareService(repo).create_share_link("space", [101], 3600)
    assert not db.writes
    result = ShareService(repo, allow_local_simulation=True).create_share_link("space", [101], 3600)
    assert result["token"] and result["share_url"] == ""
    assert len(db.writes) == 1


@pytest.mark.parametrize("tag,space,starred", [("tag", None, False), (None, "space", False),
                                               (None, "", False), (None, None, True)])
def test_incoming_clipboard_item_reloads_active_filters(monkeypatch, tag, space, starred):
    events = []
    controller = SimpleNamespace(
        _current_page=0, _search_query="", _starred_only=starred,
        _current_tag_id=tag, _current_space_id=space,
        _parent=SimpleNamespace(), prepend_item=lambda item: events.append("prepend"),
        load_items=lambda: events.append("reload"),
    )
    monkeypatch.setattr("ui.controllers.clipboard_list_controller.analytics.mark_first", lambda *args: None)
    ClipboardListController.on_item_added(controller, TextClipboardItem(text_content="new"))
    assert events == ["reload"]


def test_timeline_visible_buttons_forward_all_actions(qapp):
    item = ImageClipboardItem(id=7, cloud_id=101)
    timeline = TimelineView()
    actions = []
    for name in ("item_star_requested", "item_delete_requested", "item_save_requested",
                 "cloud_delete_requested", "image_url_copy_requested"):
        getattr(timeline, name).connect(lambda value, action=name: actions.append((action, value)))
    try:
        timeline.set_items([item])
        row = timeline.findChild(ClipboardItemWidget)
        for name in ("starButton", "deleteButton", "saveButton", "cloudButton", "urlButton"):
            button = row.findChild(QPushButton, name)
            assert button is not None
            button.click()
        assert [action for action, _ in actions] == [
            "item_star_requested", "item_delete_requested", "item_save_requested",
            "cloud_delete_requested", "image_url_copy_requested",
        ]
        assert all(value is item for _, value in actions)
    finally:
        timeline.deleteLater()


def test_blank_header_container_drags_but_interactive_child_does_not(qapp, monkeypatch):
    from ui.edge_window import EdgeHiddenWindow

    class Probe(EdgeHiddenWindow):
        def _init_position(self):
            pass

    window = Probe()
    container = QWidget(window)
    container.setGeometry(0, 0, 300, 80)
    edit = QLineEdit(container)
    edit.setGeometry(130, 4, 150, 30)
    container.show()
    edit.show()

    def press(x):
        event = QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(x, 15), QPointF(x, 15),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        window.mousePressEvent(event)

    try:
        press(20)
        assert window._dragging
        window._dragging = False
        press(170)
        assert not window._dragging
    finally:
        window._mouse_check_timer.stop()
        window.deleteLater()


@pytest.mark.parametrize("entry", ["app.quit", "posted_event", "QApplication.quit"])
def test_native_and_explicit_quit_wait_for_cleanup_before_about_to_quit(tmp_path, entry):
    script = r'''
import config, sys
from pathlib import Path
config._store = config.SettingsStore(Path(sys.argv[1]) / "settings.json")
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication
from main import ClipboardApplication
app = ClipboardApplication([])
events = []
def cleanup():
    events.append("cleanup")
    assert "about" not in events
    QTimer.singleShot(20, app.complete_quit)
app._quit_handler = cleanup
app.aboutToQuit.connect(lambda: events.append("about"))
entry = sys.argv[2]
if entry == "posted_event":
    action = lambda: QCoreApplication.postEvent(app, QEvent(QEvent.Quit))
elif entry == "QApplication.quit":
    action = QApplication.quit
else:
    action = app.quit
QTimer.singleShot(0, action)
QTimer.singleShot(2000, app.complete_quit)
assert app.exec() == 0
assert events == ["cleanup", "about"], events
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), entry],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
