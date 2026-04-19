import platform
from typing import Optional

from PySide6.QtCore import Qt, QRect, QPropertyAnimation, QEasingCurve, QTimer, QPoint, Slot
from PySide6.QtGui import QCursor, QScreen, QMouseEvent
from PySide6.QtWidgets import QWidget, QApplication

from config import (
    settings,
    update_settings,
    set_dock_edge as set_dock_edge_config,
    WINDOW_WIDTH,
    WINDOW_HEIGHT,
    HIDDEN_MARGIN,
    TRIGGER_ZONE,
    ANIMATION_DURATION,
)


class EdgeHiddenWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._is_macos = platform.system() == "Darwin"

        # 窗口设置 - macOS 需要不同的窗口标志
        if self._is_macos:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.NoDropShadowWindowHint  # macOS 上避免阴影问题
            )
            # macOS 下关闭透明背景, 避免内容未绘制时桌面穿透
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            # 切换 Space 时不抢焦点
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool  # 不在任务栏显示
            )
            self.setAttribute(Qt.WA_TranslucentBackground, False)

        # 尺寸配置
        self._window_width = WINDOW_WIDTH
        self._window_height = WINDOW_HEIGHT
        self._hidden_margin = HIDDEN_MARGIN
        self._trigger_zone = TRIGGER_ZONE

        # 停靠边缘 / 悬浮态
        s = settings()
        self._dock_edge = s.dock_edge

        # 动画
        self._animation = QPropertyAnimation(self, b"geometry")
        self._animation.setDuration(ANIMATION_DURATION)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

        # 状态
        self._is_visible = False
        self._is_pinned = False  # 固定模式，不自动隐藏
        self._show_protection = False  # 显示保护期，防止立即隐藏

        # 悬浮模式（脱离边缘吸附，自由定位）
        self._is_floating = s.is_floating

        # 拖动支持
        self._dragging = False
        self._drag_start_pos = QPoint()
        self._drag_start_geometry = QRect()
        self._last_cursor_pos = QPoint(-1, -1)

        # 鼠标位置检测定时器
        self._mouse_check_timer = QTimer(self)
        self._mouse_check_timer.timeout.connect(self._check_mouse_position)
        self._mouse_check_timer.start(200)  # 初始隐藏状态，低频检测

        # 显示保护定时器
        self._protection_timer = QTimer(self)
        self._protection_timer.setSingleShot(True)
        self._protection_timer.timeout.connect(self._end_show_protection)

        # 初始化位置
        self._init_position()

    def _init_position(self):
        screen_rect = self._get_screen_rect()
        if screen_rect.isEmpty():
            return

        if self._is_floating:
            pos = settings().floating_position
            if pos and len(pos) == 2:
                x, y = pos
                if QApplication.screenAt(QPoint(x, y)):
                    self.setGeometry(QRect(x, y, self._window_width, self._window_height))
                    self._is_visible = True
                    self._is_pinned = True
                    self.show()
                    return
            # 保存的位置无效，回退到吸附模式
            self._is_floating = False
            update_settings(is_floating=False)

        self._move_to_hidden_position(screen_rect)
        self.show()

    def _get_screen(self) -> Optional[QScreen]:
        """当前屏幕：窗口可见/悬浮时用窗口中心所在屏幕，否则用鼠标所在屏幕"""
        if self._is_visible or self._is_floating:
            screen = QApplication.screenAt(self.geometry().center())
            if screen:
                return screen
        return QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()

    def _get_screen_rect(self) -> QRect:
        """获取可用屏幕区域，macOS 上排除菜单栏和 Dock"""
        screen = self._get_screen()
        if not screen:
            return QRect()
        # macOS 使用 availableGeometry 排除菜单栏和 Dock
        # Windows 也可以使用，会排除任务栏
        return screen.availableGeometry()

    def set_dock_edge(self, edge: str):
        if edge in ("left", "right", "top", "bottom"):
            self._dock_edge = edge
            self._is_floating = False
            update_settings(is_floating=False)
            set_dock_edge_config(edge)
            # 重新定位
            screen_rect = self._get_screen_rect()
            if not screen_rect.isEmpty():
                if self._is_visible:
                    self._move_to_visible_position(screen_rect)
                else:
                    self._move_to_hidden_position(screen_rect)

    def toggle_pin(self):
        self._is_pinned = not self._is_pinned
        return self._is_pinned

    def _get_trigger_zone(self, screen_rect: QRect) -> QRect:
        zone = self._trigger_zone

        if self._dock_edge == "right":
            return QRect(
                screen_rect.right() - zone,
                screen_rect.top(),
                zone,
                screen_rect.height(),
            )
        elif self._dock_edge == "left":
            return QRect(
                screen_rect.left(),
                screen_rect.top(),
                zone,
                screen_rect.height(),
            )
        elif self._dock_edge == "top":
            return QRect(
                screen_rect.left(),
                screen_rect.top(),
                screen_rect.width(),
                zone,
            )
        else:  # bottom
            return QRect(
                screen_rect.left(),
                screen_rect.bottom() - zone,
                screen_rect.width(),
                zone,
            )

    def _get_hidden_geometry(self, screen_rect: QRect) -> QRect:
        margin = self._hidden_margin

        if self._dock_edge == "right":
            return QRect(
                screen_rect.right() - margin,
                (screen_rect.height() - self._window_height) // 2 + screen_rect.top(),
                self._window_width,
                self._window_height,
            )
        elif self._dock_edge == "left":
            return QRect(
                screen_rect.left() - self._window_width + margin,
                (screen_rect.height() - self._window_height) // 2 + screen_rect.top(),
                self._window_width,
                self._window_height,
            )
        elif self._dock_edge == "top":
            return QRect(
                (screen_rect.width() - self._window_width) // 2 + screen_rect.left(),
                screen_rect.top() - self._window_height + margin,
                self._window_width,
                self._window_height,
            )
        else:  # bottom
            return QRect(
                (screen_rect.width() - self._window_width) // 2 + screen_rect.left(),
                screen_rect.bottom() - margin,
                self._window_width,
                self._window_height,
            )

    def _get_visible_geometry(self, screen_rect: QRect) -> QRect:
        if self._dock_edge == "right":
            return QRect(
                screen_rect.right() - self._window_width,
                (screen_rect.height() - self._window_height) // 2 + screen_rect.top(),
                self._window_width,
                self._window_height,
            )
        elif self._dock_edge == "left":
            return QRect(
                screen_rect.left(),
                (screen_rect.height() - self._window_height) // 2 + screen_rect.top(),
                self._window_width,
                self._window_height,
            )
        elif self._dock_edge == "top":
            return QRect(
                (screen_rect.width() - self._window_width) // 2 + screen_rect.left(),
                screen_rect.top(),
                self._window_width,
                self._window_height,
            )
        else:  # bottom
            return QRect(
                (screen_rect.width() - self._window_width) // 2 + screen_rect.left(),
                screen_rect.bottom() - self._window_height,
                self._window_width,
                self._window_height,
            )

    def _move_to_hidden_position(self, screen_rect: QRect):
        self.setGeometry(self._get_hidden_geometry(screen_rect))

    def _move_to_visible_position(self, screen_rect: QRect):
        self.setGeometry(self._get_visible_geometry(screen_rect))

    def _check_mouse_position(self):
        # 拖动中不做边缘检测，否则会被定时器拉回停靠位置
        if self._dragging or self._is_floating or self._show_protection:
            return

        cursor_pos = QCursor.pos()
        if cursor_pos == self._last_cursor_pos:
            return
        self._last_cursor_pos = cursor_pos

        cursor_screen = QApplication.screenAt(cursor_pos)
        if not cursor_screen:
            return
        cursor_screen_rect = cursor_screen.availableGeometry()

        trigger_zone = self._get_trigger_zone(cursor_screen_rect)

        if trigger_zone.contains(cursor_pos):
            if not self._is_visible or not self.geometry().intersects(cursor_screen_rect):
                self._slide_in(cursor_screen_rect)
        else:
            if self._is_visible and not self._is_pinned:
                if not self.geometry().contains(cursor_pos):
                    self._slide_out()

    def _slide_in(self, screen_rect: Optional[QRect] = None):
        if self._animation.state() == QPropertyAnimation.Running:
            self._animation.stop()

        if screen_rect is None or screen_rect.isEmpty():
            screen_rect = self._get_screen_rect()
        if screen_rect.isEmpty():
            return

        # 若窗口当前不在目标屏幕上，先瞬移到目标屏幕的隐藏位置，避免跨屏动画突兀
        current_geometry = self.geometry()
        if not screen_rect.intersects(current_geometry):
            current_geometry = self._get_hidden_geometry(screen_rect)
            self.setGeometry(current_geometry)

        end_geometry = self._get_visible_geometry(screen_rect)

        self._animation.setStartValue(current_geometry)
        self._animation.setEndValue(end_geometry)
        self._animation.start()
        self._is_visible = True
        self._mouse_check_timer.setInterval(100)  # 窗口可见时快速检测
        self.raise_()
        self.activateWindow()

    def _slide_out(self):
        if self._is_pinned or self._is_floating:
            return

        if self._animation.state() == QPropertyAnimation.Running:
            self._animation.stop()

        screen_rect = self._get_screen_rect()
        if screen_rect.isEmpty():
            return

        end_geometry = self._get_hidden_geometry(screen_rect)

        self._animation.setStartValue(self.geometry())
        self._animation.setEndValue(end_geometry)
        self._animation.start()
        self._is_visible = False
        self._mouse_check_timer.setInterval(200)  # 窗口隐藏时降低检测频率

    @Slot()
    def show_window(self):
        # 启动显示保护期，防止立即隐藏
        self._show_protection = True
        self._protection_timer.start(1500)  # 1.5秒保护期
        self._slide_in()

    def hide_window(self):
        self._is_pinned = False
        self._is_floating = False
        update_settings(is_floating=False)
        self._show_protection = False
        self._slide_out()

    def _end_show_protection(self):
        self._show_protection = False

    def enterEvent(self, event):
        # 鼠标进入窗口时确保显示
        self._show_protection = False  # 鼠标进入后取消保护期
        if not self._is_visible:
            self._slide_in()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # 鼠标离开窗口时，延迟检查是否需要隐藏
        if not self._is_pinned and not self._show_protection:
            QTimer.singleShot(300, self._check_should_hide)
        super().leaveEvent(event)

    def _check_should_hide(self):
        if self._is_pinned or self._show_protection:
            return

        cursor_pos = QCursor.pos()
        window_rect = self.geometry()

        if not window_rect.contains(cursor_pos):
            self._slide_out()

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件 - 开始拖动"""
        if event.button() == Qt.LeftButton:
            # 命中子控件（搜索框等）时不启动拖拽，避免顶部 40px 条盖住交互区
            child = self.childAt(event.position().toPoint())
            if child is not None and child is not self:
                super().mousePressEvent(event)
                return
            # 只在窗口顶部 40 像素区域允许拖动
            if event.position().y() <= 40:
                self._dragging = True
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_start_geometry = self.geometry()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件 - 拖动窗口"""
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            new_pos = self._drag_start_geometry.topLeft() + delta
            self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件 - 结束拖动，根据位置吸附或悬浮"""
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
            self._snap_or_float()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _nearest_edge_and_distance(self, screen_rect: QRect):
        """计算窗口中心到四条屏幕边缘的距离，返回 (最近边缘名, 距离)"""
        center = self.geometry().center()
        distances = {
            "left": center.x() - screen_rect.left(),
            "right": screen_rect.right() - center.x(),
            "top": center.y() - screen_rect.top(),
            "bottom": screen_rect.bottom() - center.y(),
        }
        nearest = min(distances, key=distances.get)
        return nearest, distances[nearest]

    def _snap_or_float(self):
        """根据松手位置决定吸附到边缘还是悬浮"""
        screen_rect = self._get_screen_rect()
        if screen_rect.isEmpty():
            return

        SNAP_THRESHOLD = 80
        nearest_edge, distance = self._nearest_edge_and_distance(screen_rect)

        if distance <= SNAP_THRESHOLD:
            self._is_floating = False
            update_settings(is_floating=False)
            if nearest_edge != self._dock_edge:
                self.set_dock_edge(nearest_edge)
            else:
                self._move_to_visible_position(screen_rect)
        else:
            self._is_floating = True
            self._is_pinned = True
            pos = self.geometry().topLeft()
            update_settings(is_floating=True, floating_position=(pos.x(), pos.y()))

    def _snap_to_nearest_edge(self):
        """吸附到最近的屏幕边缘（强制吸附，不进入悬浮）"""
        screen_rect = self._get_screen_rect()
        if screen_rect.isEmpty():
            return

        self._is_floating = False
        update_settings(is_floating=False)

        nearest_edge, _ = self._nearest_edge_and_distance(screen_rect)
        if nearest_edge != self._dock_edge:
            self.set_dock_edge(nearest_edge)
        else:
            self._move_to_visible_position(screen_rect)
