"""EdgeHiddenWindow 边缘停靠 / 触发区几何回归测试。

覆盖两个已修复的真实缺陷（macOS，用户报障「设置了停靠位置，移动过去要显示界面，
实际上没有」）：

1. Qt.Tool 在 macOS 上对应 NSPanel，默认 hidesOnDeactivate=YES —— 只要共享剪贴板
   不是当前激活 App，面板就被系统整块隐藏；必须打上 WA_MacAlwaysShowToolWindow。
2. 触发区原先按 availableGeometry 计算，而 macOS 的 availableGeometry 剔掉了菜单栏
   （本机 33px）与 Dock（本机 82px），上/下两条触发带因此悬在屏幕中间，鼠标怼到
   屏幕最上/最下沿反而进不去；右/下端点还内缩 1px，边缘最后一像素不触发。

为避免依赖真实显示器，这里把屏幕与鼠标坐标整体替换成合成对象（QT_QPA_PLATFORM=offscreen）。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

import ui.edge_window as ew

# 合成屏幕：1470x956 物理分辨率，顶部 33px 菜单栏、底部 82px Dock
PHYS = QRect(0, 0, 1470, 956)
AVAIL = QRect(0, 33, 1470, 841)


class _FakeScreen:
    def geometry(self):
        return QRect(PHYS)

    def availableGeometry(self):
        return QRect(AVAIL)


class _FakeApp:
    """替掉 QApplication.screenAt，返回合成屏幕。"""

    def screenAt(self, _pos):
        return _FakeScreen()

    def primaryScreen(self):
        return _FakeScreen()


class _FakeCursor:
    pos_value = QPoint(0, 0)

    @staticmethod
    def pos():
        return _FakeCursor.pos_value


class _ProbeWindow(ew.EdgeHiddenWindow):
    """跳过真实窗口初始化（不 show、不碰真实屏幕）。"""

    def _init_position(self):
        pass


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """把 config 重定向到 tmp，避免读写用户真实 settings.json。"""
    import config

    monkeypatch.setattr(config, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_config_file", lambda: tmp_path / "settings.json")
    store = config.get_store()
    store._path = None
    store._snapshot = None
    store._extras = {}
    store._dirty = False


@pytest.fixture
def env(monkeypatch, qapp):
    """替换屏幕 / 鼠标坐标。"""
    monkeypatch.setattr(ew, "QApplication", _FakeApp())
    monkeypatch.setattr(ew, "QCursor", _FakeCursor)
    return _FakeCursor


def _make_window(edge: str, visible: bool = False) -> _ProbeWindow:
    w = _ProbeWindow()
    w._dock_edge = edge
    w._is_floating = False
    w._is_pinned = False
    w._show_protection = False
    w._dragging = False
    w._is_visible = visible
    w._last_cursor_pos = QPoint(-1, -1)
    w.setGeometry(w._get_hidden_geometry(AVAIL) if not visible
                  else w._get_visible_geometry(AVAIL))
    return w


EDGE_PROBE = {
    "left": QPoint(PHYS.left(), PHYS.center().y()),
    "right": QPoint(PHYS.right(), PHYS.center().y()),
    "top": QPoint(PHYS.center().x(), PHYS.top()),
    "bottom": QPoint(PHYS.center().x(), PHYS.bottom()),
}


# ---------- 1. macOS NSPanel 常显属性 ----------


@pytest.mark.skipif(sys.platform != "darwin", reason="仅 macOS 的 NSPanel 行为")
def test_mac_tool_window_is_always_visible_attr(env):
    w = _make_window("left")
    assert w._is_macos is True
    assert w.testAttribute(Qt.WA_MacAlwaysShowToolWindow) is True
    # 工具窗口标志仍在（不进 Dock / 任务栏）
    assert bool(w.windowFlags() & Qt.Tool)


# ---------- 2. 触发区命中物理边缘 ----------


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_trigger_zone_covers_physical_edge(env, edge):
    w = _make_window(edge)
    if not w._is_macos:  # 非 macOS 沿用 availableGeometry
        pytest.skip("非 macOS 平台触发区仍按 availableGeometry 计算")
    zone = w._get_trigger_zone(w._get_trigger_zone_rect(_FakeScreen()))
    assert zone.contains(EDGE_PROBE[edge]), f"{edge} 物理边缘不在触发区内"


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_mouse_at_physical_edge_slides_in(env, edge):
    w = _make_window(edge)
    env.pos_value = EDGE_PROBE[edge]
    w._check_mouse_position()
    assert w._is_visible is True
    assert w._animation.endValue() == w._get_visible_geometry(AVAIL)


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_zone_end_pixel_is_inclusive(env, edge):
    """边缘最后一像素必须命中（原先内缩 1px，表现为时灵时不灵）。"""
    w = _make_window(edge)
    zone = w._get_trigger_zone(PHYS)
    if edge == "right":
        assert zone.right() == PHYS.right()
    elif edge == "bottom":
        assert zone.bottom() == PHYS.bottom()
    elif edge == "left":
        assert zone.left() == PHYS.left()
    else:
        assert zone.top() == PHYS.top()


def test_trigger_zone_rect_prefers_physical_on_macos(env):
    w = _make_window("left")
    screen = _FakeScreen()
    got = w._get_trigger_zone_rect(screen)
    if w._is_macos:
        assert got == PHYS
    else:
        assert got == AVAIL


# ---------- 3. 不误触发 / 正常隐藏 ----------


def test_mouse_in_screen_center_does_not_trigger(env):
    w = _make_window("left")
    env.pos_value = QPoint(PHYS.center().x(), PHYS.center().y())
    w._check_mouse_position()
    assert w._is_visible is False


def test_leaving_zone_slides_out(env):
    w = _make_window("left", visible=True)
    env.pos_value = QPoint(PHYS.center().x(), PHYS.center().y())
    w._check_mouse_position()
    assert w._is_visible is False
    assert w._animation.endValue() == w._get_hidden_geometry(AVAIL)


def test_pinned_window_does_not_slide_out(env):
    w = _make_window("left", visible=True)
    w._is_pinned = True
    env.pos_value = QPoint(PHYS.center().x(), PHYS.center().y())
    w._check_mouse_position()
    assert w._is_visible is True
