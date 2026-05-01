import logging
import platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

_IS_MACOS = platform.system() == "Darwin"
# macOS 下 dataChanged 信号可靠，用低频轮询兜底防极端丢失
_MACOS_FALLBACK_POLL_MS = 3000

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QClipboard, QImage
from PySide6.QtWidgets import QApplication

from .models import ClipboardItem, TextClipboardItem, ImageClipboardItem
from .repository import ClipboardRepository
from .source_app import get_current_source_app
from config import settings, THUMBNAIL_SIZE
from utils.hash_utils import compute_content_hash
from utils.image_utils import create_thumbnail, image_to_bytes

logger = logging.getLogger(__name__)


def _is_source_excluded(source_app: str, excluded: tuple) -> bool:
    """source_app 命中 excluded 列表（大小写不敏感子串匹配）则返回 True。

    excluded 来自 settings.excluded_source_apps；用户填的任意串只要是 source_app 的
    子串就视为命中，方便用密码管理器、银行客户端等敏感来源关闭记录。
    """
    if not source_app or not excluded:
        return False
    sa = source_app.lower()
    for pat in excluded:
        if not pat:
            continue
        if pat.lower() in sa:
            return True
    return False


def _capture_source(capture_title: bool, seen_failures: set) -> tuple:
    """捕获当前前台应用，返回 (source_app, source_title)。

    失败时降级：首次失败记 WARNING，同类异常之后降级 DEBUG，避免日志刷屏。
    `seen_failures` 由 caller 持有，跨调用累积已见异常类型。
    """
    try:
        src = get_current_source_app()
    except Exception as e:
        exc_type = type(e).__name__
        if exc_type not in seen_failures:
            seen_failures.add(exc_type)
            logger.warning(f"捕获来源 App 失败（首次 {exc_type}）: {e}")
        else:
            logger.debug(f"捕获来源 App 再次失败 ({exc_type}): {e}")
        return "", ""
    source_app_value = src.bundle_id or src.app_name or ""
    source_title_value = src.window_title if capture_title else ""
    return source_app_value, source_title_value


class ClipboardMonitor(QObject):
    item_added = Signal(ClipboardItem)
    error_occurred = Signal(str)
    monitor_unhealthy = Signal(str)
    monitor_stopped = Signal(str)

    # 连续失败阈值
    _UNHEALTHY_THRESHOLD = 10
    _STOP_THRESHOLD = 30

    def __init__(self, repository: ClipboardRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.clipboard = QApplication.clipboard()
        self._last_text: Optional[str] = None
        self._last_image_hash: Optional[str] = None
        self._monitoring = False
        self._add_counter = 0  # 计数器，每 50 次 add 才清理
        self._counter_lock = threading.Lock()  # 保护 _add_counter 在主线程和图片后台线程的并发访问
        self._image_executor = ThreadPoolExecutor(max_workers=1)
        self._consecutive_failures = 0
        self._unhealthy_notified = False
        self._signal_connected = False
        # 记录已见过的 source_app 异常类型，避免首次后刷屏 WARNING
        self._source_app_seen_failures: set = set()

        # 使用轮询定时器代替 dataChanged 信号（Windows 上更可靠）
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_clipboard)

    def _maybe_cleanup(self):
        """每 50 次 add 才执行一次清理（线程安全：图片后台线程也会调用）"""
        with self._counter_lock:
            self._add_counter += 1
            if self._add_counter < 50:
                return
            self._add_counter = 0
        s = settings()
        self.repository.cleanup_old_items(s.max_items)
        if s.retention_days > 0:
            self.repository.cleanup_expired_items(s.retention_days)

    def start(self):
        if not self._monitoring:
            self._monitoring = True
            # 记录当前剪贴板内容，避免启动时重复保存
            self._last_text = self.clipboard.text()
            if _IS_MACOS:
                # macOS 下 dataChanged 可靠，用信号为主 + 低频兜底轮询，避免 App Nap 被阻止
                if not self._signal_connected:
                    self.clipboard.dataChanged.connect(self._poll_clipboard)
                    self._signal_connected = True
                self._poll_timer.start(_MACOS_FALLBACK_POLL_MS)
                logger.info("剪贴板监控已启动 (macOS 信号模式 + 低频兜底)")
            else:
                self._poll_timer.start(settings().poll_interval_ms)
                logger.info("剪贴板监控已启动 (轮询模式)")

    def update_poll_interval(self, interval_ms: int):
        """更新轮询间隔（毫秒）"""
        if self._monitoring:
            # macOS 下使用固定的兜底间隔，忽略用户设置
            if _IS_MACOS:
                return
            self._poll_timer.stop()
            self._poll_timer.start(interval_ms)

    def stop(self):
        if self._monitoring:
            self._monitoring = False
            self._poll_timer.stop()
            if _IS_MACOS and self._signal_connected:
                try:
                    self.clipboard.dataChanged.disconnect(self._poll_clipboard)
                except (TypeError, RuntimeError):
                    pass
                self._signal_connected = False
            # wait=False 避免与后台任务通过 QTimer 投递主线程产生死锁
            self._image_executor.shutdown(wait=False)
            logger.info("剪贴板监控已停止")

    def _poll_clipboard(self):
        if not self._monitoring:
            return

        try:
            mime_data = self.clipboard.mimeData()
            if mime_data is None:
                self._consecutive_failures = 0
                return

            # 单次快照供本 tick 全部分支使用,减少 RLock 往返
            s = settings()
            # Why: Finder 复制文件时剪贴板同时含 file:// URL 和文件图标预览图，
            # 必须先识别为"文件拷贝"走文本分支，否则图标会被当成图片存入历史。
            is_file_copy = mime_data.hasUrls() and any(
                u.isLocalFile() for u in mime_data.urls()
            )
            if is_file_copy:
                if mime_data.hasText() and s.save_text:
                    self._handle_text(s)
            elif mime_data.hasImage() and s.save_images:
                self._handle_image(s)
            elif mime_data.hasText() and s.save_text:
                self._handle_text(s)

            # 成功一次 → 重置失败计数
            if self._consecutive_failures or self._unhealthy_notified:
                self._consecutive_failures = 0
                self._unhealthy_notified = False

        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                logger.error(f"处理剪贴板内容时出错: {e}", exc_info=True)
            else:
                logger.debug(f"处理剪贴板内容再次出错 (#{self._consecutive_failures}): {e}")

            if (self._consecutive_failures >= self._UNHEALTHY_THRESHOLD
                    and not self._unhealthy_notified):
                self._unhealthy_notified = True
                msg = f"剪贴板监控异常，已连续失败 {self._consecutive_failures} 次"
                self.monitor_unhealthy.emit(msg)
                self.error_occurred.emit(msg)

            if self._consecutive_failures >= self._STOP_THRESHOLD:
                logger.error(
                    f"剪贴板监控连续失败 {self._consecutive_failures} 次，停止轮询"
                )
                self._poll_timer.stop()
                if _IS_MACOS and self._signal_connected:
                    try:
                        self.clipboard.dataChanged.disconnect(self._poll_clipboard)
                    except (TypeError, RuntimeError):
                        pass
                    self._signal_connected = False
                self._monitoring = False
                stop_msg = "剪贴板监控已停止，请重启应用或检查系统剪贴板权限"
                self.monitor_stopped.emit(stop_msg)
                self.error_occurred.emit(stop_msg)

    def _handle_text(self, s):
        text = self.clipboard.text()
        if not text or not text.strip():
            return

        # 检查是否和上次相同
        if text == self._last_text:
            return

        self._last_text = text

        if s.max_text_length > 0 and len(text) > s.max_text_length:
            logger.info(f"文本超过最大长度限制 ({len(text)} > {s.max_text_length})，跳过")
            return

        # Why: 日志文件可能被日志收集器、备份等路径读取；原始打印前 30 字符会
        # 把剪贴板中的 token/密码等敏感内容泄漏到明文日志。仅记录长度即可。
        logger.debug(f"检测到新文本: 长度 {len(text)} 字符")

        content_hash = compute_content_hash(text)

        now_ms = int(time.time() * 1000)

        # 检查是否已存在：重复内容刷新 created_at 并通知 UI 置顶
        existing = self.repository.get_by_hash(content_hash)
        if existing and existing.id:
            try:
                self.repository.touch_item(existing.id, now_ms)
                existing.created_at = now_ms
                self.item_added.emit(existing)
            except Exception as e:
                logger.warning(f"重复文本置顶失败: {e}")
            return

        source_app_value, source_title_value = _capture_source(
            getattr(s, "capture_source_title", False),
            self._source_app_seen_failures,
        )

        # P1.4: 敏感来源排除（如密码管理器、银行客户端）
        if _is_source_excluded(source_app_value, getattr(s, "excluded_source_apps", ())):
            logger.debug(f"来源 App {source_app_value!r} 在排除名单中,跳过记录")
            return

        item = TextClipboardItem(
            text_content=text,
            content_hash=content_hash,
            device_id=s.device_id,
            device_name=s.device_name,
            created_at=now_ms,
            source_app=source_app_value,
            source_title=source_title_value,
        )
        item.preview = item.get_display_preview()

        try:
            item_id = self.repository.add_item(item)
            item.id = item_id

            self._maybe_cleanup()

            logger.info(f"保存文本成功: id={item.id}")
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

    def _handle_image(self, s):
        image = self.clipboard.image()
        if image.isNull():
            return

        # 快速 hash 检测变化，避免每次都做 PNG 编码
        fast_hash = self._fast_image_hash(image)
        if fast_hash == self._last_image_hash:
            return

        self._last_image_hash = fast_hash

        # 将 QImage 转为原始 RGBA 字节（主线程，快速无压缩）
        width, height = image.width(), image.height()
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        bytes_per_line = image.bytesPerLine()
        expected_bpl = width * 4

        if bytes_per_line == expected_bpl:
            raw_bytes = bytes(image.constBits())
        else:
            # 有行填充，逐行复制去除 padding
            ptr = image.constBits()
            raw_bytes = b"".join(
                bytes(ptr[row * bytes_per_line: row * bytes_per_line + expected_bpl])
                for row in range(height)
            )

        # Why: 在主线程（信号触发点）捕获来源 App，保证拿到的是"复制瞬间"的前台窗口，
        # 而不是后台线程真正处理到这张图时的前台窗口。
        source_app_value, source_title_value = _capture_source(
            getattr(s, "capture_source_title", False),
            self._source_app_seen_failures,
        )

        # P1.4: 敏感来源排除（与文本路径一致）
        if _is_source_excluded(source_app_value, getattr(s, "excluded_source_apps", ())):
            logger.debug(f"图片来源 App {source_app_value!r} 在排除名单中,跳过记录")
            return

        logger.info(f"检测到新图片: {width}x{height}，提交后台处理")
        self._image_executor.submit(
            self._process_image_background, raw_bytes, width, height, s,
            source_app_value, source_title_value,
        )

    def _process_image_background(self, raw_bytes: bytes, width: int, height: int, s,
                                   source_app_value: str = "", source_title_value: str = ""):
        """后台线程：PNG 编码、缩略图生成、数据库写入"""
        try:
            # 延迟导入 PIL，缩短冷启动时间
            from PIL import Image
            pil_img = Image.frombytes("RGBA", (width, height), raw_bytes)
            image_data = image_to_bytes(pil_img, format="PNG")

            if not image_data:
                return

            if s.max_image_size_kb > 0 and len(image_data) > s.max_image_size_kb * 1024:
                logger.info(f"图片超过最大大小限制 ({len(image_data) // 1024}KB > {s.max_image_size_kb}KB)，跳过")
                return

            content_hash = compute_content_hash(image_data)

            now_ms = int(time.time() * 1000)

            # 检查是否已存在：重复图片刷新 created_at 并通知 UI 置顶
            existing = self.repository.get_by_hash(content_hash)
            if existing and existing.id:
                try:
                    self.repository.touch_item(existing.id, now_ms)
                    existing.created_at = now_ms
                    self.item_added.emit(existing)
                except Exception as e:
                    logger.warning(f"重复图片置顶失败: {e}")
                return

            # 创建缩略图
            try:
                thumbnail = create_thumbnail(image_data, THUMBNAIL_SIZE)
            except Exception as e:
                logger.warning(f"创建缩略图失败: {e}")
                thumbnail = None

            item = ImageClipboardItem(
                image_data=image_data,
                image_thumbnail=thumbnail,
                content_hash=content_hash,
                preview=f"[图片 {width}x{height}]",
                device_id=s.device_id,
                device_name=s.device_name,
                created_at=int(time.time() * 1000),
                source_app=source_app_value,
                source_title=source_title_value,
            )

            item_id = self.repository.add_item(item)
            item.id = item_id

            self._maybe_cleanup()

            logger.info(f"保存图片成功: {width}x{height}")
            self.item_added.emit(item)

        except Exception as e:
            logger.error(f"后台处理图片失败: {e}")
            self.error_occurred.emit(f"图片保存失败: {e}")

    def copy_to_clipboard(self, item: ClipboardItem) -> bool:
        if isinstance(item, TextClipboardItem) and item.text_content:
            self._last_text = item.text_content
            self.clipboard.setText(item.text_content)
            return True
        if isinstance(item, ImageClipboardItem) and item.image_data:
            image = QImage()
            image.loadFromData(item.image_data)
            # 使用 _fast_image_hash 计算 hash 以匹配 _handle_image 的检测逻辑
            self._last_image_hash = self._fast_image_hash(image)
            self.clipboard.setImage(image)
            return True
        return False
