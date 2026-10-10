"""Isolate user state and explicitly finish workers before natural pytest exit."""

from __future__ import annotations

import functools
import os
from pathlib import Path
import socket
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_session_patch = None
_session_directory = None
_active_directory = None
_credentials = {}


def pytest_addoption(parser):
    parser.addoption(
        "--allow-network", action="store_true", default=False,
        help="Allow explicitly configured integration tests to use real network services.",
    )


def pytest_configure(config):
    # Install before collection: imported aliases also resolve to isolated state.
    global _session_patch, _session_directory, _active_directory
    import config as app_config
    import keyring
    from core.cloud.http import HttpClient

    _session_directory = tempfile.TemporaryDirectory(prefix="sharedclipboard-pytest-")
    _active_directory = Path(_session_directory.name)
    _session_patch = pytest.MonkeyPatch()
    _session_patch.setattr(app_config, "get_config_dir", lambda: _active_directory)
    _session_patch.setattr(app_config, "_store", app_config.SettingsStore(_active_directory / "settings.json"))
    _session_patch.setattr(app_config, "_read_auth_json_token", lambda field: "")
    _session_patch.setattr(HttpClient, "_update_auth_json", lambda self, access, refresh: None)
    _session_patch.setattr(keyring, "get_password", lambda service, key: _credentials.get((service, key)))
    _session_patch.setattr(keyring, "set_password", lambda service, key, value: _credentials.__setitem__((service, key), value))
    _session_patch.setattr(keyring, "delete_password", lambda service, key: _credentials.pop((service, key), None))
    if not config.getoption("--allow-network"):
        def deny_connection(*args, **kwargs):
            raise OSError("Real network disabled in unit tests; use a mock transport")
        _session_patch.setattr(socket.socket, "connect", deny_connection)
        _session_patch.setattr(socket.socket, "connect_ex", deny_connection)


def pytest_collection_modifyitems(config, items):
    if config.getoption("--allow-network"):
        return
    for item in items:
        if item.path.name == "test_mysql_schema.py":
            item.add_marker(pytest.mark.skip(reason="Real MySQL requires --allow-network and TEST_MYSQL_*"))


@pytest.fixture(scope="session", autouse=True)
def _qt_application():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _isolated_user_state(tmp_path, monkeypatch, _qt_application):
    global _active_directory
    import config as app_config
    import utils.secure_store as secure_store

    _active_directory = tmp_path
    _credentials.clear()
    monkeypatch.setattr(app_config, "_store", app_config.SettingsStore(tmp_path / "settings.json"))
    monkeypatch.setattr(secure_store, "_active_backend", "unknown")
    yield
    store = app_config.get_store()
    if store._save_timer is not None:
        store._save_timer.stop()
    store.flush()
    _credentials.clear()


@pytest.fixture(autouse=True)
def _finish_background_resources(monkeypatch, _isolated_user_state):
    """Own resources created by a test until their workers are fully stopped."""
    from concurrent.futures import ThreadPoolExecutor
    from PySide6.QtCore import QCoreApplication, QEvent
    from core.clipboard_monitor import ClipboardMonitor
    from core.cloud.http import HttpClient
    from core.cloud_sync_service import CloudSyncService
    from core.entitlement_service import EntitlementService
    from core.file_sync_service import FileCloudSyncService
    from ui.file_list_widget import _ImportWorker

    resources = []
    executors = []

    def track_constructor(cls, target):
        original = cls.__init__

        @functools.wraps(original)
        def construct(self, *args, **kwargs):
            target.append(self)
            original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "__init__", construct)

    for cls in (ClipboardMonitor, CloudSyncService, FileCloudSyncService, EntitlementService, HttpClient, _ImportWorker):
        track_constructor(cls, resources)
    track_constructor(ThreadPoolExecutor, executors)

    yield

    failures = []
    for resource in reversed(resources):
        try:
            if isinstance(resource, (ClipboardMonitor, CloudSyncService, FileCloudSyncService)):
                resource.stop()
            if isinstance(resource, _ImportWorker):
                resource.requestInterruption()
                resource.quit()
                if not resource.wait(5000):
                    failures.append("File import did not finish")
            worker = getattr(resource, "_worker_thread", None)
            if worker is not None:
                worker.requestInterruption()
                worker.quit()
                if not worker.wait(5000):
                    failures.append(f"{type(resource).__name__} worker did not finish")
            if isinstance(resource, EntitlementService):
                if not resource.wait_for_refresh(timeout=5):
                    failures.append("Entitlement refresh did not finish")
        except RuntimeError as exc:
            if "already deleted" not in str(exc):
                failures.append(str(exc))
    for executor in executors:
        executor.shutdown(wait=True, cancel_futures=True)
    for resource in resources:
        if isinstance(resource, HttpClient):
            resource.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    if failures:
        pytest.fail("Background teardown failed: " + "; ".join(failures))


def pytest_unconfigure(config):
    global _session_patch, _session_directory
    if _session_patch is not None:
        _session_patch.undo()
        _session_patch = None
    if _session_directory is not None:
        _session_directory.cleanup()
        _session_directory = None
