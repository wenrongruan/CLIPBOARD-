"""The real application's quit paths must drain writes before closing SQLite."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("quit_mode", ["explicit", "native_event", "auth_pending"])
def test_application_naturally_exits_after_pending_write(tmp_path, quit_mode):
    project = Path(__file__).resolve().parents[1]
    script = textwrap.dedent("""
        import json
        from pathlib import Path
        import socket
        import sqlite3
        import sys
        import threading

        import keyring
        import config

        directory = Path(sys.argv[1])
        config.get_config_dir = lambda: directory
        config._store = config.SettingsStore(directory / 'settings.json')
        config._read_auth_json_token = lambda field: ''
        keyring.get_password = lambda *args: None
        keyring.set_password = lambda *args: None
        keyring.delete_password = lambda *args: None
        def deny_network(*args, **kwargs):
            raise OSError('Network disabled in shutdown integration test')
        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        config.update_settings(
            database_path=str(directory / 'history.db'),
            db_type='sqlite', onboarding_done=True,
            cloud_scope_explainer_shown=True,
        )

        import main
        from core.app_context import AppContext
        from core.models import TextClipboardItem
        from PySide6.QtCore import QCoreApplication, QEvent, QTimer

        main.ClipboardApp._init_hotkey = lambda self: None
        main.ClipboardApp._flush_startup_health_notifications = lambda self: None
        application = main.ClipboardApp()
        started = threading.Event()
        release = threading.Event()
        def delayed_write():
            started.set()
            assert release.wait(5), 'Quit stopped the event loop before writes drained'
            return application.repository.add_item(TextClipboardItem(
                text_content='write must survive application quit',
                device_id='shutdown-test',
            ))
        auth_pending = sys.argv[2] == 'auth_pending'
        executor = (application.main_window._cloud_executor if auth_pending
                    else application.main_window._io_executor)
        future = executor.submit(delayed_write)
        assert started.wait(2)
        auth_callbacks = []
        if auth_pending:
            application.main_window.cloud_controller.prepare_auth_change(
                lambda: auth_callbacks.append('credentials changed')
            )
        def request_quit():
            if sys.argv[2] != 'native_event':
                application.app.quit()
            else:
                QCoreApplication.postEvent(application.app, QEvent(QEvent.Type.Quit))
        QTimer.singleShot(10, request_quit)
        QTimer.singleShot(100, release.set)
        code = application.run()
        assert code == 0
        item_id = future.result(timeout=0)
        assert item_id > 0
        assert AppContext._instance is None
        assert auth_callbacks == []
        with sqlite3.connect(directory / 'history.db') as db:
            assert db.execute(
                'SELECT text_content FROM clipboard_items WHERE id = ?',
                (item_id,),
            ).fetchone()[0] == 'write must survive application quit'
        saved = json.loads((directory / 'settings.json').read_text())
        assert saved['onboarding_done'] is True
        print('pending write saved; application exited naturally')
    """)
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["SC_DEBUG"] = "0"
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), quit_mode],
        cwd=project, env=environment, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pending write saved; application exited naturally" in result.stdout


@pytest.mark.parametrize("service_field", ["cloud_sync_service", "file_sync_service"])
def test_context_shutdown_waits_for_a_worker_that_has_not_stopped(service_field):
    import threading
    import time
    from types import SimpleNamespace
    from PySide6.QtCore import QThread
    from core.app_context import AppContext
    from core.models import TextClipboardItem

    context = AppContext.bootstrap()
    started = threading.Event()
    results = []

    class DelayedWriter(QThread):
        def run(self):
            started.set()
            time.sleep(0.05)
            try:
                results.append(context.repository.add_item(TextClipboardItem(
                    text_content="finish before context closes the database",
                    device_id="shutdown-test",
                )))
            except Exception as error:
                results.append(error)

    worker = DelayedWriter()
    setattr(context, service_field, SimpleNamespace(
        stop=lambda: False, _worker_thread=worker,
    ))
    worker.start()
    try:
        assert started.wait(2)
        context.shutdown()
        assert not worker.isRunning()
        assert len(results) == 1 and isinstance(results[0], int) and results[0] > 0, results
    finally:
        worker.wait(2000)
        if AppContext._instance is context:
            context.shutdown()
