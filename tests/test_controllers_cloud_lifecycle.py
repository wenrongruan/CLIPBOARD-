"""CloudLifecycleController 构造 smoke test。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget, QStackedWidget

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.controllers.cloud_lifecycle_controller import CloudLifecycleController
from ui.file_list_widget import FileListWidget
from core.entitlement_service import Plan
from core.file_models import CloudFile


class _FakeFileRepository:
    def list_files(self, include_deleted=False):
        return []


class _FakeFileSyncService(QObject):
    file_added = Signal(object)
    file_updated = Signal(object)
    file_deleted = Signal(int)
    upload_progress = Signal(int, int, int)
    download_progress = Signal(int, int, int)
    upload_finished = Signal(int, bool, str)
    download_finished = Signal(int, bool, str)
    sync_error = Signal(str, int)

    def __init__(self):
        super().__init__()
        self.started = False

    def start(self):
        self.started = True


class _FakeEntitlement(QObject):
    entitlement_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.failed = False

    def refresh_async(self):
        pass

    def refresh_state(self):
        return False, self.failed

    def current(self):
        return SimpleNamespace(
            plan=Plan.FREE,
            files_quota_bytes=0,
            files_used_bytes=0,
        )

    def can_use_files(self):
        return False, "需要升级"


class _FakeClipboardMonitor(QObject):
    item_added = Signal(object)


class _FakeCloudSyncService(QObject):
    new_items_available = Signal(list)
    upload_completed = Signal(int)

    def __init__(self):
        super().__init__()
        self.enqueued = []
        self.stopped = False

    def enqueue_upload(self, item):
        self.enqueued.append(item)

    def stop(self):
        self.stopped = True


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_controller_constructs(qapp):
    parent = QWidget()
    ctx = MagicMock()
    c = CloudLifecycleController(parent, ctx)
    assert c is not None
    parent.close()
    parent.deleteLater()


def test_existing_file_page_rebinds_after_login(qapp):
    parent = QWidget()
    parent.cloud_api = MagicMock()
    parent.cloud_api.is_authenticated = True
    parent.repository = MagicMock()
    parent.entitlement_service = MagicMock()
    parent.file_repository = MagicMock()
    parent.file_sync_service = MagicMock()
    parent.file_list_widget = MagicMock()
    ctx = MagicMock()
    controller = CloudLifecycleController(parent, ctx)

    controller.bootstrap_files_stack_after_login()

    parent.file_list_widget.rebind_services.assert_called_once_with(
        parent.file_repository,
        parent.file_sync_service,
        parent.entitlement_service,
        parent.cloud_api,
    )
    assert ctx.file_sync_service is parent.file_sync_service
    parent.close()
    parent.deleteLater()


def test_open_files_starts_manual_sync_with_background_switch_off(qapp, monkeypatch):
    from ui.controllers import cloud_lifecycle_controller as cloud_module
    from ui.controllers.clipboard_list_controller import ClipboardListController

    parent = QWidget()
    parent.cloud_api = SimpleNamespace(is_authenticated=True)
    parent.repository = SimpleNamespace(db=object())
    parent.entitlement_service = None
    parent.file_repository = None
    parent.file_sync_service = None
    parent.file_list_widget = None
    parent._stack = QStackedWidget(parent)
    parent._stack.addWidget(QWidget())
    parent._file_page_placeholder = QWidget()
    parent._stack.addWidget(parent._file_page_placeholder)
    ctx = SimpleNamespace(repository=parent.repository, entitlement_service=None)
    entitlement = _FakeEntitlement()
    sync_service = _FakeFileSyncService()
    monkeypatch.setattr(cloud_module, "settings", lambda: SimpleNamespace(files_sync_enabled=False))
    monkeypatch.setattr(
        "core.entitlement_service.get_entitlement_service", lambda **_kw: entitlement
    )
    monkeypatch.setattr(
        "core.file_repository.CloudFileRepository", lambda _db: _FakeFileRepository()
    )
    monkeypatch.setattr(
        "core.file_sync_service.FileCloudSyncService", lambda *_args: sync_service
    )
    parent.cloud_controller = CloudLifecycleController(parent, ctx)

    ClipboardListController.on_tab_changed(
        SimpleNamespace(_parent=parent, ctx=ctx), 1
    )

    assert sync_service.started
    assert isinstance(parent.file_list_widget, FileListWidget)
    assert parent._file_page_placeholder is None
    assert parent._stack.currentIndex() == 1
    assert parent.file_list_widget.gate_banner_text.text() == "正在验证云端套餐..."
    assert not parent.file_list_widget.upgrade_btn.isVisible()
    entitlement.failed = True
    parent.file_list_widget._refresh_gate_view()
    assert "无法验证云端套餐" in parent.file_list_widget.gate_banner_text.text()
    parent.close()
    parent.deleteLater()


def test_file_page_rebind_disconnects_old_service(qapp):
    old_sync = _FakeFileSyncService()
    new_sync = _FakeFileSyncService()
    old_entitlement = _FakeEntitlement()
    new_entitlement = _FakeEntitlement()
    new_repo = _FakeFileRepository()
    new_cloud_api = object()
    widget = FileListWidget(
        _FakeFileRepository(),
        old_sync,
        old_entitlement,
        object(),
    )

    widget.rebind_services(
        new_repo,
        new_sync,
        new_entitlement,
        new_cloud_api,
    )
    old_sync.file_added.emit(CloudFile(id=1, name="old"))
    assert widget.model.rowCount() == 0

    new_sync.file_added.emit(CloudFile(id=2, name="new"))
    assert widget.model.rowCount() == 1
    assert widget.repo is new_repo
    assert widget.sync_service is new_sync
    assert widget.entitlement is new_entitlement
    assert widget.cloud_api is new_cloud_api
    widget.close()
    widget.deleteLater()


def test_logout_disconnects_old_cloud_sync_service(qapp):
    parent = QWidget()
    monitor = _FakeClipboardMonitor()
    cloud_sync = _FakeCloudSyncService()
    parent.cloud_sync_service = cloud_sync
    parent.file_sync_service = None
    parent.entitlement_service = object()
    parent.file_repository = object()
    parent._cloud_sync_item_added_connected = True
    parent._cloud_sync_ui_connected = False
    ctx = SimpleNamespace(
        repository=MagicMock(),
        sync_service=MagicMock(),
        clipboard_monitor=monitor,
        cloud_sync_service=cloud_sync,
        file_sync_service=None,
        cloud_api=object(),
        entitlement_service=parent.entitlement_service,
        file_repository=parent.file_repository,
    )
    monitor.item_added.connect(cloud_sync.enqueue_upload)
    controller = CloudLifecycleController(parent, ctx)

    controller.teardown_cloud_sync_after_logout()
    monitor.item_added.emit(object())

    assert cloud_sync.stopped is True
    assert cloud_sync.enqueued == []
    assert parent.cloud_sync_service is None
    assert ctx.cloud_sync_service is None
    parent.close()
    parent.deleteLater()
