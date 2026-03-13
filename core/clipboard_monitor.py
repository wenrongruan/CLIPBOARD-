import io
import logging
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QClipboard, QImage
from PySide6.QtWidgets import QApplication

from .models import ClipboardItem, ContentType
from .repository import ClipboardRepository
from config import Config
from utils.hash_utils import compute_content_hash
from utils.image_utils import create_thumbnail

logger = logging.getLogger(__name__)


class ClipboardMonitor(QObject):
    item_added = Signal(ClipboardItem)
    error_occurred = Signal(str)

    def __init__(self, repository: ClipboardRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.clipboard = QApplication.clipboard()
        self._last_text: Optional[str] = None
        self._last_image_hash: Optional[str] = None
        self._monitoring = False
        self._add_counter = 0  # 计数器，每 50 次 add 才清理

        # 使用轮询定时器代替 dataChanged 信号（Windows 上更可靠）
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_clipboard)

    def _maybe_cleanup(self):
        """每 50 次 add 才执行一次清理"""
        self._add_counter += 1
        if self._add_counter >= 50:
            self._add_counter = 0
            self.repository.cleanup_old_items(Config.get_max_items())
            retention_days = Config.get_retention_days()
            if retention_days > 0:
                self.repository.cleanup_expired_items(retention_days)

    def start(self):
        if not self._monitoring:
            self._monitoring = True
            # 记录当前剪贴板内容，避免启动时重复保存
            self._last_text = self.clipboard.text()
            self._poll_timer.start(Config.get_poll_interval_ms())
            logger.info("剪贴板监控已启动 (轮询模式)")

    def update_poll_interval(self, interval_ms: int):
        """更新轮询间隔（毫秒）"""
        if self._monitoring:
            self._poll_timer.stop()
            self._poll_timer.start(interval_ms)

    def stop(self):
        if self._monitoring:
            self._monitoring = False
            self._poll_timer.stop()
            logger.info("剪贴板监控已停止")

    def _poll_clipboard(self):
        if not self._monitoring:
            return

        try:
            mime_data = self.clipboard.mimeData()
            if mime_data is None:
                return

            # 优先检查图片
            if mime_data.hasImage() and Config.get_save_images():
                self._handle_image()
            elif mime_data.hasText() and Config.get_save_text():
                self._handle_text()

        except Exception as e:
            logger.error(f"处理剪贴板内容时出错: {e}")

    def _handle_text(self):
        text = self.clipboard.text()
        if not text or not text.strip():
            return

        # 检查是否和上次相同
        if text == self._last_text:
            return

        self._last_text = text

        # 检查文本长度限制
        max_text_length = Config.get_max_text_length()
        if max_text_length > 0 and len(text) > max_text_length:
            logger.info(f"文本超过最大长度限制 ({len(text)} > {max_text_length})，跳过")
            return

        logger.info(f"检测到新文本: {text[:30]}...")

        content_hash = compute_content_hash(text)

        # 检查是否已存在
        existing = self.repository.get_by_hash(content_hash)
        if existing:
            return

        # 创建新记录
        preview = text[:100].replace("\n", " ").strip()
        if len(text) > 100:
            preview += "..."

        item = ClipboardItem(
            content_type=ContentType.TEXT,
            text_content=text,
            content_hash=content_hash,
            preview=preview,
            device_id=Config.get_device_id(),
            device_name=Config.get_device_name(),
            created_at=int(time.time() * 1000),
        )

        try:
            item_id = self.repository.add_item(item)
            item.id = item_id

            self._maybe_cleanup()

            logger.info(f"保存文本成功: {preview[:50]}...")
            self.item_added.emit(item)

        except Exception as e:
            logger.error(f"保存文本失败: {e}")
            self.error_occurred.emit(f"保存失败: {e}")

    def _fast_image_hash(self, image: QImage) -> str:
        """用缩小到 64x64 的原始像素数据快速计算 hash，避免 PNG 编码开销"""
        small = image.scaled(64, 64, Qt.KeepAspectRatio, Qt.FastTransformation)
        small = small.convertToFormat(QImage.Format.Format_ARGB32)
        ptr = small.constBits()
        return compute_content_hash(bytes(ptr))

    def _handle_image(self):
        image = self.clipboard.image()
        if image.isNull():
            return

        # 快速 hash 检测变化，避免每次都做 PNG 编码
        fast_hash = self._fast_image_hash(image)
        if fast_hash == self._last_image_hash:
            return

        self._last_image_hash = fast_hash

        # hash 变化了，才做完整 PNG 编码
        from PySide6.QtCore import QBuffer, QIODevice

        qbuffer = QBuffer()
        qbuffer.open(QIODevice.WriteOnly)
        if not image.save(qbuffer, "PNG"):
            logger.warning("无法将图片保存为PNG格式")
            return
        image_data = bytes(qbuffer.data())

        if not image_data:
            return

        # 检查图片大小限制
        max_image_size_kb = Config.get_max_image_size_kb()
        if max_image_size_kb > 0 and len(image_data) > max_image_size_kb * 1024:
            logger.info(f"图片超过最大大小限制 ({len(image_data) // 1024}KB > {max_image_size_kb}KB)，跳过")
            return

        content_hash = compute_content_hash(image_data)
        logger.info(f"检测到新图片: {image.width()}x{image.height()}")

        # 检查是否已存在
        existing = self.repository.get_by_hash(content_hash)
        if existing:
            return

        # 创建缩略图
        try:
            thumbnail = create_thumbnail(image_data, Config.THUMBNAIL_SIZE)
        except Exception as e:
            logger.warning(f"创建缩略图失败: {e}")
            thumbnail = None

        item = ClipboardItem(
            content_type=ContentType.IMAGE,
            image_data=image_data,
            image_thumbnail=thumbnail,
            content_hash=content_hash,
            preview=f"[图片 {image.width()}x{image.height()}]",
            device_id=Config.get_device_id(),
            device_name=Config.get_device_name(),
            created_at=int(time.time() * 1000),
        )

        try:
            item_id = self.repository.add_item(item)
            item.id = item_id

            self._maybe_cleanup()

            logger.info(f"保存图片成功: {image.width()}x{image.height()}")
            self.item_added.emit(item)

        except Exception as e:
            logger.error(f"保存图片失败: {e}")
            self.error_occurred.emit(f"保存失败: {e}")

    def copy_to_clipboard(self, item: ClipboardItem):
        if item.is_text and item.text_content:
            self._last_text = item.text_content
            self.clipboard.setText(item.text_content)
        elif item.is_image and item.image_data:
            self._last_image_hash = item.content_hash
            image = QImage()
            image.loadFromData(item.image_data)
            self.clipboard.setImage(image)
