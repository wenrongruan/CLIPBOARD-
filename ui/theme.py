"""Follow the native system color scheme and update open Qt windows in place."""
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from . import styles


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self._updating = False
        self._style_hints = app.styleHints()
        self._style_hints.colorSchemeChanged.connect(self._on_color_scheme_changed)
        app.installEventFilter(self)
        self._apply_theme(self._system_theme_name(), force=True)

    def _system_theme_name(self) -> str:
        scheme = self._style_hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
        # Some Linux/offscreen Qt backends expose no color scheme. Their native
        # application palette still tells us whether the background is dark.
        return "dark" if self._app.palette().color(QPalette.Window).lightness() < 128 else "light"

    def _on_color_scheme_changed(self, scheme):
        if scheme == Qt.ColorScheme.Dark:
            self._apply_theme("dark")
        elif scheme == Qt.ColorScheme.Light:
            self._apply_theme("light")
        else:
            self._apply_theme(self._system_theme_name())

    def eventFilter(self, obj, event):
        if (obj is self._app and not self._updating
                and event.type() == QEvent.ApplicationPaletteChange
                and self._style_hints.colorScheme() == Qt.ColorScheme.Unknown):
            self._apply_theme(self._system_theme_name())
        return super().eventFilter(obj, event)

    def _apply_theme(self, name: str, *, force: bool = False):
        if self._updating or (name == styles.current_theme() and not force):
            return
        self._updating = True
        try:
            styles.set_theme(name)
            palette = QPalette(self._app.palette())
            roles = {
                QPalette.Window: "page", QPalette.WindowText: "text",
                QPalette.Base: "surface", QPalette.AlternateBase: "page",
                QPalette.Text: "text", QPalette.Button: "surface",
                QPalette.ButtonText: "text", QPalette.PlaceholderText: "muted",
                QPalette.Highlight: "accent_soft", QPalette.HighlightedText: "text",
                QPalette.Link: "accent", QPalette.LinkVisited: "accent",
                QPalette.ToolTipBase: "surface", QPalette.ToolTipText: "text",
            }
            for role, token in roles.items():
                palette.setColor(role, QColor(styles.COLORS[token]))
            for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
                palette.setColor(QPalette.Disabled, role, QColor(styles.COLORS["disabled"]))
            self._app.setPalette(palette)

            widgets = self._app.allWidgets()
            for widget in widgets:
                if widget.property("sharedThemeRoot"):
                    widget.setStyleSheet(styles.main_style())
                elif widget.styleSheet():
                    updated = styles.refresh_component_style(widget.styleSheet())
                    if updated != widget.styleSheet():
                        widget.setStyleSheet(updated)
            from .icons import refresh_themed_icons
            refresh_themed_icons(widgets)
            for widget in widgets:
                # Older PySide6 bindings expose QAbstractItemView.update(index)
                # without the inherited no-argument overload.
                QWidget.update(widget)
            self.theme_changed.emit(name)
        finally:
            self._updating = False


def theme_manager() -> ThemeManager:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Create QApplication before installing the theme")
    manager = getattr(app, "_clipboard_theme_manager", None)
    if manager is None:
        manager = ThemeManager(app)
        app._clipboard_theme_manager = manager
    return manager


def follow_system_theme(widget) -> None:
    """Register a window/dialog. No user preference or system setting is changed."""
    theme_manager()
    widget.setProperty("sharedThemeRoot", True)
    widget.setStyleSheet(styles.main_style())
