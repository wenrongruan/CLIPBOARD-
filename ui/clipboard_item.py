from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)

from core.models import ClipboardItem
from .styles import ITEM_WIDGET_STYLE


class ClipboardItemWidget(QWidget):
    clicked = Signal(ClipboardItem)
    delete_clicked = Signal(ClipboardItem)
    star_clicked = Signal(ClipboardItem)

    def __init__(self, item: ClipboardItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("itemWidget")
        self.setStyleSheet(ITEM_WIDGET_STYLE)
        self.setCursor(Qt.PointingHandCursor)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # 左侧：内容预览
        content_layout = QVBoxLayout()
        content_layout.setSpacing(4)

        if self.item.is_image and self.item.image_thumbnail:
            # 图片预览
            image_label = QLabel()
            image_label.setObjectName("imageLabel")
            pixmap = QPixmap()
            pixmap.loadFromData(self.item.image_thumbnail)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                image_label.setPixmap(scaled)
            image_label.setFixedSize(60, 60)
            layout.addWidget(image_label)

            # 图片信息
            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)

            preview_label = QLabel(self.item.preview)
            preview_label.setObjectName("previewLabel")
            info_layout.addWidget(preview_label)

            time_label = QLabel(self._format_time(self.item.created_at))
            time_label.setObjectName("timeLabel")
            info_layout.addWidget(time_label)

            if self.item.device_name:
                device_label = QLabel(self.item.device_name)
                device_label.setObjectName("deviceLabel")
                info_layout.addWidget(device_label)

            info_layout.addStretch()
            layout.addLayout(info_layout, 1)

        else:
            # 文本预览
            preview_text = self.item.get_display_preview(80)
            preview_label = QLabel(preview_text)
            preview_label.setObjectName("previewLabel")
            preview_label.setWordWrap(True)
            preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            content_layout.addWidget(preview_label)

            # 时间和设备
            meta_layout = QHBoxLayout()
            meta_layout.setSpacing(8)

            time_label = QLabel(self._format_time(self.item.created_at))
            time_label.setObjectName("timeLabel")
            meta_layout.addWidget(time_label)

            if self.item.device_name:
                device_label = QLabel(self.item.device_name)
                device_label.setObjectName("deviceLabel")
                meta_layout.addWidget(device_label)

            meta_layout.addStretch()
            content_layout.addLayout(meta_layout)

            layout.addLayout(content_layout, 1)

        # 右侧：操作按钮
        button_layout = QVBoxLayout()
        button_layout.setSpacing(4)

        star_btn = QPushButton("★" if self.item.is_starred else "☆")
        star_btn.setObjectName("starButton")
        star_btn.setToolTip("收藏" if not self.item.is_starred else "取消收藏")
        star_btn.clicked.connect(lambda: self.star_clicked.emit(self.item))
        button_layout.addWidget(star_btn)

        delete_btn = QPushButton("×")
        delete_btn.setObjectName("deleteButton")
        delete_btn.setToolTip("删除")
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.item))
        button_layout.addWidget(delete_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _format_time(self, timestamp_ms: int) -> str:
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        now = datetime.now()

        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        elif dt.year == now.year:
            return dt.strftime("%m-%d %H:%M")
        else:
            return dt.strftime("%Y-%m-%d")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.item)
        super().mousePressEvent(event)
