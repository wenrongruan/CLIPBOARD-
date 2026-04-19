from datetime import datetime

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage, QPixmapCache
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)

from core.models import ClipboardItem, TextClipboardItem, ImageClipboardItem


class ClipboardItemWidget(QWidget):
    clicked = Signal(ClipboardItem)
    delete_clicked = Signal(ClipboardItem)
    star_clicked = Signal(ClipboardItem)
    save_clicked = Signal(ClipboardItem)
    cloud_delete_clicked = Signal(ClipboardItem)
    image_url_clicked = Signal(ClipboardItem)

    def __init__(self, item: ClipboardItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("itemWidget")
        # 样式已合并到 MAIN_STYLE，由父级 MainWindow 统一设置
        self.setCursor(Qt.PointingHandCursor)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)

        # 左侧：内容预览
        content_layout = QVBoxLayout()
        content_layout.setSpacing(6)

        if isinstance(self.item, ImageClipboardItem) and self.item.image_thumbnail:
            image_label = QLabel()
            image_label.setObjectName("imageLabel")
            cache_key = self.item.content_hash
            image_label.setFixedSize(56, 56)
            cached = QPixmapCache.find(cache_key) if cache_key else None
            if cached is not None:
                # 命中缓存直接同步设置, 避免小图后台化开销
                image_label.setPixmap(cached)
            else:
                # 未命中: 占位 + 下一 tick 解码, 不阻塞首屏布局
                image_label.setPixmap(QPixmap())
                thumb_bytes = self.item.image_thumbnail
                def _decode_and_set(lbl=image_label, key=cache_key, data=thumb_bytes):
                    if lbl is None:
                        return
                    pixmap = QPixmap()
                    pixmap.loadFromData(data)
                    if pixmap.isNull():
                        return
                    scaled = pixmap.scaled(
                        56, 56, Qt.KeepAspectRatio, Qt.FastTransformation
                    )
                    if key:
                        QPixmapCache.insert(key, scaled)
                    lbl.setPixmap(scaled)
                QTimer.singleShot(0, _decode_and_set)
            layout.addWidget(image_label)

            # 图片信息
            info_layout = QVBoxLayout()
            info_layout.setSpacing(3)

            preview_label = QLabel(self.item.preview)
            preview_label.setObjectName("previewLabel")
            preview_label.setTextFormat(Qt.PlainText)
            preview_label.setMinimumWidth(0)
            preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            info_layout.addWidget(preview_label)

            meta_label = self._make_meta_label()
            info_layout.addWidget(meta_label)

            info_layout.addStretch()
            layout.addLayout(info_layout, 1)

        else:
            # 文本预览 - 保留换行显示，最多3行
            preview_text = self._get_multiline_preview(self.item, max_lines=3, max_chars=120)
            preview_label = QLabel(preview_text)
            preview_label.setObjectName("previewLabel")
            preview_label.setTextFormat(Qt.PlainText)
            preview_label.setWordWrap(True)
            preview_label.setMinimumWidth(0)
            preview_label.setMaximumHeight(54)
            preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            content_layout.addWidget(preview_label)

            content_layout.addStretch()

            meta_label = self._make_meta_label()
            content_layout.addWidget(meta_label)

            layout.addLayout(content_layout, 1)

        # 右侧：操作按钮 - 用 QWidget 包裹确保固定宽度
        button_container = QWidget()
        button_container.setFixedWidth(28)
        button_layout = QVBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(4)

        star_btn = QPushButton("★" if self.item.is_starred else "☆")
        star_btn.setObjectName("starButton")
        star_btn.setToolTip("收藏" if not self.item.is_starred else "取消收藏")
        star_btn.clicked.connect(lambda: self.star_clicked.emit(self.item))
        button_layout.addWidget(star_btn)

        if self.item.is_cloud_synced:
            cloud_btn = QPushButton("☁")
            cloud_btn.setObjectName("cloudButton")
            cloud_btn.setToolTip("已同步到云端\n点击删除云端副本")
            cloud_btn.clicked.connect(lambda: self.cloud_delete_clicked.emit(self.item))
            button_layout.addWidget(cloud_btn)

        if self.item.is_image:
            if self.item.is_cloud_synced:
                url_btn = QPushButton("🔗")
                url_btn.setObjectName("urlButton")
                url_btn.setToolTip("复制图片链接")
                url_btn.clicked.connect(lambda: self.image_url_clicked.emit(self.item))
                button_layout.addWidget(url_btn)

            save_btn = QPushButton("💾")
            save_btn.setObjectName("saveButton")
            save_btn.setToolTip("保存图片")
            save_btn.clicked.connect(lambda: self.save_clicked.emit(self.item))
            button_layout.addWidget(save_btn)

        delete_btn = QPushButton("×")
        delete_btn.setObjectName("deleteButton")
        delete_btn.setToolTip("删除")
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.item))
        button_layout.addWidget(delete_btn)

        button_layout.addStretch()
        layout.addWidget(button_container)

    def _make_meta_label(self) -> QLabel:
        meta_text = self._format_time(self.item.created_at)
        if self.item.device_name:
            meta_text += "  ·  " + self.item.device_name
        label = QLabel(meta_text)
        label.setObjectName("metaLabel")
        label.setMinimumWidth(0)
        return label

    @staticmethod
    def _get_multiline_preview(item: ClipboardItem, max_lines: int = 3, max_chars: int = 120) -> str:
        """保留原始换行结构，取前几行，更自然地展示内容"""
        if not isinstance(item, TextClipboardItem) or not item.text_content:
            return item.preview or ""
        text = item.text_content
        result_lines: list[str] = []
        total_chars = 0
        start = 0
        while start < len(text) and len(result_lines) < max_lines and total_chars < max_chars:
            end = text.find("\n", start)
            if end == -1:
                end = len(text)
            stripped = text[start:end].strip()
            start = end + 1
            if not stripped and not result_lines:
                continue
            remaining = max_chars - total_chars
            if len(stripped) > remaining:
                stripped = stripped[:remaining] + "…"
            result_lines.append(stripped)
            total_chars += len(stripped)
        result = "\n".join(result_lines)
        if total_chars < len(text.strip()):
            if not result.endswith("…"):
                result += " …"
        return result or item.preview or ""

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
