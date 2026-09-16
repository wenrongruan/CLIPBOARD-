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
    if not w._is_macos:
        # 非 macOS 的触发区按 availableGeometry 计算，而 EDGE_PROBE 打的是**物理**
        # 边缘（y = PHYS.top() / PHYS.bottom()）。上/下两条会落在 available 之外
        # （合成屏顶部有 33px 菜单栏、底部 82px Dock），断言必然失败 ——
        # 这是平台语义差异，不是缺陷。与同文件的
        # test_trigger_zone_covers_physical_edge 保持一致的跳过条件。
        pytest.skip("物理边缘触发仅 macOS 生效（非 macOS 触发区按 availableGeometry）")
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


# ---------- 4. 窗口尺寸取真实值而不是 QWidget 默认值 ----------


def test_effective_size_ignores_widget_default_before_layout(env):
    """回归：__init__ 阶段不能拿 self.width()（QWidget 默认 640）当真实宽度。

    本机实测的原始症状：MainWindow 是先 super().__init__()（里面有
    _init_position → _get_hidden_geometry）返回之后才 _setup_ui() 的，
    所以那一刻 self.width() 还是 640。左边缘隐藏位因此算成
    0 - 640 + 3 = -637（正确 -377）：Qt 报
    "Window position QRect(-637,128 640x650) outside any known screen"，
    而且这个离屏坐标会被 Qt 当成锚点，把启动期弹的对话框一起拽到屏幕外。
    """
    w = _ProbeWindow()
    w._dock_edge = "left"
    assert w._laid_out is False
    # 裸 QWidget（还没跑过布局）的 width() 就是 640
    assert w.width() == 640

    assert w._effective_size() == (ew.WINDOW_WIDTH, ew.WINDOW_HEIGHT)

    hidden = w._get_hidden_geometry(AVAIL)
    # 回归点：隐藏位必须按 WINDOW_WIDTH 算，而不是 QWidget 默认的 640。
    #
    # Why 不写死 -377：WINDOW_WIDTH 是**平台相关**的（config.py:88，
    # macOS 380 / 其他平台 350），写死会让 linux/windows CI 算出 -347。
    buggy_left = AVAIL.left() - 640 + ew.HIDDEN_MARGIN  # 拿 QWidget 默认 640 算出的错值
    assert hidden.left() != buggy_left
    assert hidden.left() == AVAIL.left() - ew.WINDOW_WIDTH + ew.HIDDEN_MARGIN
    assert hidden.width() == ew.WINDOW_WIDTH

    visible = w._get_visible_geometry(AVAIL)
    assert visible.left() == AVAIL.left()
    assert visible.width() == ew.WINDOW_WIDTH


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_layout_done_uses_real_size(env, edge):
    """布局跑完后真实尺寸大于配置值时，隐藏位必须按真实宽度算 ——
    否则窗口藏不干净，会在边缘漏出一截（_effective_size 原本要解决的问题）。"""
    w = _ProbeWindow()
    w._dock_edge = edge
    w._laid_out = True
    w.setFixedWidth(480)  # 模拟子控件（侧栏等）把窗口撑大

    width, _ = w._effective_size()
    assert width == 480
    assert w._get_hidden_geometry(AVAIL).width() == 480


def test_correction_skipped_when_size_matches_config(env):
    """尺寸没被撑大时不要重算位置，避免一次可见的跳动。"""
    w = _ProbeWindow()
    w._laid_out = True
    w.setFixedWidth(ew.WINDOW_WIDTH)
    before = QRect(w._get_hidden_geometry(AVAIL))
    w.setGeometry(before)

    w._correct_position_after_layout()
    assert w.geometry() == before


def test_correction_repositions_when_window_grew(env):
    """尺寸被撑大时按真实宽度把隐藏位重算一遍，保证只有 HIDDEN_MARGIN 露出来。"""
    w = _ProbeWindow()
    w._dock_edge = "left"
    w._laid_out = True
    w._is_visible = False
    w.setGeometry(w._get_hidden_geometry(AVAIL))
    w.setFixedWidth(480)  # 模拟布局把窗口撑大

    w._correct_position_after_layout()

    assert w.geometry().width() == 480
    assert w.geometry().right() == AVAIL.left() + ew.HIDDEN_MARGIN - 1


def test_correction_leaves_floating_window_alone(env):
    """悬浮态是用户自己摆的位置，校正逻辑不能碰。"""
    w = _ProbeWindow()
    w._is_floating = True
    w._laid_out = True
    w.setFixedWidth(480)
    w.setGeometry(QRect(120, 200, 480, 480))

    w._correct_position_after_layout()
    assert w.geometry() == QRect(120, 200, 480, 480)
