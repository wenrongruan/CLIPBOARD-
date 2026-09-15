"""左侧标签栏折叠行为测试。

Why: 折叠看着简单，但有两个容易回归的点 ——
1. 折叠后宽度必须真的落到窄轨道。只动 maximumWidth 会被布局的 sizeHint 钳住
   （折叠时内容已隐藏，sizeHint 会瞬间塌到几像素），表现就是"点了没反应 / 啪地闪一下"；
2. 折叠状态要能跨重启保留，依赖 AppSettings.sidebar_collapsed 的序列化往返。

UI 部分用 offscreen Qt + 合成宿主窗口跑，不依赖真实显示器；
配置持久化部分显式传 path，绝不碰真机 settings.json。
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

# 折叠补间 160ms，留足余量再断言宽度
_ANIM_WAIT_MS = 400


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def persist_calls(monkeypatch):
    """隔离配置：构造期一律当作"上次是展开"，并拦下折叠状态回写。"""
    from ui.sidebar import Sidebar

    calls: list[bool] = []
    monkeypatch.setattr(Sidebar, "_read_saved_collapsed", staticmethod(lambda: False))
    monkeypatch.setattr(
        Sidebar, "_persist_collapsed", staticmethod(lambda collapsed: calls.append(collapsed))
    )
    return calls


@pytest.fixture
def host(qapp, persist_calls):
    """把 Sidebar 放进一个 380px 宽的宿主窗口，模拟真实布局。"""
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    from ui.sidebar import Sidebar
    from ui.styles import MAIN_STYLE

    class _Host(QWidget):
        def __init__(self):
            super().__init__()
            self.setStyleSheet(MAIN_STYLE)
            root = QHBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)
            self.sidebar = Sidebar()
            root.addWidget(self.sidebar)
            root.addWidget(QWidget(), 1)  # 右侧内容区，占满剩余宽度
            self.resize(380, 650)

    w = _Host()
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()


def _wait_animation(qapp, ms: int = _ANIM_WAIT_MS) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    qapp.processEvents()


def test_sidebar_starts_expanded(host):
    from ui.sidebar import EXPANDED_WIDTH

    sb = host.sidebar
    assert sb.is_collapsed() is False
    assert sb.width() == EXPANDED_WIDTH
    assert sb._content.isVisible() is True
    assert sb.header_label.isVisible() is True
    assert sb.collapse_btn.text() == "‹"


def test_collapse_hides_content_and_shrinks_width(host, qapp, persist_calls):
    from ui.sidebar import COLLAPSED_WIDTH

    sb = host.sidebar
    events: list[bool] = []
    sb.collapsed_changed.connect(events.append)

    sb.toggle_collapsed()
    _wait_animation(qapp)

    assert sb.width() == COLLAPSED_WIDTH
    assert sb._content.isVisible() is False
    assert sb.header_label.isVisible() is False
    assert sb.collapse_btn.text() == "›"
    assert events == [True]
    assert persist_calls == [True]


def test_expand_restores_original_width(host, qapp, persist_calls):
    from ui.sidebar import COLLAPSED_WIDTH, EXPANDED_WIDTH

    sb = host.sidebar
    events: list[bool] = []
    sb.collapsed_changed.connect(events.append)

    sb.toggle_collapsed()
    _wait_animation(qapp)
    assert sb.width() == COLLAPSED_WIDTH

    sb.toggle_collapsed()
    _wait_animation(qapp)

    assert sb.width() == EXPANDED_WIDTH
    assert sb._content.isVisible() is True
    assert sb.collapse_btn.text() == "‹"
    assert events == [True, False]
    assert persist_calls == [True, False]


def test_collapse_keeps_selected_tag(host, qapp, persist_calls):
    """折叠只是隐藏面板，标签选中态不能被清掉。"""
    sb = host.sidebar
    assert sb.tag_list.count() >= 1
    sb.tag_list.setCurrentRow(0)
    selected = sb.tag_list.currentRow()

    sb.toggle_collapsed()
    _wait_animation(qapp)
    sb.toggle_collapsed()
    _wait_animation(qapp)

    assert sb.tag_list.currentRow() == selected


def test_set_collapsed_without_animation_is_immediate(host, persist_calls):
    from ui.sidebar import COLLAPSED_WIDTH, EXPANDED_WIDTH

    sb = host.sidebar
    sb.set_collapsed(True, animate=False)
    assert sb.width() == COLLAPSED_WIDTH

    sb.set_collapsed(False, animate=False)
    assert sb.width() == EXPANDED_WIDTH


def test_saved_collapsed_state_is_restored_on_construct(qapp, monkeypatch):
    """构造期读到 sidebar_collapsed=True 时，首帧就落在窄轨道（且不播动画）。"""
    from ui.sidebar import COLLAPSED_WIDTH, Sidebar

    monkeypatch.setattr(Sidebar, "_read_saved_collapsed", staticmethod(lambda: True))
    monkeypatch.setattr(Sidebar, "_persist_collapsed", staticmethod(lambda c: None))

    sb = Sidebar()
    try:
        assert sb.is_collapsed() is True
        assert sb.width() == COLLAPSED_WIDTH
        assert sb._content.isVisible() is False
        assert sb.collapse_btn.text() == "›"
    finally:
        sb.deleteLater()


def test_sidebar_collapsed_round_trips_through_settings_dict():
    """纯函数往返：sidebar_collapsed 必须能写进 settings.json 再读回来。"""
    import config

    snapshot, extras = config._snapshot_from_dict({"sidebar_collapsed": True})
    assert snapshot.sidebar_collapsed is True

    dumped = config._snapshot_to_dict(snapshot, extras)
    assert dumped["sidebar_collapsed"] is True

    again, _ = config._snapshot_from_dict(dumped)
    assert again.sidebar_collapsed is True

    # 老配置里没这个键时按"展开"处理，不能因为缺字段就折叠
    legacy, _ = config._snapshot_from_dict({})
    assert legacy.sidebar_collapsed is False


def test_collapse_persists_through_settings_store(tmp_path):
    """走真实 SettingsStore 的落盘 / 重载（显式传 path，不碰真机配置）。"""
    import config

    path = tmp_path / "settings.json"
    store = config.SettingsStore(path)
    store.update(sidebar_collapsed=True)
    store.flush()
    assert path.exists()

    reloaded = config.SettingsStore(path)
    assert reloaded.snapshot().sidebar_collapsed is True
