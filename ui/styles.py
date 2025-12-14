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
QPushButton[text="⚙"], QPushButton[text="✕"] {
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
    background-color: #3c3c3c;
    border-radius: 8px;
    margin: 4px 0px;
    padding: 0px;
}

QListWidget::item:hover {
    background-color: #4a4a4a;
}

QListWidget::item:selected {
    background-color: #0078d4;
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

QLabel#deviceLabel {
    color: #888888;
    font-size: 11px;
}

QLabel#timeLabel {
    color: #666666;
    font-size: 11px;
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
"""

ITEM_WIDGET_STYLE = """
QWidget#itemWidget {
    background-color: transparent;
}

QLabel#previewLabel {
    color: #ffffff;
    font-size: """ + _FONT_SIZE + """;
}

QLabel#imageLabel {
    background-color: #1e1e1e;
    border-radius: 4px;
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
"""
