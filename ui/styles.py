"""Shared Qt design tokens and the application stylesheet.

Keep surfaces explicit and child widgets transparent so labels and button
containers inherit their card instead of painting small rectangular patches.
"""
import platform
from string import Template

COLORS = {
    "page": "#f7f8fa",
    "surface": "#ffffff",
    "sidebar": "#eef1f4",
    "hover": "#edf1f4",
    "border": "#dce2e7",
    "subtle": "#e9edf1",
    "text": "#25323d",
    "secondary": "#5e6e7b",
    "muted": "#697986",
    "disabled": "#9aa5ad",
    "accent": "#247a64",
    "accent_hover": "#1b6552",
    "accent_soft": "#e3f0ea",
    "accent_border": "#a7cdbd",
    "danger": "#ba4c50",
    "danger_soft": "#fbeded",
    "warning": "#936422",
    "warning_soft": "#fff5e4",
}

# On macOS the default QFont is the actual system UI font. Web aliases such
# as -apple-system are not Qt font families and trigger slow alias lookup.
_FONT_FAMILY = "" if platform.system() == "Darwin" else '"Segoe UI", "Microsoft YaHei", "Sans Serif"'
_FONT_SIZE = "14px" if platform.system() == "Darwin" else "13px"
_SCROLLBAR_WIDTH = "8px"


def _font_family_decl() -> str:
    return f"font-family: {_FONT_FAMILY};" if _FONT_FAMILY else ""


def theme_style(source: str) -> str:
    """Resolve semantic color tokens in the few component-specific styles."""
    return Template(source).substitute(COLORS)


MAIN_STYLE = Template("""
QWidget {
    background: transparent;
    color: $text;
    $font_family
    font-size: $font_size;
}
QWidget#mainWindow, QWidget#mainContent, QDialog, QMessageBox {
    background: $page;
}
QLabel { background: transparent; border: none; }
QLabel[role="muted"], QLabel#pageLabel, QLabel#metaLabel { color: $muted; }
QLabel[role="secondary"] { color: $secondary; }
QLabel#windowTitle { font-size: 24px; font-weight: 700; }
QLabel#windowSubtitle { color: $secondary; font-size: 12px; }
QLabel#brandName { font-size: 14px; font-weight: 700; }
QLabel#brandCaption, QLabel#sidebarCaption { color: $secondary; font-size: 11px; }
QLabel#brandMark { background: $accent; border-radius: 9px; }
QLabel#sectionTitle { color: $accent; font-size: 14px; font-weight: 600; }
QLabel#sectionCaption { color: $secondary; font-size: 12px; font-weight: 600; }
QLabel#emptyTitle { font-size: 18px; font-weight: 600; }
QLabel#emptyDescription { color: $secondary; font-size: 13px; }
QLabel#emptyIcon { background: $accent_soft; border-radius: 16px; }
QLabel#metaLabel { font-size: 11px; }
QLabel#previewLabel { color: $text; font-size: $font_size; }
QLabel#imageLabel { background: $hover; border: 1px solid $subtle; border-radius: 8px; }

QPushButton, QToolButton {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 7px;
    padding: 6px 12px;
    min-height: 18px;
}
QPushButton:hover, QToolButton:hover { background: $hover; border-color: $accent_border; }
QPushButton:pressed, QToolButton:pressed { background: $accent_soft; }
QPushButton:focus, QToolButton:focus { border-color: $accent; }
QPushButton:disabled, QToolButton:disabled { color: $disabled; background: $page; border-color: $subtle; }
QPushButton#okButton { background: $accent; border-color: $accent; color: white; font-weight: 600; }
QPushButton#okButton:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#okButton:pressed { background: $accent_hover; }
QPushButton#okButton:focus { border: 1px solid $text; }
QPushButton#okButton:disabled { background: $border; border-color: $border; color: $secondary; }
QPushButton#iconButton, QPushButton#sidebarToggleBtn {
    background: transparent; border: 1px solid transparent; padding: 0; color: $secondary;
}
QPushButton#iconButton:hover, QPushButton#sidebarToggleBtn:hover { background: $hover; border-color: $border; }
QPushButton#iconButton:checked { background: $accent_soft; border-color: $accent_border; }
QPushButton#iconButton:focus, QPushButton#sidebarToggleBtn:focus { border-color: $accent; }
QPushButton#closeButton { background: transparent; border: 1px solid transparent; padding: 0; }
QPushButton#closeButton:hover { background: $danger_soft; border-color: $danger; }
QPushButton#closeButton:focus { border-color: $accent; }
QPushButton#sidebarToggleBtn { font-size: 18px; }
QPushButton#tabBtn {
    background: transparent; border: none; border-bottom: 2px solid transparent;
    border-radius: 0; padding: 10px 2px; color: $secondary; font-weight: 600;
}
QPushButton#tabBtn:hover { color: $accent; }
QPushButton#tabBtn:checked { color: $accent; border-bottom-color: $accent; }
QPushButton#tabBtn:focus { background: $accent_soft; }
QToolButton#viewButton { background: transparent; border: 1px solid transparent; padding: 0; }
QToolButton#viewButton:hover { background: $hover; }
QToolButton#viewButton:checked { background: $surface; border-color: $border; }
QToolButton#viewButton:focus { border-color: $accent; }
QPushButton#pageBtn { padding: 0; min-width: 28px; min-height: 28px; }

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $surface; color: $text; border: 1px solid $border; border-radius: 7px;
    padding: 7px 10px; min-height: 20px; selection-background-color: $accent_soft;
    selection-color: $text;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { background: $hover; color: $disabled; }
QLineEdit#searchInput { padding: 10px 12px; border-radius: 9px; }
QComboBox:hover { border-color: $accent_border; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: $surface; color: $text; border: 1px solid $border;
    selection-background-color: $accent_soft; selection-color: $accent;
    padding: 4px; outline: 0;
}
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; }

QWidget#sidebar { background: $sidebar; border-right: 1px solid $border; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item {
    background: $surface; border: 1px solid $subtle; border-radius: 10px;
    margin: 3px 0; padding: 0;
}
QListWidget::item:hover { background: $surface; border-color: $accent_border; }
QListWidget::item:selected { background: $accent_soft; border-color: $accent_border; }
QListWidget#tagList::item {
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    margin: 2px 0; padding: 8px; color: $secondary;
}
QListWidget#tagList::item:hover { background: $subtle; }
QListWidget#tagList::item:selected { background: $accent_soft; border-color: $accent_border; color: $accent; }
QWidget#itemWidget { background: transparent; }
QPushButton#starButton, QPushButton#deleteButton, QPushButton#saveButton,
QPushButton#cloudButton, QPushButton#urlButton {
    background: transparent; border: 1px solid transparent; padding: 0; min-height: 0;
}
QPushButton#starButton:hover, QPushButton#saveButton:hover, QPushButton#urlButton:hover,
QPushButton#cloudButton:hover { background: $accent_soft; border-color: $accent_border; }
QPushButton#deleteButton:hover { background: $danger_soft; border-color: $danger; }
QPushButton#starButton:focus, QPushButton#deleteButton:focus, QPushButton#saveButton:focus,
QPushButton#cloudButton:focus, QPushButton#urlButton:focus { border-color: $accent; }
QFrame#timelineGroup { background: $surface; border: 1px solid $subtle; border-radius: 10px; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: $scrollbar_width; margin: 2px 0; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: $disabled; }
QScrollBar:horizontal { background: transparent; height: $scrollbar_width; }
QScrollBar::handle:horizontal { background: $border; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: $disabled; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane { background: $surface; border: 1px solid $border; border-radius: 9px; padding: 8px; }
QTabBar::tab {
    color: $secondary; background: transparent; padding: 10px 12px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: $accent; border-bottom-color: $accent; font-weight: 600; }
QTabBar::tab:hover { background: $accent_soft; }
QGroupBox { border: 1px solid $border; border-radius: 8px; margin-top: 16px; padding: 16px 10px 10px; }
QGroupBox::title {
    color: $secondary; subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 6px; left: 10px; font-weight: 600;
}
QCheckBox { spacing: 8px; min-height: 24px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QProgressBar { background: $subtle; border: none; border-radius: 3px; color: $secondary; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }

QTableView {
    background: $surface; alternate-background-color: $page; border: 1px solid $border;
    border-radius: 8px; gridline-color: $subtle; color: $text;
    selection-background-color: $accent_soft; selection-color: $text;
}
QTableView::item { padding: 8px; border: none; }
QTableView::item:selected { background: $accent_soft; color: $text; }
QHeaderView::section {
    background: $page; color: $secondary; padding: 9px 8px; border: none;
    border-bottom: 1px solid $border; font-weight: 600;
}
QHeaderView::section:hover { background: $hover; }
QTableCornerButton::section { background: $page; border: none; border-bottom: 1px solid $border; }
QPushButton#dbTypeCard { background: $surface; border: 1px solid $border; padding: 12px; }
QPushButton#dbTypeCard:hover { border-color: $accent; }
QPushButton#dbTypeCard:checked { background: $accent_soft; border-color: $accent; }

QMenu { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 8px 24px; border-radius: 5px; }
QMenu::item:selected { background: $accent_soft; color: $accent; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $subtle; margin: 4px 8px; }
QToolTip { background: $text; color: white; border: none; border-radius: 5px; padding: 6px 9px; }
QLabel#copyFeedbackSuccess { color: $accent; background: $accent_soft; border-radius: 6px; padding: 8px; }
QLabel#copyFeedbackError { color: $danger; background: $danger_soft; border-radius: 6px; padding: 8px; }
QLabel#pluginProgress { color: $accent; background: $accent_soft; border-radius: 6px; padding: 8px; }
QLabel#pluginTimeout { color: $warning; background: $warning_soft; border-radius: 6px; padding: 8px; }
QLabel#permissionTag { color: $warning; font-size: 11px; }
QWidget#pluginItem { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 8px; }
QWidget#pluginItem:hover { border-color: $accent_border; }
QPushButton#pluginConfigBtn { background: transparent; border: 1px solid $border; padding: 5px 10px; color: $secondary; font-size: 12px; }
QPushButton#pluginConfigBtn:hover { background: $accent_soft; color: $accent; border-color: $accent_border; }
""").substitute(COLORS, font_family=_font_family_decl(), font_size=_FONT_SIZE, scrollbar_width=_SCROLLBAR_WIDTH)
