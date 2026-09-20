"""插件安装清理与 macOS 热键监听器的回归测试。"""

import io
import sys
import types
import zipfile
from pathlib import Path

import pytest

from core.macos_hotkey import MacOSGlobalHotkey
from ui.settings.plugins_tab import _PluginInstallThread


def _archive(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return data.getvalue()


def _run_install(monkeypatch, root, content):
    class Response:
        status_code = 200

    Response.content = content
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: Response())
    worker = _PluginInstallThread("https://example.invalid", "new_plugin", "/download", str(root))
    errors = []
    installed = []
    worker.error.connect(lambda *args: errors.append(args))
    worker.installed.connect(installed.append)
    worker.run()
    return errors, installed


@pytest.mark.parametrize(
    "content",
    [
        b"invalid zip",
        _archive({"../outside.txt": "bad"}),
    ],
)
def test_failed_install_keeps_existing_plugins(monkeypatch, tmp_path, content):
    root = tmp_path / "plugins"
    old = root / "existing_plugin" / "manifest.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")

    errors, installed = _run_install(monkeypatch, root, content)

    assert errors and not installed
    assert old.read_text(encoding="utf-8") == "{}"
    assert not list(tmp_path.glob(".plugin-install-*"))


def test_valid_install_moves_only_selected_plugin(monkeypatch, tmp_path):
    root = tmp_path / "plugins"
    old = root / "existing_plugin" / "manifest.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")
    content = _archive({"new_plugin/manifest.json": '{"id":"new_plugin"}',
                        "new_plugin/plugin.py": "pass"})

    errors, installed = _run_install(monkeypatch, root, content)

    assert errors == []
    assert installed == ["new_plugin"]
    assert old.exists()
    assert (root / "new_plugin" / "plugin.py").read_text() == "pass"
    assert not list(tmp_path.glob(".plugin-install-*"))


def test_install_repairs_broken_target_without_touching_other_plugins(monkeypatch, tmp_path):
    root = tmp_path / "plugins"
    broken = root / "new_plugin" / "manifest.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("broken", encoding="utf-8")
    other = root / "existing_plugin" / "manifest.json"
    other.parent.mkdir()
    other.write_text("other", encoding="utf-8")
    content = _archive({"new_plugin/manifest.json": '{"id":"new_plugin"}',
                        "new_plugin/plugin.py": "repaired"})

    errors, installed = _run_install(monkeypatch, root, content)

    assert errors == []
    assert installed == ["new_plugin"]
    assert (root / "new_plugin" / "plugin.py").read_text() == "repaired"
    assert other.read_text(encoding="utf-8") == "other"
    assert not list(tmp_path.glob(".plugin-backup-*"))


def test_install_restores_target_if_swap_fails(monkeypatch, tmp_path):
    root = tmp_path / "plugins"
    old = root / "new_plugin" / "manifest.json"
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    content = _archive({"new_plugin/manifest.json": '{"id":"new_plugin"}'})
    original_rename = Path.rename

    def fail_staged_rename(path, target):
        if path.name == "new_plugin" and path.parent.name.startswith(".plugin-install-"):
            raise OSError("simulated move failure")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_staged_rename)
    errors, installed = _run_install(monkeypatch, root, content)

    assert errors and not installed
    assert old.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".plugin-backup-*"))


def test_install_accepts_symlinked_temp_parent(monkeypatch, tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("当前平台无法创建目录软链接")
    content = _archive({"new_plugin/manifest.json": '{"id":"new_plugin"}'})

    errors, installed = _run_install(monkeypatch, alias / "plugins", content)

    assert errors == []
    assert installed == ["new_plugin"]
    assert (actual / "plugins" / "new_plugin" / "manifest.json").exists()


def test_install_rejects_archive_for_other_plugin(monkeypatch, tmp_path):
    root = tmp_path / "plugins"
    old = root / "existing_plugin" / "manifest.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")

    errors, installed = _run_install(
        monkeypatch, root, _archive({"existing_plugin/plugin.py": "overwrite"})
    )

    assert errors and not installed
    assert old.exists()
    assert not (root / "existing_plugin" / "plugin.py").exists()


def test_download_failure_keeps_existing_plugins(monkeypatch, tmp_path):
    root = tmp_path / "plugins"
    old = root / "existing_plugin" / "manifest.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")

    def fail_download(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("httpx.get", fail_download)
    worker = _PluginInstallThread("https://example.invalid", "new_plugin", "/download", str(root))
    errors = []
    worker.error.connect(lambda *args: errors.append(args))
    worker.run()

    assert errors == [("new_plugin", "network down")]
    assert old.exists()


def _fake_appkit(monkeypatch, *, global_result, local_result):
    class Event:
        local_calls = 0
        removed = []

        @classmethod
        def addGlobalMonitorForEventsMatchingMask_handler_(cls, _mask, _handler):
            return global_result

        @classmethod
        def addLocalMonitorForEventsMatchingMask_handler_(cls, _mask, _handler):
            cls.local_calls += 1
            if isinstance(local_result, Exception):
                raise local_result
            return local_result

        @classmethod
        def removeMonitor_(cls, monitor):
            cls.removed.append(monitor)

    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(
        NSEvent=Event, NSEventMaskKeyDown=1
    ))
    return Event


def test_macos_hotkey_does_not_install_local_monitor_without_global(monkeypatch):
    event = _fake_appkit(monkeypatch, global_result=None, local_result=object())
    hotkey = MacOSGlobalHotkey("<cmd>+v", lambda: None)

    assert hotkey.start() is False
    assert event.local_calls == 0
    assert hotkey.running is False


def test_macos_hotkey_removes_global_monitor_when_local_fails(monkeypatch):
    global_monitor = object()
    event = _fake_appkit(monkeypatch, global_result=global_monitor, local_result=None)
    hotkey = MacOSGlobalHotkey("<cmd>+v", lambda: None)

    assert hotkey.start() is False
    assert event.removed == [global_monitor]
    assert hotkey.running is False


def test_macos_hotkey_removes_global_monitor_on_local_exception(monkeypatch):
    global_monitor = object()
    event = _fake_appkit(
        monkeypatch, global_result=global_monitor, local_result=RuntimeError("monitor failed")
    )
    hotkey = MacOSGlobalHotkey("<cmd>+v", lambda: None)

    with pytest.raises(RuntimeError, match="monitor failed"):
        hotkey.start()
    assert event.removed == [global_monitor]
    assert hotkey.running is False
