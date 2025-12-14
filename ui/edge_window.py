import platform
from typing import Optional

from PySide6.QtCore import Qt, QRect, QPropertyAnimation, QEasingCurve, QTimer, QPoint
from PySide6.QtGui import QCursor, QScreen
from PySide6.QtWidgets import QWidget, QApplication

from config import Config


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
            # macOS 上启用透明背景以获得更好的视觉效果
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool  # 不在任务栏显示
            )
            self.setAttribute(Qt.WA_TranslucentBackground, False)

        # 尺寸配置
        self._window_width = Config.WINDOW_WIDTH
        self._window_height = Config.WINDOW_HEIGHT
        self._hidden_margin = Config.HIDDEN_MARGIN
        self._trigger_zone = Config.TRIGGER_ZONE

        # 停靠边缘
        self._dock_edge = Config.get_dock_edge()

        # 动画
        self._animation = QPropertyAnimation(self, b"geometry")
        self._animation.setDuration(Config.ANIMATION_DURATION)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

        # 状态
        self._is_visible = False
        self._is_pinned = False  # 固定模式，不自动隐藏
        self._show_protection = False  # 显示保护期，防止立即隐藏

        # 鼠标位置检测定时器
        self._mouse_check_timer = QTimer(self)
        self._mouse_check_timer.timeout.connect(self._check_mouse_position)
        self._mouse_check_timer.start(50)

        # 显示保护定时器
        self._protection_timer = QTimer(self)
        self._protection_timer.setSingleShot(True)
        self._protection_timer.timeout.connect(self._end_show_protection)

        # 初始化位置
        self._init_position()

    def _init_position(self):
        screen_rect = self._get_screen_rect()
        if not screen_rect.isEmpty():
            self._move_to_hidden_position(screen_rect)
            self.show()

    def _get_screen(self) -> Optional[QScreen]:
        return QApplication.primaryScreen()

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
            Config.set_dock_edge(edge)
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
        # 保护期内不自动隐藏
        if self._show_protection:
            return

        screen_rect = self._get_screen_rect()
        if screen_rect.isEmpty():
            return

        cursor_pos = QCursor.pos()
        trigger_zone = self._get_trigger_zone(screen_rect)

        # 检查鼠标是否在触发区域
        if trigger_zone.contains(cursor_pos):
            if not self._is_visible:
                self._slide_in()
        else:
            # 检查鼠标是否在窗口内
            window_rect = self.geometry()
            if self._is_visible and not self._is_pinned:
                if not window_rect.contains(cursor_pos):
                    self._slide_out()

    def _slide_in(self):
        if self._animation.state() == QPropertyAnimation.Running:
            self._animation.stop()

        screen_rect = self._get_screen_rect()
        if screen_rect.isEmpty():
            return

        end_geometry = self._get_visible_geometry(screen_rect)

        self._animation.setStartValue(self.geometry())
        self._animation.setEndValue(end_geometry)
        self._animation.start()
        self._is_visible = True
        self.raise_()
        self.activateWindow()

    def _slide_out(self):
        if self._is_pinned:
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

    def show_window(self):
        # 启动显示保护期，防止立即隐藏
        self._show_protection = True
        self._protection_timer.start(1500)  # 1.5秒保护期
        self._slide_in()

    def hide_window(self):
        self._is_pinned = False
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
