import platform

# 根据平台选择字体
if platform.system() == "Darwin":
    _FONT_FAMILY = '-apple-system, "SF Pro Display", "Helvetica Neue", sans-serif'
    _FONT_SIZE = "14px"  # macOS 上字体稍大一点更清晰
    _SCROLLBAR_WIDTH = "10px"  # macOS 滚动条稍宽
else:
    _FONT_FAMILY = '"Microsoft YaHei", "Segoe UI", sans-serif'
    _FONT_SIZE = "13px"
    _SCROLLBAR_WIDTH = "8px"

MAIN_STYLE = """
QWidget {
    background-color: #2b2b2b;
    color: #ffffff;
    font-family: """ + _FONT_FAMILY + """;
    font-size: """ + _FONT_SIZE + """;
}

QLineEdit {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 8px 12px;
    color: #ffffff;
}

QLineEdit:focus {
    border: 1px solid #0078d4;
}

QLineEdit::placeholder {
    color: #888888;
}

QPushButton {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 4px 8px;
    color: #ffffff;
}

QPushButton[text="📌"], QPushButton[text="📍"],
QPushButton[text="⚙"], QPushButton[text="✕"], QPushButton[text="—"] {
    min-width: 28px;
    max-width: 28px;
    padding: 2px;
    font-size: 14px;
}

QPushButton:hover {
    background-color: #4a4a4a;
    border-color: #666666;
}

QPushButton:pressed {
    background-color: #555555;
}

QPushButton:disabled {
    background-color: #2b2b2b;
    color: #666666;
}

QListWidget {
    background-color: #2b2b2b;
    border: none;
    outline: none;
}

QListWidget::item {
    background-color: #333333;
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.04);
    margin: 3px 2px;
    padding: 0px;
}

QListWidget::item:hover {
    background-color: #3a3a3a;
    border: 1px solid rgba(255, 255, 255, 0.08);
}

QListWidget::item:selected {
    background-color: rgba(0, 120, 212, 0.25);
    border: 1px solid rgba(0, 120, 212, 0.4);
}

QScrollBar:vertical {
    background-color: #2b2b2b;
    width: """ + _SCROLLBAR_WIDTH + """;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #555555;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #666666;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
}

QLabel {
    color: #ffffff;
}

QLabel#pageLabel {
    color: #888888;
    font-size: 12px;
}

QLabel#copyFeedbackSuccess {
    color: #4ade80;
    background: rgba(34, 197, 94, 0.15);
    border-radius: 4px;
    padding: 4px 8px;
}

QLabel#copyFeedbackError {
    color: #f87171;
    background: rgba(239, 68, 68, 0.15);
    border-radius: 4px;
    padding: 4px 8px;
}

QMenu {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #0078d4;
}

QToolTip {
    background-color: #3c3c3c;
    color: #ffffff;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 4px 8px;
}

QWidget#itemWidget {
    background-color: transparent;
}

QLabel#previewLabel {
    color: #e8e8e8;
    font-size: """ + _FONT_SIZE + """;
    line-height: 1.4;
}

QLabel#metaLabel {
    color: #777777;
    font-size: 11px;
}

QLabel#imageLabel {
    background-color: #1e1e1e;
    border-radius: 6px;
}

QPushButton#starButton {
    background-color: transparent;
    border: none;
    padding: 4px;
    min-width: 24px;
    max-width: 24px;
}

QPushButton#starButton:hover {
    background-color: rgba(255, 255, 255, 0.1);
    border-radius: 4px;
}

QPushButton#deleteButton {
    background-color: transparent;
    border: none;
    padding: 4px;
    min-width: 24px;
    max-width: 24px;
    color: #ff6b6b;
}

QPushButton#deleteButton:hover {
    background-color: rgba(255, 107, 107, 0.2);
    border-radius: 4px;
}

QPushButton#saveButton {
    background-color: transparent;
    border: none;
    padding: 4px;
    min-width: 24px;
    max-width: 24px;
    color: #4fc3f7;
}

QPushButton#saveButton:hover {
    background-color: rgba(79, 195, 247, 0.2);
    border-radius: 4px;
}

QTabWidget::pane {
    border: 1px solid #555555;
    border-radius: 6px;
    background-color: #2b2b2b;
}

QTabBar::tab {
    background-color: #3c3c3c;
    color: #888888;
    padding: 8px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

QTabBar::tab:selected {
    background-color: #2b2b2b;
    color: #ffffff;
    border-bottom: 2px solid #0078d4;
}

QTabBar::tab:hover {
    background-color: #4a4a4a;
}

QComboBox {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
}

QComboBox:hover {
    border-color: #0078d4;
}

QComboBox::drop-down {
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    color: #ffffff;
    selection-background-color: #0078d4;
}

QGroupBox {
    border: 1px solid #555555;
    border-radius: 6px;
    margin-top: 16px;
    padding-top: 16px;
}

QGroupBox::title {
    color: #0078d4;
    background-color: #2b2b2b;
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
}

QSpinBox {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 4px 8px;
    color: #ffffff;
}

QSpinBox:focus {
    border-color: #0078d4;
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: #4a4a4a;
    border: none;
    width: 16px;
}

QPushButton#dbTypeCard {
    background-color: #3c3c3c;
    border: 2px solid #555555;
    border-radius: 8px;
    padding: 12px;
    color: #ffffff;
}

QPushButton#dbTypeCard:hover {
    border-color: #0078d4;
}

QPushButton#dbTypeCard:checked {
    background-color: rgba(0, 120, 212, 0.15);
    border-color: #0078d4;
}

QPushButton#okButton {
    background-color: #0078d4;
    border: none;
    color: #ffffff;
}

QPushButton#okButton:hover {
    background-color: #1a8ae8;
}

QLabel#sectionTitle {
    color: #0078d4;
    font-size: 14px;
    font-weight: bold;
}

QMenu::separator {
    height: 1px;
    background-color: #555555;
    margin: 4px 8px;
}

QLabel#pluginProgress {
    color: #58a6ff;
    background: rgba(88, 166, 255, 0.12);
    border-radius: 4px;
    padding: 4px 8px;
}

QLabel#pluginTimeout {
    color: #f0ad4e;
    background: rgba(240, 173, 78, 0.15);
    border-radius: 4px;
    padding: 4px 8px;
}

QLabel#permissionTag {
    color: #f0ad4e;
    font-size: 11px;
}

QWidget#pluginItem {
    background-color: #333333;
    border: 1px solid #444444;
    border-radius: 6px;
    padding: 8px;
}

QWidget#pluginItem:hover {
    border-color: #0078d4;
}

QPushButton#pluginConfigBtn {
    background-color: transparent;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 4px 10px;
    color: #aaaaaa;
    font-size: 12px;
}

QPushButton#pluginConfigBtn:hover {
    border-color: #0078d4;
    color: #ffffff;
}
"""
