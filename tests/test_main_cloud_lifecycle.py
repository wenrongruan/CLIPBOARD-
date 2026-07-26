"""Application 壳与 AppContext 动态云服务引用的一致性测试。"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

from main import ClipboardApp


def test_deferred_file_start_reuses_service_created_during_login():
    service = MagicMock()
    app = ClipboardApp.__new__(ClipboardApp)
    app.ctx = SimpleNamespace(
        cloud_api=object(),
        cloud_sync_service=None,
        entitlement_service=object(),
        file_repository=object(),
        file_sync_service=service,
    )
    app.cloud_api = object()
    app.cloud_sync_service = None
    app.entitlement_service = None
    app.file_repository = None
    app.file_sync_service = None
    app._file_cursor_atexit_registered = True
    app._startup_phase = lambda _name: nullcontext()
    app._ensure_file_sync_services = MagicMock(
        side_effect=AssertionError("不应重复创建文件同步服务")
    )

    app._start_file_sync_deferred()

    assert app.file_sync_service is service
    service.start.assert_called_once_with()
    app._ensure_file_sync_services.assert_not_called()


def test_deferred_file_start_does_not_restart_logged_out_service():
    old_service = MagicMock()
    app = ClipboardApp.__new__(ClipboardApp)
    app.ctx = SimpleNamespace(
        cloud_api=None,
        cloud_sync_service=None,
        entitlement_service=None,
        file_repository=None,
        file_sync_service=None,
    )
    app.cloud_api = object()
    app.cloud_sync_service = None
    app.entitlement_service = object()
    app.file_repository = object()
    app.file_sync_service = old_service
    app._file_cursor_atexit_registered = True
    app._startup_phase = lambda _name: nullcontext()
    app._ensure_file_sync_services = MagicMock()

    app._start_file_sync_deferred()

    old_service.start.assert_not_called()
    app._ensure_file_sync_services.assert_called_once_with()
