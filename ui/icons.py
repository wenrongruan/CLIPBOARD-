"""Small, consistent SVG line icons rendered by Qt at both display scales."""
from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .styles import COLORS

_PATHS = {
    "clipboard": '<rect x="6" y="5" width="12" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12h6m-6 4h4"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "settings": '<path d="m9.5 4 .7-2h3.6l.7 2 2 .9 2.1-.4 1.8 3.1-1.4 1.6V12l1.4 1.6-1.8 3.1-2.1-.4-2 .9-.7 2h-3.6l-.7-2-2-.9-2.1.4-1.8-3.1L5.1 12V9.2L3.7 7.6l1.8-3.1 2.1.4Z" transform="translate(0 1)"/><circle cx="12" cy="11.6" r="3"/>',
    "pin": '<path d="M9 3h6l-1 6 4 4v2h-5v6h-2v-6H6v-2l4-4z"/>',
    "minus": '<path d="M5 12h14"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 14h8m-8 3h5"/>',
    "star": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "cloud": '<path d="M6 18a4.5 4.5 0 1 1 .4-9 6 6 0 0 1 11.4-.8A5 5 0 1 1 18 18Z"/>',
    "link": '<path d="m10 13 4-4m-6 7-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 2 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0" transform="translate(1 0)"/>',
    "tag": '<path d="M3 3h8l10 10-8 8L3 11z"/><circle cx="7.5" cy="7.5" r="1"/>',
    "chevron-left": '<path d="m14 6-6 6 6 6"/>',
    "chevron-right": '<path d="m10 6 6 6-6 6"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4 2c-1 .7-1.5 1-1.5 2M12 17h.01"/>',
}


@lru_cache(maxsize=128)
def icon(name: str, color: str = "secondary", filled: bool = False) -> QIcon:
    """Return an implicitly shared icon. Call only after QApplication exists."""
    result = QIcon()
    for mode, stroke in ((QIcon.Normal, COLORS.get(color, color)), (QIcon.Disabled, COLORS["disabled"])):
        fill = stroke if filled else "none"
        source = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="{fill}" stroke="{stroke}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>'
        renderer = QSvgRenderer(QByteArray(source.encode()))
        for scale in (1, 2):
            pixmap = QPixmap(20 * scale, 20 * scale)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            result.addPixmap(pixmap, mode)
    return result
