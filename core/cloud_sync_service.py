"""云端同步服务 — 通过 REST API 与云端服务器双向同步剪贴板数据"""

import logging
import platform
from collections import deque
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer, QThread, Slot, QMetaObject, Qt, Q_ARG

from .models import ClipboardItem, ContentType
from .repository import ClipboardRepository
from .cloud_api import CloudAPIClient, CloudAPIError
from config import Config

logger = logging.getLogger(__name__)


class _SyncWorker(QObject):
    """在工作线程中执行同步 HTTP 请求，避免阻塞主线程"""
    pull_done = Signal(list, int)   # (new_items, max_server_id)
    pull_error = Signal(str, int)   # (message, status_code)
    push_done = Signal(int)         # uploaded_count
    push_error = Signal(str, int, list)  # (message, status_code, failed_batch)
    quota_warning = Signal(int, int)

    def __init__(self, cloud_api: CloudAPIClient, repository: ClipboardRepository):
        super().__init__()
        self.cloud_api = cloud_api
        self.repository = repository
        self._device_id = Config.get_device_id()
        self._device_name = Config.get_device_name()

    @Slot(int)
    def do_pull(self, last_sync_id: int):
        """从云端拉取新记录（在工作线程中执行）"""
        try:
            data = self.cloud_api.sync(since_id=last_sync_id, device_id=self._device_id)
            items_data = data.get("items", [])

            new_items = []
            cloud_id_pairs = []
            max_server_id = last_sync_id

            for item_data in items_data:
                server_id = item_data.get("id", 0)
                item = self._server_item_to_local(item_data)
                if item is None:
                    # 解析失败：不更新 sync_id，防止数据丢失
                    logger.warning(f"跳过无法解析的服务端条目 id={server_id}")
                    continue

                existing = self.repository.get_by_hash(item.content_hash)
                if existing is None:
                    item_id = self.repository.add_item(item)
                    item.id = item_id
                    new_items.append(item)
                    if server_id and item_id:
                        cloud_id_pairs.append((item_id, server_id))
                elif existing and not existing.is_cloud_synced and server_id:
                    cloud_id_pairs.append((existing.id, server_id))

                # 只在成功解析后才更新 max_server_id
                if server_id > max_server_id:
                    max_server_id = server_id

            self.repository.set_cloud_ids_bulk(cloud_id_pairs)
            self.pull_done.emit(new_items, max_server_id)

        except CloudAPIError as e:
            self.pull_error.emit(str(e), e.status_code)
        except Exception as e:
            logger.error(f"云端同步检查失败: {e}")
            self.pull_error.emit(str(e), 0)

    @Slot(list)
    def do_push(self, batch: list):
        """将本地条目推送到云端（在工作线程中执行）"""
        try:
            # 转换为上传格式
            upload_items = []
            image_items = []
            for item in batch:
                item_dict = {
                    "content_type": item.content_type.value,
                    "text_content": item.text_content,
                    "content_hash": item.content_hash,
                    "preview": item.preview or "",
                    "device_id": item.device_id,
                    "device_name": item.device_name,
                    "created_at": item.created_at,
                    "is_starred": item.is_starred,
                }
                upload_items.append(item_dict)
                if item.is_image and item.image_data:
                    image_items.append(item)

            server_items = self.cloud_api.upload_items(upload_items)

            hash_to_server_id = {}
            if server_items:
                for si in server_items:
                    h = si.get("content_hash", "")
                    sid = si.get("id")
                    if h and sid:
                        hash_to_server_id[h] = sid

            cloud_id_pairs = [
                (item.id, hash_to_server_id[item.content_hash])
                for item in batch
                if item.id and item.content_hash in hash_to_server_id
            ]
            self.repository.set_cloud_ids_bulk(cloud_id_pairs)

            for item in image_items:
                server_id = hash_to_server_id.get(item.content_hash)
                if server_id:
                    self._upload_image_for_item(item, server_id)

            uploaded_count = len(server_items) if server_items else len(batch)
            self.push_done.emit(uploaded_count)

        except CloudAPIError as e:
            self.push_error.emit(str(e), e.status_code, batch)
        except Exception as e:
            logger.error(f"云端推送异常: {e}")
            self.push_error.emit(str(e), 0, batch)

    @Slot()
    def do_check_quota(self):
        """检查配额（在工作线程中执行）"""
        try:
            sub = self.cloud_api.get_subscription()
            current = sub.get("used_records", 0)
            max_count = sub.get("max_records", 30)
            if max_count > 0 and current >= max_count * 0.8:
                self.quota_warning.emit(current, max_count)
        except CloudAPIError as e:
            logger.debug(f"配额检查失败: {e}")

    def _server_item_to_local(self, data: dict) -> Optional[ClipboardItem]:
        """将服务端返回的 item 数据转换为本地 ClipboardItem"""
        try:
            content_type_str = data.get("content_type", "text")
            content_type = ContentType(content_type_str)

            item = ClipboardItem(
                content_type=content_type,
                text_content=data.get("text_content"),
                image_data=None,
                image_thumbnail=None,
                content_hash=data.get("content_hash", ""),
                preview=data.get("preview", ""),
                device_id=data.get("device_id", ""),
                device_name=data.get("device_name", ""),
                created_at=data.get("created_at", 0),
                is_starred=data.get("is_starred", False),
            )

            if content_type == ContentType.IMAGE:
                server_id = data.get("id")
                if server_id:
                    self._download_image(item, server_id)

            return item
        except Exception as e:
            logger.error(f"转换服务端数据失败: {e}, data={data}")
            return None

    def _download_image(self, item: ClipboardItem, server_id: int):
        try:
            image_data = self.cloud_api.download_image(server_id)
            if image_data:
                item.image_data = image_data
                from utils.image_utils import create_thumbnail
                item.image_thumbnail = create_thumbnail(image_data)
        except Exception as e:
            logger.warning(f"下载云端图片失败 (server_id={server_id}): {e}")

    def _upload_image_for_item(self, item: ClipboardItem, server_id: int):
        if not item.image_data:
            return
        try:
            from utils.image_utils import compress_for_cloud
            compressed = compress_for_cloud(item.image_data)
            self.cloud_api.upload_image(server_id, compressed)
        except CloudAPIError as e:
            logger.warning(f"图片上传失败 (server_id={server_id}): {e}")


class CloudSyncService(QObject):
    """
    云端同步服务。
    信号接口与 SyncService 完全一致，确保 MainWindow 无需修改。
    """

    # 与 SyncService 相同的信号
    new_items_available = Signal(list)  # List[ClipboardItem]
    sync_error = Signal(str)

    # 云端特有信号
    upload_completed = Signal(int)       # 上传成功的 item 数量
    quota_warning = Signal(int, int)     # (当前已用, 最大额度)

    # 自适应轮询参数（与 SyncService 一致）
    _MIN_INTERVAL_MS = 1000
    _MAX_INTERVAL_MS = 10000
    _INTERVAL_STEP_MS = 1000

    # 上传批次大小
    _UPLOAD_BATCH_SIZE = 20

    def __init__(self, repository: ClipboardRepository, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.cloud_api = cloud_api
        self._device_id = Config.get_device_id()
        self._device_name = Config.get_device_name()
        self._last_sync_id = Config.get_cloud_last_sync_id()
        self._running = False
        self._current_interval = self._MIN_INTERVAL_MS
        self._pulling = False  # 防止重叠请求
        self._pushing = False

        # 待上传队列（离线队列）
        self._pending_upload_queue: deque = deque(maxlen=500)

        # 工作线程 — HTTP 请求不再阻塞主线程
        self._worker_thread = QThread(self)
        self._worker = _SyncWorker(cloud_api, repository)
        self._worker.moveToThread(self._worker_thread)
        self._worker.pull_done.connect(self._on_pull_done)
        self._worker.pull_error.connect(self._on_pull_error)
        self._worker.push_done.connect(self._on_push_done)
        self._worker.push_error.connect(self._on_push_error)
        self._worker.quota_warning.connect(self.quota_warning)
        self._worker_thread.start()

        # 拉取定时器
        self._pull_timer = QTimer(self)
        self._pull_timer.timeout.connect(self._pull_from_cloud)

        # 推送定时器（间隔稍长，减少请求频率）
        self._push_timer = QTimer(self)
        self._push_timer.timeout.connect(self._push_to_cloud)

        # 注册设备（首次连接时）
        self._device_registered = False
        self._quota_check_counter = 0

    def start(self, interval_ms: int = None):
        """启动云端同步服务"""
        if interval_ms is None:
            interval_ms = Config.SYNC_INTERVAL_MS

        if not self._running:
            self._running = True

            # 注册设备
            self._register_device()

            # 启动拉取定时器
            self._pull_timer.start(interval_ms)

            # 推送定时器间隔为拉取的 2 倍
            self._push_timer.start(interval_ms * 2)

            logger.info(f"云端同步服务已启动，拉取间隔 {interval_ms}ms")

    def stop(self):
        """停止云端同步服务"""
        if self._running:
            self._running = False
            self._pull_timer.stop()
            self._push_timer.stop()
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
            logger.info("云端同步服务已停止")

    def force_sync(self):
        """强制立即同步（拉取 + 推送）"""
        self._pulling = False
        self._pushing = False
        self._pull_from_cloud()
        self._push_to_cloud()

    def reset_sync_position(self):
        """重置同步位置"""
        self._last_sync_id = 0
        Config.set_cloud_last_sync_id(0)
        logger.info("云端同步位置已重置")

    def enqueue_upload(self, item: ClipboardItem):
        """将新条目加入上传队列"""
        self._pending_upload_queue.append(item)

    # ========== 设备注册 ==========

    def _register_device(self):
        """向云端注册当前设备"""
        if self._device_registered:
            return
        try:
            success = self.cloud_api.register_device(
                device_id=self._device_id,
                device_name=self._device_name,
                platform=platform.system(),
            )
            if success:
                self._device_registered = True
                logger.info(f"设备已注册: {self._device_name}")
        except CloudAPIError as e:
            logger.warning(f"设备注册失败: {e}")

    # ========== 拉取逻辑 ==========

    def _pull_from_cloud(self):
        """从云端拉取新记录（主线程调度，实际 HTTP 在工作线程执行）"""
        if not self._running or self._pulling:
            return
        self._pulling = True
        QMetaObject.invokeMethod(
            self._worker, "do_pull", Qt.QueuedConnection,
            Q_ARG(int, self._last_sync_id),
        )

    @Slot(list, int)
    def _on_pull_done(self, new_items: list, max_server_id: int):
        """拉取完成回调（主线程）"""
        self._pulling = False
        if max_server_id > self._last_sync_id:
            self._last_sync_id = max_server_id
            Config.set_cloud_last_sync_id(self._last_sync_id)

        if new_items:
            logger.debug(f"从云端拉取了 {len(new_items)} 条新记录")
            self.new_items_available.emit(new_items)
            if self._current_interval != self._MIN_INTERVAL_MS:
                self._current_interval = self._MIN_INTERVAL_MS
                self._pull_timer.setInterval(self._current_interval)
        else:
            self._increase_interval()

    @Slot(str, int)
    def _on_pull_error(self, message: str, status_code: int):
        """拉取失败回调（主线程）"""
        self._pulling = False
        if status_code == 401:
            logger.warning("云端认证失败，请重新登录")
            self.sync_error.emit("云端认证失败，请在设置中重新登录")
        else:
            logger.error(f"云端拉取失败: {message}")
            self.sync_error.emit(message)

    def _increase_interval(self):
        """无新数据时，逐步增加轮询间隔"""
        new_interval = min(
            self._current_interval + self._INTERVAL_STEP_MS,
            self._MAX_INTERVAL_MS,
        )
        if new_interval != self._current_interval:
            self._current_interval = new_interval
            self._pull_timer.setInterval(self._current_interval)

    # ========== 推送逻辑 ==========

    def _push_to_cloud(self):
        """将本地待上传条目推送到云端（主线程调度，实际 HTTP 在工作线程执行）"""
        if not self._running or not self._pending_upload_queue or self._pushing:
            return

        self._pushing = True

        # 每 10 次推送检查一次配额
        self._quota_check_counter += 1
        if self._quota_check_counter % 10 == 1:
            QMetaObject.invokeMethod(self._worker, "do_check_quota", Qt.QueuedConnection)

        # 取一批数据
        batch = []
        while self._pending_upload_queue and len(batch) < self._UPLOAD_BATCH_SIZE:
            batch.append(self._pending_upload_queue.popleft())

        QMetaObject.invokeMethod(
            self._worker, "do_push", Qt.QueuedConnection,
            Q_ARG(list, batch),
        )

    @Slot(int)
    def _on_push_done(self, uploaded_count: int):
        """推送完成回调（主线程）"""
        self._pushing = False
        self.upload_completed.emit(uploaded_count)
        logger.debug(f"成功上传 {uploaded_count} 条记录到云端")

    @Slot(str, int, list)
    def _on_push_error(self, message: str, status_code: int, failed_batch: list):
        """推送失败回调（主线程）"""
        self._pushing = False
        logger.error(f"云端推送失败: {message}")
        # 配额不足时不重试
        if status_code != 403:
            for item in reversed(failed_batch):
                self._pending_upload_queue.appendleft(item)
        self.sync_error.emit(f"上传失败: {message}")
