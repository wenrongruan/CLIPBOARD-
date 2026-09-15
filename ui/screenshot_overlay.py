"""非 macOS 平台的区域框选遮罩层。

macOS 走系统 screencapture 自带的选择 UI，不需要这个模块；这里只服务
Windows / Linux（Qt 没有现成的框选控件）。

做法是先抓一张整个虚拟桌面的静态图作为背景（"冻结屏幕"），再让用户在上面
拖矩形——这样遮罩层自己不会被拍进截图里。松开鼠标后按矩形从冻结图上裁剪。

坐标说明：整条链路都在逻辑像素（Qt 的 device-independent pixel）上做，
新建的 QPixmap 默认 devicePixelRatio=1。高 DPI 屏（Windows 150% 缩放）上
框选结果会被按逻辑分辨率裁剪，比原生截图糊一点，但坐标不会错位——
这是刻意取舍，真要求原生分辨率请走 macOS 的 screencapture 路径。
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QDialog

logger = logging.getLogger(__name__)

#: 小于这个尺寸（逻辑像素）视为误触，按取消处理
_MIN_SELECTION_PX = 2

_MASK_COLOR = QColor(0, 0, 0, 110)
_BORDER_COLOR = QColor("#2f9bff")


def _virtual_geometry() -> QRect:
    """所有屏幕的并集，多屏时覆盖整个桌面。"""
    app = QApplication.instance()
    if app is None:
        return QRect()
    geometry = QRect()
    for screen in app.screens():
        geometry = geometry.united(screen.geometry())
    return geometry


def _grab_desktop(geometry: QRect) -> Optional[QPixmap]:
    """把整个虚拟桌面抓成一张静态图。"""
    app = QApplication.instance()
    if app is None or geometry.isEmpty():
        return None
    frozen = QPixmap(geometry.size())
    frozen.fill(Qt.GlobalColor.black)
    painter = QPainter(frozen)
    try:
        origin = geometry.topLeft()
        for screen in app.screens():
            pm = screen.grabWindow(0)
            if pm.isNull():
                continue
            painter.drawPixmap(screen.geometry().topLeft() - origin, pm)
    finally:
        painter.end()
    return frozen


class RegionSelector(QDialog):
    """无边框全屏遮罩：拖出矩形即选中。"""

    def __init__(self, frozen: QPixmap, geometry: QRect, parent=None):
        super().__init__(parent)
        self._frozen = frozen
        self._start = None
        self._current = None
        self._selected: Optional[QPixmap] = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(geometry)

    # ---- 绘制 ----

    def _selection_rect(self) -> Optional[QRect]:
        if self._start is None or self._current is None:
            return None
        return QRect(self._start, self._current).normalized()

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.drawPixmap(0, 0, self._frozen)
            painter.fillRect(self.rect(), _MASK_COLOR)

            rect = self._selection_rect()
            if rect is not None and rect.width() > 0 and rect.height() > 0:
                # 选中区域还原成原始亮度
                painter.drawPixmap(rect, self._frozen, rect)
                pen = QPen(_BORDER_COLOR)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawRect(rect)
        finally:
            painter.end()

    # ---- 交互 ----

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.reject()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        rect = self._selection_rect()
        self._start = self._current = None
        if rect is None or rect.width() < _MIN_SELECTION_PX or rect.height() < _MIN_SELECTION_PX:
            self.reject()
            return
        self._selected = self._frozen.copy(rect)
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def selected_pixmap(self) -> Optional[QPixmap]:
        return self._selected


def select_region(parent=None) -> Optional[QPixmap]:
    """冻结屏幕并弹出框选遮罩，返回裁剪后的图片；取消返回 None。

    必须在 GUI 线程调用。
    """
    geometry = _virtual_geometry()
    if geometry.isEmpty():
        logger.warning("拿不到虚拟桌面尺寸，无法进入区域框选")
        return None
    frozen = _grab_desktop(geometry)
    if frozen is None:
        return None

    selector = RegionSelector(frozen, geometry, parent=parent)
    selector.exec()
    pixmap = selector.selected_pixmap()
    selector.deleteLater()
    return pixmap
