"""Local clipboard main-path E2E tests.

These tests use the real SQLite database, repository, and ClipboardMonitor, but
replace the OS clipboard with a deterministic fake object.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class _FakeMimeData:
    def hasUrls(self):
        return False

    def urls(self):
        return []

    def hasImage(self):
        return False

    def hasText(self):
        return True


class _FakeClipboard:
    def __init__(self):
        self._text = ""
        self._mime = _FakeMimeData()

    def set_text(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def image(self):
        return None

    def mimeData(self):
        return self._mime


def _patch_monitor_settings(monkeypatch):
    from config import AppSettings
    import core.clipboard_monitor as cm

    snap = AppSettings(
        device_id="local-e2e-device",
        device_name="Local E2E",
        save_text=True,
        save_images=False,
        max_items=100,
        retention_days=0,
        capture_source_title=False,
    )
    monkeypatch.setattr(cm, "settings", lambda: snap)
    return snap


def _patch_source_app(monkeypatch):
    from core.source_app.base import SourceApp
    import core.clipboard_monitor as cm

    monkeypatch.setattr(
        cm,
        "get_current_source_app",
        lambda: SourceApp(
            app_name="E2E App",
            bundle_id="com.sharedclipboard.e2e",
            exe_path="",
            window_title="Ignored Title",
        ),
    )


def test_local_clipboard_main_path_e2e(qapp, tmp_path, monkeypatch):
    import config
    from core.clipboard_monitor import ClipboardMonitor
    from core.database import DatabaseManager
    from core.repository import ClipboardRepository

    monkeypatch.setattr(config, "get_config_dir", lambda: tmp_path, raising=False)
    _patch_monitor_settings(monkeypatch)
    _patch_source_app(monkeypatch)

    db = DatabaseManager(str(tmp_path / "clipboard-e2e.db"))
    repo = ClipboardRepository(db)
    monitor = ClipboardMonitor(repo)
    fake_clipboard = _FakeClipboard()
    monitor.clipboard = fake_clipboard
    monitor._monitoring = True

    captured = []
    monitor.item_added.connect(captured.append)

    try:
        fake_clipboard.set_text("hello local rocket search path")
        monitor._poll_clipboard()

        items, total = repo.get_items(page=0, page_size=10)
        assert total == 1
        assert len(captured) == 1
        assert captured[0].id == items[0].id
        assert captured[0].text_content == "hello local rocket search path"
        assert captured[0].source_app == "com.sharedclipboard.e2e"
        first_created_at = items[0].created_at

        hits, hits_total = repo.search_by_keyword("rocket")
        assert hits_total == 1
        assert hits[0].id == captured[0].id

        misses, misses_total = repo.search_by_keyword("nonexistent_xyz")
        assert misses == []
        assert misses_total == 0

        # Same tick: in-memory duplicate guard should suppress a second signal.
        monitor._poll_clipboard()
        items_after_same_tick, total_after_same_tick = repo.get_items(page=0, page_size=10)
        assert total_after_same_tick == 1
        assert items_after_same_tick[0].id == captured[0].id
        assert len(captured) == 1

        # Later tick: repository hash duplicate should touch the existing row
        # and emit the same item id so the UI can move it to the top.
        monitor._last_text = None
        monitor._poll_clipboard()

        items_after_duplicate, total_after_duplicate = repo.get_items(page=0, page_size=10)
        assert total_after_duplicate == 1
        assert len(captured) == 2
        assert captured[1].id == captured[0].id
        assert items_after_duplicate[0].id == captured[0].id
        assert items_after_duplicate[0].created_at >= first_created_at
    finally:
        monitor.stop()
        db.close()
