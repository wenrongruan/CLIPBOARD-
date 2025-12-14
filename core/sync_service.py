import logging
from typing import List

from PySide6.QtCore import QObject, Signal, QTimer

from .models import ClipboardItem
from .repository import ClipboardRepository
from config import Config

logger = logging.getLogger(__name__)


class SyncService(QObject):
    new_items_available = Signal(list)  # List[ClipboardItem]
    sync_error = Signal(str)

    def __init__(self, repository: ClipboardRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self._last_sync_id = Config.get_last_sync_id()
        self._device_id = Config.get_device_id()
        self._running = False

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._check_for_updates)

    def start(self, interval_ms: int = None):
        if interval_ms is None:
            interval_ms = Config.SYNC_INTERVAL_MS

        if not self._running:
            self._running = True
            # 初始化时获取最新ID
            try:
                latest_id = self.repository.get_latest_id()
                if latest_id > self._last_sync_id:
                    self._last_sync_id = latest_id
                    Config.set_last_sync_id(latest_id)
            except Exception as e:
                logger.warning(f"获取最新ID失败: {e}")

            self._sync_timer.start(interval_ms)
            logger.info(f"同步服务已启动，间隔 {interval_ms}ms")

    def stop(self):
        if self._running:
            self._running = False
            self._sync_timer.stop()
            logger.info("同步服务已停止")

    def _check_for_updates(self):
        if not self._running:
            return

        try:
            new_items = self.repository.get_new_items_since(
                self._last_sync_id, self._device_id
            )

            if new_items:
                # 更新同步ID
                self._last_sync_id = max(item.id for item in new_items)
                Config.set_last_sync_id(self._last_sync_id)

                logger.debug(f"发现 {len(new_items)} 条来自其他设备的新记录")
                self.new_items_available.emit(new_items)

        except Exception as e:
            logger.error(f"同步检查失败: {e}")
            self.sync_error.emit(str(e))

    def force_sync(self):
        self._check_for_updates()

    def reset_sync_position(self):
        self._last_sync_id = 0
        Config.set_last_sync_id(0)
        logger.info("同步位置已重置")
