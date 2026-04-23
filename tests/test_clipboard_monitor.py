"""ClipboardMonitor 的来源 App 捕获集成测试。

这里用 offscreen Qt + 内存数据库，不直接依赖真实剪贴板/前台窗口；
通过 mock `get_current_source_app`、patch `clipboard.text()`/`clipboard.image()`
触发 `_handle_text` / `_handle_image` 路径，断言生成的 item 带上了正确的
`source_app` / `source_title` 字段。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def tmp_config_env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    import config
    monkeypatch.setattr(config, "get_config_dir", lambda: cfg_dir, raising=False)
    yield cfg_dir


class _FakeRepository:
    """只实现 monitor 用到的三个方法：get_by_hash / add_item / touch_item /
    cleanup_*。保存 add_item 传入的 item，方便断言。
    """

    def __init__(self):
        self.added: list = []
        self._next_id = 1

    def get_by_hash(self, content_hash: str):
        return None

    def add_item(self, item) -> int:
        item_id = self._next_id
        self._next_id += 1
        item.id = item_id
        self.added.append(item)
        return item_id

    def touch_item(self, item_id: int, created_at: int) -> bool:  # pragma: no cover
        return True

    def cleanup_old_items(self, max_items: int) -> int:  # pragma: no cover
        return 0

    def cleanup_expired_items(self, retention_days: int) -> int:  # pragma: no cover
        return 0


@pytest.fixture
def monitor(qapp, tmp_config_env):
    """构造一个 ClipboardMonitor，仓储换成 FakeRepository 避免依赖 DB schema。"""
    from core.clipboard_monitor import ClipboardMonitor

    repo = _FakeRepository()
    m = ClipboardMonitor(repo)
    yield m


def _make_source_app(app_name="Chrome",
                     bundle_id="com.google.Chrome",
                     exe_path="/Applications/Chrome.app",
                     window_title="Test Page"):
    from core.source_app.base import SourceApp
    return SourceApp(
        app_name=app_name,
        bundle_id=bundle_id,
        exe_path=exe_path,
        window_title=window_title,
    )


def _patch_settings(monkeypatch, capture_source_title: bool):
    """让 `settings()` 返回一个带期望字段的 dataclass snapshot。"""
    from config import AppSettings
    snap = AppSettings(
        device_id="test-device",
        device_name="Tester",
        save_text=True,
        save_images=True,
        capture_source_title=capture_source_title,
    )
    # 直接 patch 模块里的 settings 引用；monitor.py 通过 `from config import settings`
    # 拿到的是函数引用，我们替换成 lambda 返回定制 snapshot。
    import core.clipboard_monitor as cm
    monkeypatch.setattr(cm, "settings", lambda: snap)
    return snap


# ---------------------------------------------------------------------------
# 文本路径：source_app / source_title 填充
# ---------------------------------------------------------------------------


class TestHandleTextSourceApp:
    def test_source_app_from_bundle_id(self, monitor, monkeypatch):
        """默认配置下：source_app 取 bundle_id，source_title 为空。"""
        s = _patch_settings(monkeypatch, capture_source_title=False)

        import core.clipboard_monitor as cm
        monkeypatch.setattr(cm, "get_current_source_app", lambda: _make_source_app())
        # 让剪贴板 text() 返回固定文本
        monitor.clipboard = MagicMock()
        monitor.clipboard.text.return_value = "hello from chrome"

        captured = []
        monitor.item_added.connect(lambda it: captured.append(it))

        monitor._handle_text(s)

        assert len(captured) == 1
        item = captured[0]
        assert item.text_content == "hello from chrome"
        assert item.source_app == "com.google.Chrome"
        assert item.source_title == ""  # 默认关

    def test_source_title_captured_when_enabled(self, monitor, monkeypatch):
        """capture_source_title=True 时，source_title 拿到 window_title。"""
        s = _patch_settings(monkeypatch, capture_source_title=True)

        import core.clipboard_monitor as cm
        monkeypatch.setattr(cm, "get_current_source_app", lambda: _make_source_app())
        monitor.clipboard = MagicMock()
        monitor.clipboard.text.return_value = "hello with title"

        captured = []
        monitor.item_added.connect(lambda it: captured.append(it))

        monitor._handle_text(s)

        assert len(captured) == 1
        assert captured[0].source_app == "com.google.Chrome"
        assert captured[0].source_title == "Test Page"

    def test_fallback_to_app_name(self, monitor, monkeypatch):
        """bundle_id 为空时退化到 app_name。"""
        s = _patch_settings(monkeypatch, capture_source_title=False)

        import core.clipboard_monitor as cm
        fake = _make_source_app(bundle_id="", app_name="Finder", exe_path="/usr/bin/finder")
        monkeypatch.setattr(cm, "get_current_source_app", lambda: fake)
        monitor.clipboard = MagicMock()
        monitor.clipboard.text.return_value = "from finder"

        captured = []
        monitor.item_added.connect(lambda it: captured.append(it))

        monitor._handle_text(s)
        assert captured[0].source_app == "Finder"

    def test_source_app_capture_failure_does_not_block(self, monitor, monkeypatch, caplog):
        """get_current_source_app 抛异常时 item 仍被创建，source_app 为空。"""
        s = _patch_settings(monkeypatch, capture_source_title=False)

        import core.clipboard_monitor as cm

        def _boom():
            raise RuntimeError("device offline")

        monkeypatch.setattr(cm, "get_current_source_app", _boom)
        monitor.clipboard = MagicMock()
        monitor.clipboard.text.return_value = "content still saved"

        captured = []
        monitor.item_added.connect(lambda it: captured.append(it))

        monitor._handle_text(s)

        assert len(captured) == 1
        assert captured[0].text_content == "content still saved"
        assert captured[0].source_app == ""
        assert captured[0].source_title == ""

    def test_repeated_failure_degraded_to_debug(self, monitor, monkeypatch, caplog):
        """同一异常第二次及以后降级为 DEBUG，不再刷 WARNING。"""
        import logging
        s = _patch_settings(monkeypatch, capture_source_title=False)

        import core.clipboard_monitor as cm

        def _boom():
            raise RuntimeError("still broken")

        monkeypatch.setattr(cm, "get_current_source_app", _boom)
        monitor.clipboard = MagicMock()

        caplog.set_level(logging.DEBUG, logger="core.clipboard_monitor")

        # 第一次调用 → WARNING
        monitor.clipboard.text.return_value = "first"
        monitor._handle_text(s)
        # 第二次调用 → DEBUG（不再 WARNING）
        monitor.clipboard.text.return_value = "second"
        monitor._handle_text(s)

        warning_records = [
            r for r in caplog.records
            if r.name == "core.clipboard_monitor"
            and r.levelno == logging.WARNING
            and "捕获来源 App" in r.getMessage()
        ]
        # 应仅有首次 WARNING
        assert len(warning_records) == 1


# ---------------------------------------------------------------------------
# 图片路径：source_app / source_title 透传到后台线程
# ---------------------------------------------------------------------------


class TestProcessImageBackgroundSourceApp:
    def test_image_item_source_app(self, monitor, monkeypatch):
        """_process_image_background 直接传入 source_app/source_title 时写入 item。"""
        s = _patch_settings(monkeypatch, capture_source_title=True)

        # 构造一张最小的 RGBA 原始字节：2x2 全透明
        width, height = 2, 2
        raw = bytes([0, 0, 0, 0] * (width * height))

        captured = []
        monitor.item_added.connect(lambda it: captured.append(it))

        monitor._process_image_background(
            raw, width, height, s,
            source_app_value="com.example.App",
            source_title_value="Example Window",
        )

        assert len(captured) == 1
        item = captured[0]
        assert item.is_image
        assert item.source_app == "com.example.App"
        assert item.source_title == "Example Window"


# ---------------------------------------------------------------------------
# 配置项：新增字段向后兼容（老 settings.json 无该字段不崩）
# ---------------------------------------------------------------------------


class TestConfigCaptureSourceTitle:
    def test_default_is_false(self):
        from config import AppSettings
        assert AppSettings().capture_source_title is False

    def test_legacy_settings_json_has_no_field(self, tmp_path, monkeypatch):
        """老 settings.json 不含 capture_source_title 时，SettingsStore 读取走默认值。"""
        import json, config
        path = tmp_path / "settings.json"
        # 故意不写 capture_source_title 字段
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "device_id": "legacy",
                "device_name": "Old PC",
                "save_text": True,
            }, f)

        store = config.SettingsStore(path=path)
        snap = store.snapshot()
        assert snap.device_id == "legacy"
        assert snap.capture_source_title is False  # 默认关

    def test_roundtrip_true(self, tmp_path):
        """capture_source_title=True 能被持久化并读回。"""
        import config
        path = tmp_path / "settings.json"
        store = config.SettingsStore(path=path)
        store.update(capture_source_title=True)
        store.flush()

        store2 = config.SettingsStore(path=path)
        snap = store2.snapshot()
        assert snap.capture_source_title is True
