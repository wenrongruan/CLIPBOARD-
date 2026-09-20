"""设置文件在 UI 与后台线程同时更新时保持最后一次快照。"""

import json
import threading

from config import SettingsStore


def test_older_flush_cannot_overwrite_newer_update(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    first_write_started = threading.Event()
    release_first_write = threading.Event()
    second_update_applied = threading.Event()
    original_write = store._write_payload
    original_schedule = store._schedule_save

    def delayed_write(path, data):
        if data["language"] == "en_US":
            first_write_started.set()
            assert release_first_write.wait(timeout=5)
        original_write(path, data)

    def tracked_schedule():
        if store.snapshot().language == "fr_FR":
            second_update_applied.set()
        original_schedule()

    store._write_payload = delayed_write
    store._schedule_save = tracked_schedule

    first = threading.Thread(target=lambda: store.update(language="en_US"))
    second = threading.Thread(target=lambda: store.update(language="fr_FR"))
    try:
        first.start()
        assert first_write_started.wait(timeout=5)
        second.start()
        assert second_update_applied.wait(timeout=5)
        # 无落盘串行化时第二次写入会先完成，随后第一次写入覆盖它。
        # 有串行化时第二线程会等待第一次写入释放。
        second.join(timeout=0.2)
    finally:
        release_first_write.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert store.snapshot().language == "fr_FR"
    assert json.loads((tmp_path / "settings.json").read_text())["language"] == "fr_FR"
    assert store._dirty is False
