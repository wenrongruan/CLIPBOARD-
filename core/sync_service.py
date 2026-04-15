"""本地同步服务:轮询共享数据库,拉取其他设备写入的条目。"""

import logging
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer

from .models import ClipboardItem
from .repository import ClipboardRepository
from config import settings, update_settings, SYNC_INTERVAL_MS

logger = logging.getLogger(__name__)


class SyncState(Enum):
    STOPPED = "stopped"
    UNINITIALIZED = "uninitialized"
    POLLING_FAST = "polling_fast"
    POLLING_SLOW = "polling_slow"


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
        s = settings()
        self._last_sync_id = s.last_sync_id
        self._device_id = s.device_id
        self._state: SyncState = SyncState.STOPPED
        self._current_interval = self._MIN_INTERVAL_MS

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._check_for_updates)

    @property
    def state(self) -> SyncState:
        return self._state

    def _transition(self, new_state: SyncState) -> None:
        if new_state != self._state:
            logger.debug(f"SyncService: {self._state.value} -> {new_state.value}")
            self._state = new_state

    def start(self, interval_ms: Optional[int] = None):
        if self._state != SyncState.STOPPED:
            logger.debug(f"SyncService.start 被忽略,当前状态: {self._state.value}")
            return
        if interval_ms is None:
            interval_ms = SYNC_INTERVAL_MS

        # 启动时获取最新ID,把游标对齐到当前库尾,避免首轮把历史条目全当新数据
        try:
            latest_id = self.repository.get_latest_id()
            if latest_id > self._last_sync_id:
                self._last_sync_id = latest_id
            self._transition(SyncState.POLLING_FAST)
        except Exception as e:
            self._transition(SyncState.UNINITIALIZED)
            logger.warning(
                f"获取最新ID失败,同步服务将在下一轮重试初始化,避免重复推送历史条目: {e}"
            )

        self._current_interval = self._MIN_INTERVAL_MS
        self._sync_timer.start(interval_ms)
        logger.info(f"同步服务已启动,间隔 {interval_ms}ms")

    def stop(self):
        if self._state == SyncState.STOPPED:
            return
        self._sync_timer.stop()
        # 退出时才落盘游标,避免热路径每秒 serialize 全量 settings
        update_settings(last_sync_id=self._last_sync_id)
        self._transition(SyncState.STOPPED)
        logger.info("同步服务已停止")

    def _check_for_updates(self):
        if self._state == SyncState.STOPPED:
            return

        # 启动初始化失败的情况下,每轮重试一次,避免把全部历史条目视为新数据
        if self._state == SyncState.UNINITIALIZED:
            try:
                latest_id = self.repository.get_latest_id()
                if latest_id > self._last_sync_id:
                    self._last_sync_id = latest_id
                self._transition(SyncState.POLLING_FAST)
                logger.info("同步服务延迟初始化成功")
            except Exception as e:
                logger.warning(f"同步服务尚未就绪,跳过本轮同步: {e}")
                return

        try:
            new_items = self.repository.get_new_items_since(
                self._last_sync_id, self._device_id
            )

            if new_items:
                self._last_sync_id = max(item.id for item in new_items)
                logger.debug(f"发现 {len(new_items)} 条来自其他设备的新记录")
                self.new_items_available.emit(new_items)

                # 有新数据,重置为最短间隔并进入 FAST 状态
                if self._current_interval != self._MIN_INTERVAL_MS:
                    self._current_interval = self._MIN_INTERVAL_MS
                    self._sync_timer.setInterval(self._current_interval)
                self._transition(SyncState.POLLING_FAST)
            else:
                new_interval = min(
                    self._current_interval + self._INTERVAL_STEP_MS,
                    self._MAX_INTERVAL_MS,
                )
                if new_interval != self._current_interval:
                    self._current_interval = new_interval
                    self._sync_timer.setInterval(self._current_interval)
                # 一旦退避过就进入 SLOW 状态(直到有新数据才回 FAST)
                if self._current_interval > self._MIN_INTERVAL_MS:
                    self._transition(SyncState.POLLING_SLOW)

        except Exception as e:
            logger.error(f"同步检查失败: {e}")
            self.sync_error.emit(str(e))

    def force_sync(self):
        if self._state == SyncState.STOPPED:
            return
        self._check_for_updates()

    def advance_sync_id(self, new_id: int):
        """将同步游标前进到指定 ID,避免已知条目被重复通知。
        内存状态权威,落盘在 stop() 统一处理,避免热路径全量 settings 比较。"""
        if new_id > self._last_sync_id:
            self._last_sync_id = new_id

    def reset_sync_position(self):
        self._last_sync_id = 0
        update_settings(last_sync_id=0)
        logger.info("同步位置已重置")
