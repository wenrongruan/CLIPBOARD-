"""对话框摆位的小工具。

为什么需要它
------------
这个应用的主窗口是个「边缘停靠窗」：不用的时候被主动停在**屏幕外**
（左边缘的隐藏位 x = -WINDOW_WIDTH + 3，本机实测 -377）。这是有意的，
但带来一个副作用 —— Qt 会拿「当前窗口」当锚点给新对话框算位置，
而启动期唯一存在的窗口就是这个停在屏幕外的停靠窗，于是新弹的框跟着
一起落到屏幕外。Qt 只往 stderr 丢一句
    qt.qpa.window: Window position QRect(...) outside any known screen
用户则什么都看不到。

本机实测过的两例：
- 输入监控权限引导框 → QRect(-546,303 460x300)（整块在屏幕外）
- 首启 3 步引导框   → QRect(-416,303 460x300)（整块在屏幕外）

所以凡是"用户必须看到"的对话框，show 之前都显式摆到主屏可用区正中。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def center_on_primary_screen(dialog) -> None:
    """把对话框摆到主屏可用区正中（要在 show()/open() 之前调用）。

    尺寸优先取 sizeHint()（QMessageBox 和带布局的对话框都能算出来）；
    返回无效尺寸时退回控件当前尺寸（setFixedSize 过的裸 QDialog 就是这种）。
    尺寸按主屏可用区裁剪，保证整块都落在可见范围内。
    拿不到屏幕（无 GUI 会话）时静默跳过。
    """
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return
    area = screen.availableGeometry()

    size = dialog.sizeHint()
    if not size.isValid() or size.isEmpty():
        size = dialog.size()
    width = min(max(size.width(), 0), area.width())
    height = min(max(size.height(), 0), area.height())
    dialog.move(
        area.left() + max((area.width() - width) // 2, 0),
        area.top() + max((area.height() - height) // 2, 0),
    )


__all__ = ["center_on_primary_screen"]
