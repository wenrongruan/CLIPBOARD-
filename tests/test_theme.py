"""Open windows follow native appearance changes without losing UI state."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)
import pytest

from ui import styles
from ui.icons import icon, set_label_icon
from ui.theme import follow_system_theme, theme_manager


class _SystemAppearance(QObject):
    colorSchemeChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.scheme = Qt.ColorScheme.Light

    def colorScheme(self):
        return self.scheme

    def switch(self, scheme):
        self.scheme = scheme
        self.colorSchemeChanged.emit(scheme)


@pytest.fixture
def appearance(_qt_application, monkeypatch):
    manager = theme_manager()
    previous = styles.current_theme()
    hints = _SystemAppearance()
    monkeypatch.setattr(manager, "_style_hints", hints)
    hints.colorSchemeChanged.connect(manager._on_color_scheme_changed)
    manager._apply_theme("light", force=True)
    yield _qt_application, hints
    hints.colorSchemeChanged.disconnect(manager._on_color_scheme_changed)
    manager._apply_theme(previous, force=True)


def test_system_change_updates_open_windows_and_icons_without_losing_state(appearance):
    app, system = appearance
    window = QWidget()
    window.setObjectName("mainWindow")
    follow_system_theme(window)
    layout = QVBoxLayout(window)
    label = QLabel("文字、图片与灵感", window)
    label.setStyleSheet(styles.theme_style("color:$accent;background:$surface;"))
    layout.addWidget(label)
    button = QPushButton(window)
    button.setIcon(icon("star", "accent", True))
    layout.addWidget(button)
    mark = QLabel(window)
    set_label_icon(mark, "clipboard", "accent", 24)
    layout.addWidget(mark)
    search = QLineEdit("from:chrome $100", window)
    action = search.addAction(icon("close"), QLineEdit.TrailingPosition)
    layout.addWidget(search)
    checkbox = QCheckBox("保留我的设置", window)
    checkbox.setChecked(True)
    layout.addWidget(checkbox)
    records = QListWidget(window)
    records.addItem(QListWidgetItem(icon("tag"), "工作"))
    records.setCurrentRow(0)
    layout.addWidget(records)
    window.show()
    app.processEvents()
    light_mark = mark.pixmap().cacheKey()

    try:
        for scheme, colors in (
            (Qt.ColorScheme.Dark, styles.DARK_COLORS),
            (Qt.ColorScheme.Light, styles.LIGHT_COLORS),
            (Qt.ColorScheme.Dark, styles.DARK_COLORS),
        ):
            system.switch(scheme)
            app.processEvents()
            assert colors["page"] in window.styleSheet()
            assert label.styleSheet() == f'color:{colors["accent"]};background:{colors["surface"]};'
            assert button.icon().cacheKey() == icon("star", "accent", True).cacheKey()
            assert action.icon().cacheKey() == icon("close").cacheKey()
            assert records.item(0).icon().cacheKey() == icon("tag").cacheKey()
            assert app.palette().color(QPalette.Window).name() == colors["page"]
            assert search.text() == "from:chrome $100"
            assert checkbox.isChecked()
            assert records.currentRow() == 0
        assert mark.pixmap().cacheKey() != light_mark
    finally:
        window.close()
        window.deleteLater()


def test_dialog_created_after_system_change_uses_current_theme(appearance):
    _, system = appearance
    system.switch(Qt.ColorScheme.Dark)
    dialog = QWidget()
    follow_system_theme(dialog)
    try:
        assert styles.DARK_COLORS["page"] in dialog.styleSheet()
        assert styles.theme_style("color:$text;") == f'color:{styles.DARK_COLORS["text"]};'
        assert "ui-chevron-down-dark.svg" in dialog.styleSheet()
    finally:
        dialog.close()
        dialog.deleteLater()
