"""启动期对话框的两条回归。

都来自本机 mac 版调试（`./run.sh` 起不来 / 起来了也没反应）：

1. 首启引导每次启动都会弹：`ui/main_window.py` 写的是
   `getattr(settings, "onboarding_done", False)`，而 `config.settings` 是个**函数**，
   取函数对象上的属性永远拿到默认值 False —— 判断等于恒真。
2. 引导框/权限框整块落在屏幕外：停靠窗不在用时被停在屏幕外（左边缘隐藏位
   x = -WINDOW_WIDTH + 3 = -377），Qt 会拿它当锚点给新对话框算位置，
   实测两个框都落到了 QRect(-546,303 460x300) / QRect(-416,303 460x300)。
   所以必须显式摆到主屏正中（ui/dialog_utils.center_on_primary_screen）。
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from ui.dialog_utils import center_on_primary_screen


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """把 config 重定向到 tmp，避免读写真机 settings.json。"""
    import config

    monkeypatch.setattr(config, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_config_file", lambda: tmp_path / "settings.json")
    store = config.get_store()
    store._path = None
    store._snapshot = None
    store._extras = {}
    store._dirty = False


# ---------- center_on_primary_screen ----------


def test_dialog_lands_inside_primary_screen(qapp):
    screen = QApplication.primaryScreen()
    assert screen is not None, "offscreen 平台也应提供一个主屏"
    area = screen.availableGeometry()

    dlg = QDialog()
    dlg.setFixedSize(300, 200)
    center_on_primary_screen(dlg)

    got = dlg.geometry()
    assert got.size().width() == 300 and got.size().height() == 200
    # 关键断言：整块都在屏幕可用区内（修好之前是整块在屏幕外）
    assert area.contains(got), f"{got} 不在主屏可用区 {area} 内"


def test_dialog_is_horizontally_and_vertically_centered(qapp):
    area = QApplication.primaryScreen().availableGeometry()

    dlg = QDialog()
    dlg.setFixedSize(300, 200)
    center_on_primary_screen(dlg)

    got = dlg.geometry()
    assert got.left() == area.left() + (area.width() - 300) // 2
    assert got.top() == area.top() + (area.height() - 200) // 2


def test_oversized_dialog_is_clamped_to_screen(qapp):
    """比屏幕还大的对话框要按可用区裁剪，不能一半露在屏幕外。"""
    area = QApplication.primaryScreen().availableGeometry()

    dlg = QDialog()
    dlg.setFixedSize(area.width() + 400, area.height() + 400)
    center_on_primary_screen(dlg)

    # 尺寸是控件自己定的（我们只负责摆位），但左上角必须落在可用区内
    got = dlg.geometry()
    assert area.contains(got.topLeft())


# ---------- 首启引导是否会被重复弹出 ----------


class _StubWindow(QWidget):
    """只需要 _maybe_show_onboarding 用到的两样东西。"""

    def __init__(self):
        super().__init__()
        self._onboarding_dialog = None

    def _on_onboarding_done(self):
        self._onboarding_dialog = None


def _run_maybe_show_onboarding(monkeypatch, *, done: bool):
    import ui.main_window as mw

    monkeypatch.setattr(
        mw, "settings", lambda: SimpleNamespace(onboarding_done=done)
    )
    win = _StubWindow()
    mw.MainWindow._maybe_show_onboarding(win)
    return win


def test_onboarding_shown_when_not_done(monkeypatch, qapp):
    win = _run_maybe_show_onboarding(monkeypatch, done=False)
    assert win._onboarding_dialog is not None, "没引导过就应该弹"
    win._onboarding_dialog.close()


def test_onboarding_not_shown_when_already_done(monkeypatch, qapp):
    """回归：settings 是函数，必须调用；写成 getattr(settings, ...) 会永远当没引导过。"""
    win = _run_maybe_show_onboarding(monkeypatch, done=True)
    assert win._onboarding_dialog is None, "已经引导过就不该再弹"


def test_onboarding_dialog_is_positioned_on_screen(monkeypatch, qapp):
    """父窗口停在屏幕外，引导框也必须摆到屏幕里（否则等于没弹）。"""
    win = _run_maybe_show_onboarding(monkeypatch, done=False)
    dlg = win._onboarding_dialog
    assert dlg is not None

    area = QApplication.primaryScreen().availableGeometry()
    assert area.intersects(QRect(dlg.geometry())), (
        f"引导框 {dlg.geometry()} 与主屏可用区 {area} 没有交集"
    )
    dlg.close()
