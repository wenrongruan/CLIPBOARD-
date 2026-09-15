"""诊断：macOS 边缘停靠触发逻辑是否成立（不显示任何窗口）。

用法：./venv/bin/python scripts/diag_edge_trigger.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

import ui.edge_window as ew
from config import TRIGGER_ZONE, HIDDEN_MARGIN


class _FakeCursor:
    """模拟鼠标位置。"""
    pos_value = QPoint(0, 0)

    @staticmethod
    def pos():
        return _FakeCursor.pos_value


class _ProbeWindow(ew.EdgeHiddenWindow):
    """禁止真正 show()，只验证触发/几何计算。"""

    def _init_position(self):
        pass

    def show(self):
        pass

    def raise_(self):
        pass

    def setGeometry(self, *a):
        """记录几何，但不真正移动原生窗口。"""
        if a and hasattr(a[0], "x"):
            self._fake_geo = a[0]
            self._fake_geo_value = (a[0].x(), a[0].y(), a[0].width(), a[0].height())
        return super().setGeometry(*a)

    def geometry(self):
        g = getattr(self, "_fake_geo", None)
        return g if g is not None else super().geometry()


def main():
    app = QApplication([])
    screen = app.primaryScreen()
    geo = screen.geometry()
    avail = screen.availableGeometry()
    print(f"screen.geometry()          = {geo.x()},{geo.y()} {geo.width()}x{geo.height()}")
    print(f"screen.availableGeometry() = {avail.x()},{avail.y()} {avail.width()}x{avail.height()}")
    print(f"菜单栏高度={avail.top() - geo.top()}px  Dock/底边内缩={geo.bottom() - avail.bottom()}px")
    print(f"TRIGGER_ZONE={TRIGGER_ZONE}px  HIDDEN_MARGIN={HIDDEN_MARGIN}px")
    print("-" * 72)

    ew.QCursor = _FakeCursor  # 只替换模块级名字，拦截鼠标坐标

    for edge in ("left", "right", "top", "bottom"):
        w = _ProbeWindow()
        w._dock_edge = edge
        w._is_floating = False
        w._is_visible = False
        w._show_protection = False
        w._dragging = False
        w._last_cursor_pos = QPoint(-1, -1)

        zone_rect = w._get_trigger_zone_rect(screen)
        tz = w._get_trigger_zone(zone_rect)
        hidden = w._get_hidden_geometry(avail)
        visible = w._get_visible_geometry(avail)

        # 用户「把鼠标怼到屏幕物理边缘」的坐标
        probe = {
            "left": QPoint(geo.left(), geo.center().y()),
            "right": QPoint(geo.right(), geo.center().y()),
            "top": QPoint(geo.center().x(), geo.top()),
            "bottom": QPoint(geo.center().x(), geo.bottom()),
        }[edge]

        inside = tz.contains(probe)
        _FakeCursor.pos_value = probe
        w._check_mouse_position()
        print(f"[{edge:6}] 物理边缘点={probe.x()},{probe.y()}  触发区="
              f"{tz.x()},{tz.y()} {tz.width()}x{tz.height()}  命中={inside}  "
              f"→ _check_mouse_position 触发显示={w._is_visible}")
        print(f"         隐藏位={hidden.x()},{hidden.y()} {hidden.width()}x{hidden.height()}"
              f"   展开位={visible.x()},{visible.y()} {visible.width()}x{visible.height()}")
    print("-" * 72)
    print("WA_MacAlwaysShowToolWindow =",
          w.testAttribute(ew.Qt.WA_MacAlwaysShowToolWindow))
    print("WA_ShowWithoutActivating   =",
          w.testAttribute(ew.Qt.WA_ShowWithoutActivating))


if __name__ == "__main__":
    main()
