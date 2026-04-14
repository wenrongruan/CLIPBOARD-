import logging
from enum import Enum
from typing import List

from PySide6.QtCore import QObject, Signal, QTimer

from .models import ClipboardItem
from .repository import ClipboardRepository
from config import Config

logger = logging.getLogger(__name__)


class SyncState(Enum):
    STOPPED = "stopped"
    POLLING_FAST = "polling_fast"  # 最短轮询间隔（有新数据）
    POLLING_SLOW = "polling_slow"  # 已退避到较长间隔


class SyncService(QObject):
    new_items_available = Signal(list)  # List[ClipboardItem]
    sync_error = Signal(str)

    # 自适应轮询参数
    _MIN_INTERVAL_MS = 1000   # 有新数据时重置到 1s
    _MAX_INTERVAL_MS = 30000  # 无新数据时最大间隔 30s
    _INTERVAL_STEP_MS = 2000  # 每次无数据增加 2s

    def __init__(self, repository: ClipboardRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self._last_sync_id = Config.get_last_sync_id()
        self._device_id = Config.get_device_id()
        self._running = False
        self._current_interval = self._MIN_INTERVAL_MS

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._check_for_updates)

    @property
    def state(self) -> SyncState:
        if not self._running:
            return SyncState.STOPPED
        if self._current_interval == self._MIN_INTERVAL_MS:
            return SyncState.POLLING_FAST
        return SyncState.POLLING_SLOW

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

                # 有新数据，重置为最短间隔
                if self._current_interval != self._MIN_INTERVAL_MS:
                    self._current_interval = self._MIN_INTERVAL_MS
                    self._sync_timer.setInterval(self._current_interval)
            else:
                # 无新数据，逐步增加间隔
                new_interval = min(
                    self._current_interval + self._INTERVAL_STEP_MS,
                    self._MAX_INTERVAL_MS,
                )
                if new_interval != self._current_interval:
                    self._current_interval = new_interval
                    self._sync_timer.setInterval(self._current_interval)

        except Exception as e:
            logger.error(f"同步检查失败: {e}")
            self.sync_error.emit(str(e))

    def force_sync(self):
        self._check_for_updates()

    def advance_sync_id(self, new_id: int):
        """将同步游标前进到指定 ID，避免已知条目被重复通知"""
        if new_id > self._last_sync_id:
            self._last_sync_id = new_id
            Config.set_last_sync_id(new_id)

    def reset_sync_position(self):
        self._last_sync_id = 0
        Config.set_last_sync_id(0)
        logger.info("同步位置已重置")
