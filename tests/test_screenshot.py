"""截图功能测试。

覆盖四块：
1. 配置：截图热键默认值 / 持久化 / 老 settings.json 向后兼容
2. macOS screencapture 的参数拼装与「取消 → None」语义
   （不真的调系统截图，避免在跑测试时打扰用户）
3. ClipboardMonitor.persist_image_bytes 的入库链路（去重 / 大小限制 / item_added）
4. ScreenshotService 的降级行为与「取景 → 入库 → 复制」主链路
"""

from __future__ import annotations

import io
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

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
def isolated_config(tmp_path, monkeypatch):
    """把 config 的落盘目录重定向到 tmp_path，避免测试写用户真实 settings.json。"""
    import config

    monkeypatch.setattr(config, "get_config_dir", lambda: tmp_path, raising=False)
    monkeypatch.setattr(
        config, "get_config_file", lambda: tmp_path / "settings.json", raising=False
    )
    store = config.get_store()
    monkeypatch.setattr(store, "_path", None, raising=False)
    monkeypatch.setattr(store, "_snapshot", None, raising=False)
    monkeypatch.setattr(store, "_extras", {}, raising=False)
    monkeypatch.setattr(store, "_dirty", False, raising=False)
    return store


def _png_bytes(size=(8, 6), noise: bool = False) -> bytes:
    from PIL import Image

    if noise:
        raw = os.urandom(size[0] * size[1] * 3)
        image = Image.frombytes("RGB", size, raw)
    else:
        image = Image.new("RGB", size, (255, 0, 0))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class _RecordingMonitor:
    """ClipboardMonitor 的最小替身：只记录 persist / copy 调用。"""

    def __init__(self, persist_result=True):
        self.persisted: list = []
        self.copied: list = []
        self._persist_result = persist_result

    def persist_image_bytes(
        self, data, *, source_app="", source_title="", preview_prefix="图片"
    ):
        from core.models import ImageClipboardItem

        self.persisted.append((data, source_app, preview_prefix))
        if not self._persist_result:
            return None
        item = ImageClipboardItem(image_data=data, preview=f"[{preview_prefix}]")
        item.id = 1
        return item

    def copy_to_clipboard(self, item) -> bool:
        self.copied.append(item)
        return True


# ---------------------------------------------------------------------------
# 1. 配置
# ---------------------------------------------------------------------------


class TestScreenshotConfig:
    def test_default_hotkey_is_platform_specific(self, monkeypatch):
        import config

        monkeypatch.setattr(config, "IS_MACOS", True)
        assert config.get_default_screenshot_hotkey() == "<cmd>+<shift>+a"
        monkeypatch.setattr(config, "IS_MACOS", False)
        assert config.get_default_screenshot_hotkey() == "<ctrl>+<shift>+a"

    def test_default_hotkeys_do_not_collide(self, monkeypatch):
        """两个默认热键必须不同，否则注册时后者会被顶掉。"""
        import config

        for is_mac in (True, False):
            monkeypatch.setattr(config, "IS_MACOS", is_mac)
            assert config.get_default_screenshot_hotkey() != config.get_default_hotkey()

    def test_effective_hotkey_falls_back_to_default(self, monkeypatch):
        import config
        from config import AppSettings

        monkeypatch.setattr(config, "IS_MACOS", True)
        monkeypatch.setattr(config, "settings", lambda: AppSettings(screenshot_hotkey=""))
        assert config.get_effective_screenshot_hotkey() == "<cmd>+<shift>+a"

        monkeypatch.setattr(
            config, "settings", lambda: AppSettings(screenshot_hotkey="<ctrl>+9")
        )
        assert config.get_effective_screenshot_hotkey() == "<ctrl>+9"

    def test_defaults(self):
        from config import AppSettings

        snap = AppSettings()
        assert snap.screenshot_hotkey == ""
        assert snap.screenshot_copy_to_clipboard is True

    def test_roundtrip(self, tmp_path):
        import config

        path = tmp_path / "settings.json"
        store = config.SettingsStore(path=path)
        store.update(screenshot_hotkey="<cmd>+<shift>+9", screenshot_copy_to_clipboard=False)
        store.flush()

        snap = config.SettingsStore(path=path).snapshot()
        assert snap.screenshot_hotkey == "<cmd>+<shift>+9"
        assert snap.screenshot_copy_to_clipboard is False

    def test_legacy_settings_json_without_fields(self, tmp_path):
        """老 settings.json 没有截图字段时走默认值，不抛异常。"""
        import config

        path = tmp_path / "settings.json"
        path.write_text('{"device_id": "legacy", "device_name": "Old PC"}', encoding="utf-8")

        snap = config.SettingsStore(path=path).snapshot()
        assert snap.device_id == "legacy"
        assert snap.screenshot_hotkey == ""
        assert snap.screenshot_copy_to_clipboard is True


# ---------------------------------------------------------------------------
# 2. macOS screencapture 封装
# ---------------------------------------------------------------------------


class TestMacosCapture:
    def test_region_args(self):
        import core.screenshot_service as ss

        args = ss.build_macos_args(ss.REGION, "/tmp/x.png")
        assert args[0] == "/usr/sbin/screencapture"
        assert args[-1] == "/tmp/x.png"
        assert "-x" in args
        assert "-i" in args
        # -s：只允许鼠标框选，空格不再切到窗口模式（窗口已是独立入口）
        assert "-s" in args
        assert "-w" not in args and "-m" not in args

    def test_window_args(self):
        import core.screenshot_service as ss

        args = ss.build_macos_args(ss.WINDOW, "/tmp/x.png")
        assert "-i" in args and "-w" in args
        # -o：窗口截图不带阴影
        assert "-o" in args
        assert "-s" not in args and "-m" not in args

    def test_full_args(self):
        import core.screenshot_service as ss

        args = ss.build_macos_args(ss.FULL, "/tmp/x.png")
        # -m：只截主显示器；全屏不该是交互式
        assert "-m" in args
        assert "-i" not in args

    def test_cancel_returns_none(self, monkeypatch):
        """用户按 Esc：screencapture 返回非 0 且不写文件 → None（取消不是错误）。"""
        import core.screenshot_service as ss

        class _Proc:
            returncode = 1
            stdout = b""
            stderr = b""

        monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _Proc())
        assert ss.capture_macos(ss.REGION) is None

    def test_success_reads_png(self, monkeypatch):
        import core.screenshot_service as ss

        payload = b"\x89PNG\r\n\x1a\nfakepayload"

        class _Proc:
            returncode = 0
            stdout = b""
            stderr = b""

        def _fake_run(args, capture_output=True, timeout=None):
            with open(args[-1], "wb") as f:
                f.write(payload)
            return _Proc()

        monkeypatch.setattr(ss.subprocess, "run", _fake_run)
        assert ss.capture_macos(ss.FULL) == payload

    def test_timeout_returns_none(self, monkeypatch):
        import core.screenshot_service as ss

        def _boom(*a, **k):
            raise ss.subprocess.TimeoutExpired(cmd="screencapture", timeout=1)

        monkeypatch.setattr(ss.subprocess, "run", _boom)
        assert ss.capture_macos(ss.FULL) is None

    def test_exception_returns_none(self, monkeypatch):
        import core.screenshot_service as ss

        def _boom(*a, **k):
            raise OSError("no such file")

        monkeypatch.setattr(ss.subprocess, "run", _boom)
        assert ss.capture_macos(ss.WINDOW) is None

    def test_permission_probe_defaults_true_when_unavailable(self, monkeypatch):
        """Quartz 不可用（非 macOS / 缺 pyobjc）时必须放行，不能把功能整条挡死。"""
        import core.screenshot_service as ss

        monkeypatch.setattr(ss, "IS_MACOS", False)
        assert ss.has_screen_recording_permission() is True
        assert ss.request_screen_recording_permission() is True


# ---------------------------------------------------------------------------
# 3. ClipboardMonitor.persist_image_bytes
# ---------------------------------------------------------------------------


@pytest.fixture
def monitor_env(qapp, tmp_path, monkeypatch):
    """真实 DB + 真实 Repository 的 ClipboardMonitor，settings 换成定制 snapshot。"""
    import core.clipboard_monitor as cm
    from config import AppSettings
    from core.clipboard_monitor import ClipboardMonitor
    from core.database import DatabaseManager
    from core.repository import ClipboardRepository

    snap = AppSettings(
        device_id="dev-1",
        device_name="Tester",
        save_text=True,
        save_images=True,
        max_items=100,
        retention_days=0,
        max_image_size_kb=0,
    )
    monkeypatch.setattr(cm, "settings", lambda: snap)

    db = DatabaseManager(str(tmp_path / "shots.db"))
    repo = ClipboardRepository(db)
    monitor = ClipboardMonitor(repo)
    yield monitor, repo, snap
    monitor.stop()
    db.close()


class TestPersistImageBytes:
    def test_creates_item_and_emits(self, monitor_env):
        monitor, repo, _ = monitor_env
        captured = []
        monitor.item_added.connect(lambda item: captured.append(item))

        data = _png_bytes(size=(8, 6))
        item = monitor.persist_image_bytes(
            data, source_app="screenshot", preview_prefix="截图"
        )

        assert item is not None
        assert item.is_image
        assert item.id
        assert item.source_app == "screenshot"
        # 预览里带上尺寸，方便在历史列表里一眼分辨
        assert item.preview == "[截图 8x6]"
        assert len(captured) == 1
        assert captured[0].id == item.id

        items, total = repo.get_items(page=0, page_size=10)
        assert total == 1
        assert items[0].content_hash == item.content_hash

    def test_thumbnail_generated(self, monitor_env):
        monitor, _, _ = monitor_env
        item = monitor.persist_image_bytes(_png_bytes(size=(400, 300)))
        assert item is not None
        assert item.image_thumbnail
        from utils.image_utils import create_thumbnail

        assert create_thumbnail(item.image_thumbnail)  # 缩略图本身可解码

    def test_duplicate_touches_existing_instead_of_inserting(self, monitor_env):
        monitor, repo, _ = monitor_env
        data = _png_bytes(size=(8, 6))

        first = monitor.persist_image_bytes(data)
        second = monitor.persist_image_bytes(data)

        assert first is not None and second is not None
        assert second.id == first.id
        _, total = repo.get_items(page=0, page_size=10)
        assert total == 1

    def test_size_limit_returns_none(self, monitor_env, monkeypatch):
        monitor, repo, snap = monitor_env
        import core.clipboard_monitor as cm

        monkeypatch.setattr(cm, "settings", lambda: replace(snap, max_image_size_kb=1))
        data = _png_bytes(size=(400, 400), noise=True)
        assert len(data) > 1024

        assert monitor.persist_image_bytes(data) is None
        _, total = repo.get_items(page=0, page_size=10)
        assert total == 0

    def test_preview_prefix_default(self, monitor_env):
        monitor, _, _ = monitor_env
        item = monitor.persist_image_bytes(_png_bytes(size=(5, 4)))
        assert item is not None
        assert item.preview == "[图片 5x4]"


# ---------------------------------------------------------------------------
# 4. ScreenshotService
# ---------------------------------------------------------------------------


def _pump_until(qapp, predicate, timeout=5.0):
    """等后台线程通过 QueuedConnection 把结果送回主线程。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


class TestScreenshotService:
    def test_unknown_mode_rejected(self, qapp):
        import core.screenshot_service as ss

        service = ss.ScreenshotService(_RecordingMonitor())
        errors = []
        service.capture_failed.connect(errors.append)

        assert service.capture("nope") is False
        assert errors

    def test_missing_monitor_fails_gracefully(self, qapp):
        import core.screenshot_service as ss

        service = ss.ScreenshotService(None)
        errors = []
        service.capture_failed.connect(errors.append)

        assert service.capture(ss.FULL) is False
        assert errors

    def test_permission_required_emits_and_skips(self, qapp, monkeypatch):
        import core.screenshot_service as ss

        monkeypatch.setattr(ss, "has_screen_recording_permission", lambda: False)
        service = ss.ScreenshotService(_RecordingMonitor())
        fired = []
        service.permission_required.connect(lambda: fired.append(True))

        assert service.capture(ss.REGION) is False
        assert fired == [True]
        assert service.is_busy() is False

    def test_busy_guard_drops_second_request(self, qapp, monkeypatch):
        """框选途中再按热键不应叠加第二个截图。"""
        import core.screenshot_service as ss

        monkeypatch.setattr(ss, "IS_MACOS", True)
        monkeypatch.setattr(ss, "has_screen_recording_permission", lambda: True)

        release = []

        def _slow_capture(mode):
            while not release:
                time.sleep(0.01)
            return b"png"

        monkeypatch.setattr(ss, "capture_macos", _slow_capture)
        service = ss.ScreenshotService(_RecordingMonitor())

        assert service.capture(ss.REGION) is True
        assert service.is_busy() is True
        assert service.capture(ss.REGION) is False  # 被 busy 守卫挡下

        release.append(True)
        assert _pump_until(qapp, lambda: not service.is_busy())

    def test_cancel_resets_state_without_notification(self, qapp, monkeypatch):
        """用户取消：不弹任何提示，但必须复位 busy。"""
        import core.screenshot_service as ss

        monkeypatch.setattr(ss, "IS_MACOS", True)
        monkeypatch.setattr(ss, "has_screen_recording_permission", lambda: True)
        monkeypatch.setattr(ss, "capture_macos", lambda mode: None)

        service = ss.ScreenshotService(_RecordingMonitor())
        saved, errors = [], []
        service.item_saved.connect(saved.append)
        service.capture_failed.connect(errors.append)

        assert service.capture(ss.REGION) is True
        assert _pump_until(qapp, lambda: not service.is_busy())
        assert saved == [] and errors == []

    def test_macos_happy_path_saves_and_copies(self, qapp, monkeypatch, isolated_config):
        """端到端（不真的截屏）：取景 → 入库 → 主线程复制到剪贴板。"""
        import core.screenshot_service as ss

        monkeypatch.setattr(ss, "IS_MACOS", True)
        monkeypatch.setattr(ss, "has_screen_recording_permission", lambda: True)
        monkeypatch.setattr(ss, "capture_macos", lambda mode: b"png-bytes")

        monitor = _RecordingMonitor()
        service = ss.ScreenshotService(monitor)
        saved = []
        service.item_saved.connect(saved.append)

        assert service.capture(ss.FULL) is True
        assert _pump_until(qapp, lambda: bool(saved))

        assert len(saved) == 1
        assert monitor.persisted == [(b"png-bytes", "screenshot", "截图")]
        assert len(monitor.copied) == 1
        assert service.is_busy() is False

    def test_copy_skipped_when_setting_off(self, qapp, monkeypatch, isolated_config):
        import core.screenshot_service as ss
        from config import update_settings

        update_settings(screenshot_copy_to_clipboard=False)

        monkeypatch.setattr(ss, "IS_MACOS", True)
        monkeypatch.setattr(ss, "has_screen_recording_permission", lambda: True)
        monkeypatch.setattr(ss, "capture_macos", lambda mode: b"png-bytes")

        monitor = _RecordingMonitor()
        service = ss.ScreenshotService(monitor)
        saved = []
        service.item_saved.connect(saved.append)

        service.capture(ss.WINDOW)
        assert _pump_until(qapp, lambda: bool(saved))

        assert len(saved) == 1
        assert monitor.persisted  # 仍然入库
        assert monitor.copied == []  # 但不碰系统剪贴板

    def test_persist_none_reports_too_large(self, qapp, monkeypatch):
        import core.screenshot_service as ss

        monkeypatch.setattr(ss, "IS_MACOS", True)
        monkeypatch.setattr(ss, "has_screen_recording_permission", lambda: True)
        monkeypatch.setattr(ss, "capture_macos", lambda mode: b"png-bytes")

        service = ss.ScreenshotService(_RecordingMonitor(persist_result=False))
        errors = []
        service.capture_failed.connect(errors.append)

        service.capture(ss.FULL)
        assert _pump_until(qapp, lambda: bool(errors))
        assert "过大" in errors[0] or "large" in errors[0].lower()

    def test_slots_dispatch_by_mode(self, qapp, monkeypatch):
        """托盘菜单用的无参槽必须落到对应的取景模式上。"""
        import core.screenshot_service as ss

        seen = []
        monkeypatch.setattr(ss, "has_screen_recording_permission", lambda: True)
        monkeypatch.setattr(
            ss.ScreenshotService,
            "capture",
            lambda self, mode=ss.REGION: seen.append(mode) or True,
        )

        service = ss.ScreenshotService(_RecordingMonitor())
        service.capture_region()
        service.capture_full()
        service.capture_window()
        assert seen == [ss.REGION, ss.FULL, ss.WINDOW]


# ---------------------------------------------------------------------------
# 5. i18n
# ---------------------------------------------------------------------------


class TestScreenshotI18n:
    _EXTRA_KEYS = ("open_system_settings",)

    def test_all_languages_have_screenshot_keys(self):
        import i18n

        zh = i18n.TRANSLATIONS["zh_CN"]
        keys = [k for k in zh if k == "screenshot" or k.startswith("screenshot_")]
        keys += [k for k in self._EXTRA_KEYS if k in zh]
        assert len(keys) >= 10

        for lang, table in i18n.TRANSLATIONS.items():
            missing = sorted(k for k in keys if k not in table)
            assert not missing, f"{lang} 缺失截图文案: {missing}"

    def test_t_returns_non_empty(self):
        import i18n

        original = i18n.get_language()
        try:
            for lang in i18n.TRANSLATIONS:
                i18n.set_language(lang)
                for key in (
                    "screenshot",
                    "screenshot_region",
                    "screenshot_full",
                    "screenshot_window",
                    "screenshot_saved",
                    "screenshot_hotkey",
                    "screenshot_permission_title",
                ):
                    assert i18n.t(key) not in ("", key)
        finally:
            i18n.set_language(original)
