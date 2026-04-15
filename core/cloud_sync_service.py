"""云端同步服务:通过 REST API 与云端服务器双向同步剪贴板数据。"""

import logging
import platform
from collections import deque
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer, QThread, Slot, QMetaObject, Qt

from .models import ClipboardItem, TextClipboardItem, ImageClipboardItem, ContentType
from .repository import ClipboardRepository
from .cloud_api import CloudAPIClient, CloudAPIError
from config import settings, update_settings, SYNC_INTERVAL_MS

logger = logging.getLogger(__name__)


class CloudSyncState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    AUTH_FAILED = "auth_failed"


class _SyncWorker(QObject):
    """在工作线程中执行同步 HTTP 请求，避免阻塞主线程"""
    pull_done = Signal(list, int)   # (new_items, max_server_id)
    pull_error = Signal(str, int)   # (message, status_code)
    push_done = Signal(int)         # uploaded_count
    push_error = Signal(str, int, list)  # (message, status_code, failed_batch)
    quota_warning = Signal(int, int)
    device_registered = Signal()    # 设备注册成功

    def __init__(self, cloud_api: CloudAPIClient, repository: ClipboardRepository):
        super().__init__()
        self.cloud_api = cloud_api
        self.repository = repository
        s = settings()
        self._device_id = s.device_id
        self._device_name = s.device_name

    @Slot(int)
    def do_pull(self, last_sync_id: int):
        """从云端拉取新记录（在工作线程中执行）"""
        try:
            data = self.cloud_api.sync(since_id=last_sync_id, device_id=self._device_id)
            items_data = data.get("items", [])

            # 第一遍：解析所有条目，收集 content_hash
            parsed_items = []
            skipped_server_ids = []
            for item_data in items_data:
                server_id = item_data.get("id", 0)
                item = self._server_item_to_local(item_data)
                if item is None:
                    logger.warning(f"跳过服务端条目 id={server_id}（解析或图片下载失败，下次同步将重试）")
                    # 记录跳过的 server_id，用于限制 max_server_id 不越过它
                    if server_id:
                        skipped_server_ids.append(server_id)
                    # 多次失败后登记到永久跳过集合，避免无限阻塞同步游标
                    self._register_skip(server_id)
                    continue
                parsed_items.append((server_id, item))

            # 批量查询已存在的 hash（替代逐条 get_by_hash，减少 N 次查询为 1 次）
            all_hashes = [item.content_hash for _, item in parsed_items]
            existing_map = self.repository.get_existing_hashes(all_hashes)

            new_items = []
            cloud_id_pairs = []
            max_server_id = last_sync_id

            for server_id, item in parsed_items:
                existing = existing_map.get(item.content_hash)
                if existing is None:
                    item_id = self.repository.add_item(item)
                    item.id = item_id
                    new_items.append(item)
                    if server_id and item_id:
                        cloud_id_pairs.append((item_id, server_id))
                elif not existing.is_cloud_synced and server_id:
                    cloud_id_pairs.append((existing.id, server_id))

                if server_id > max_server_id:
                    max_server_id = server_id

            # 若存在跳过的条目，游标只能推进到最小跳过 id - 1（避免越过重试目标）
            # 但若该条目已被标记为“永久放弃”（超过重试次数），则允许越过
            min_retryable_skip = min(
                (sid for sid in skipped_server_ids if not self._is_permanently_skipped(sid)),
                default=None,
            )
            if min_retryable_skip is not None:
                max_server_id = min(max_server_id, min_retryable_skip - 1)
                if max_server_id < last_sync_id:
                    max_server_id = last_sync_id

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
            # 转换为上传格式(根据子类决定 text_content 字段)
            upload_items = []
            image_items = []
            for item in batch:
                item_dict = {
                    "content_type": item.content_type.value,
                    "text_content": item.text_content if isinstance(item, TextClipboardItem) else None,
                    "content_hash": item.content_hash,
                    "preview": item.preview or "",
                    "device_id": item.device_id,
                    "device_name": item.device_name,
                    "created_at": item.created_at,
                    "is_starred": item.is_starred,
                }
                upload_items.append(item_dict)
                if isinstance(item, ImageClipboardItem) and item.image_data:
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
    def _do_register_device(self):
        """在工作线程中注册设备"""
        try:
            success = self.cloud_api.register_device(
                device_id=self._device_id,
                device_name=self._device_name,
                platform=platform.system(),
            )
            if success:
                logger.info(f"设备已注册: {self._device_name}")
                self.device_registered.emit()
        except CloudAPIError as e:
            logger.warning(f"设备注册失败: {e}")

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

    # 图片下载失败重试计数：{server_id: fail_count}
    # 超过 _MAX_IMAGE_RETRY 次后视为永久放弃，允许同步游标越过
    _MAX_IMAGE_RETRY = 5

    def _server_item_to_local(self, data: dict) -> Optional[ClipboardItem]:
        """将服务端返回的 item 数据转换为本地 ClipboardItem

        根据服务端 content_type 分派到 TextClipboardItem / ImageClipboardItem 子类。
        图片类型下载失败时返回 None（调用方会跳过该条目且不推进游标，下次重试）
        """
        try:
            content_type_str = data.get("content_type", "text")
            content_type = ContentType(content_type_str)

            # 共享元数据（基类字段），供子类构造复用
            common_kwargs = dict(
                content_hash=data.get("content_hash", ""),
                preview=data.get("preview", ""),
                device_id=data.get("device_id", ""),
                device_name=data.get("device_name", ""),
                created_at=data.get("created_at", 0),
                is_starred=data.get("is_starred", False),
            )

            if content_type == ContentType.TEXT:
                return TextClipboardItem(
                    **common_kwargs,
                    text_content=data.get("text_content") or "",
                )

            # 图片条目：先构造空 image_data 占位，再尝试下载
            item = ImageClipboardItem(
                **common_kwargs,
                image_data=None,
                image_thumbnail=None,
            )
            server_id = data.get("id")
            if not server_id:
                logger.warning("服务端图片条目缺少 id，无法下载")
                return None
            if not self._download_image(item, server_id):
                # 下载失败且未达到永久放弃阈值 → 返回 None，下次重试
                if not self._is_permanently_skipped(server_id):
                    return None
                # 已达阈值：允许进入本地库（preview 至少保留），
                # 避免同步游标被永久卡住；但 image_data 仍为 None
                logger.error(
                    f"图片下载持续失败达 {self._MAX_IMAGE_RETRY} 次 (server_id={server_id})，放弃重试并写入空图片占位"
                )

            return item
        except Exception as e:
            logger.error(f"转换服务端数据失败: {e}, data={data}")
            return None

    def _download_image(self, item: ImageClipboardItem, server_id: int) -> bool:
        """下载云端图片；成功返回 True，失败返回 False

        签名改为 ImageClipboardItem：image_data/image_thumbnail 仅该子类拥有。
        """
        try:
            image_data = self.cloud_api.download_image(server_id)
            if image_data:
                item.image_data = image_data
                from utils.image_utils import create_thumbnail
                item.image_thumbnail = create_thumbnail(image_data)
                return True
            logger.warning(f"下载云端图片为空 (server_id={server_id})")
            return False
        except Exception as e:
            logger.warning(f"下载云端图片失败 (server_id={server_id}): {e}")
            return False

    def _register_skip(self, server_id: int):
        """记录某 server_id 因图片/解析失败被跳过的次数"""
        if not server_id:
            return
        counter = getattr(self, '_skip_retry_counter', None)
        if counter is None:
            counter = {}
            self._skip_retry_counter = counter
        counter[server_id] = counter.get(server_id, 0) + 1

    def _is_permanently_skipped(self, server_id: int) -> bool:
        """判断某 server_id 是否已达永久放弃阈值"""
        if not server_id:
            return True
        counter = getattr(self, '_skip_retry_counter', {})
        return counter.get(server_id, 0) >= self._MAX_IMAGE_RETRY

    def _upload_image_for_item(self, item: ImageClipboardItem, server_id: int):
        """上传图片到云端（仅对 ImageClipboardItem 调用，调用方已做类型过滤）"""
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
    queue_overflow = Signal(int)         # 离线队列溢出，参数为被丢弃的条目 id

    # 内部信号：跨线程调度 worker 方法（避免 Q_ARG 不支持 list 类型）
    _trigger_push = Signal(list)
    _trigger_pull = Signal(int)

    # 自适应轮询参数（与 SyncService 一致）
    _MIN_INTERVAL_MS = 1000
    _MAX_INTERVAL_MS = 30000
    _INTERVAL_STEP_MS = 2000

    # 上传批次大小
    _UPLOAD_BATCH_SIZE = 20

    def __init__(self, repository: ClipboardRepository, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.cloud_api = cloud_api
        s = settings()
        self._device_id = s.device_id
        self._device_name = s.device_name
        self._last_sync_id = s.cloud_last_sync_id
        self._state: CloudSyncState = CloudSyncState.STOPPED
        self._current_interval = self._MIN_INTERVAL_MS
        self._pulling = False  # 正交的 in-flight 标志:拉取请求是否在途
        self._pushing = False  # 同上,推送请求

        # 待上传队列（离线队列）— 仅存新增条目，保证新数据不被失败重试挤出
        self._pending_upload_queue: deque = deque(maxlen=500)
        # 失败重试队列 — 独立 maxlen，溢出时丢弃最旧重试项而非新数据
        self._retry_queue: deque = deque(maxlen=50)
        self._dropped_count = 0  # 累计被离线队列挤出的条目数，仅用于告警节流

        # 工作线程 — HTTP 请求不再阻塞主线程
        self._worker_thread = QThread(self)
        self._worker = _SyncWorker(cloud_api, repository)
        self._worker.moveToThread(self._worker_thread)
        self._worker.pull_done.connect(self._on_pull_done)
        self._worker.pull_error.connect(self._on_pull_error)
        self._worker.push_done.connect(self._on_push_done)
        self._worker.push_error.connect(self._on_push_error)
        self._worker.quota_warning.connect(self.quota_warning)
        self._worker.device_registered.connect(lambda: setattr(self, '_device_registered', True))
        # 用信号槽替代 QMetaObject.invokeMethod + Q_ARG 传递 list
        self._trigger_push.connect(self._worker.do_push, Qt.QueuedConnection)
        self._trigger_pull.connect(self._worker.do_pull, Qt.QueuedConnection)
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

    @property
    def state(self) -> CloudSyncState:
        return self._state

    def _transition(self, new_state: CloudSyncState) -> None:
        if new_state != self._state:
            logger.debug(f"CloudSyncService: {self._state.value} -> {new_state.value}")
            self._state = new_state

    def start(self, interval_ms: int = None):
        """启动云端同步服务"""
        if interval_ms is None:
            interval_ms = SYNC_INTERVAL_MS

        if self._state != CloudSyncState.STOPPED:
            logger.debug(f"CloudSyncService.start 被忽略,当前状态: {self._state.value}")
            return

        self._transition(CloudSyncState.RUNNING)

        # 注册设备
        self._register_device()

        # 启动拉取定时器
        self._pull_timer.start(interval_ms)

        # 推送定时器间隔为拉取的 2 倍
        self._push_timer.start(interval_ms * 2)

        logger.info(f"云端同步服务已启动,拉取间隔 {interval_ms}ms")

    def stop(self):
        """停止云端同步服务"""
        if self._state == CloudSyncState.STOPPED:
            return
        self._transition(CloudSyncState.STOPPED)
        self._pull_timer.stop()
        self._push_timer.stop()
        # 退出时才落盘游标,避免热路径每秒 serialize 全量 settings
        update_settings(cloud_last_sync_id=self._last_sync_id)
        self._worker_thread.quit()
        self._worker_thread.wait(3000)
        logger.info("云端同步服务已停止")

    def force_sync(self):
        """强制立即同步(拉取 + 推送)"""
        if self._state != CloudSyncState.RUNNING:
            logger.debug(f"force_sync 被忽略,当前状态: {self._state.value}")
            return
        self._pulling = False
        self._pushing = False
        self._pull_from_cloud()
        self._push_to_cloud()

    def reset_sync_position(self):
        """重置同步位置"""
        self._last_sync_id = 0
        update_settings(cloud_last_sync_id=0)
        logger.info("云端同步位置已重置")

    def enqueue_upload(self, item: ClipboardItem):
        """将新条目加入上传队列；队列满时最旧条目被挤出并上报告警"""
        if len(self._pending_upload_queue) >= self._pending_upload_queue.maxlen:
            dropped = self._pending_upload_queue[0]
            self._dropped_count += 1
            logger.warning(
                f"离线上传队列已满 ({self._pending_upload_queue.maxlen})，丢弃最旧条目 id={dropped.id}，累计丢弃 {self._dropped_count}"
            )
            self.queue_overflow.emit(dropped.id or 0)
        self._pending_upload_queue.append(item)

    # ========== 设备注册 ==========

    def _register_device(self):
        """向云端注册当前设备（在工作线程执行，避免阻塞启动）"""
        if self._device_registered:
            return
        QMetaObject.invokeMethod(
            self._worker, "_do_register_device", Qt.QueuedConnection,
        )

    # ========== 拉取逻辑 ==========

    def _pull_from_cloud(self):
        """从云端拉取新记录(主线程调度,实际 HTTP 在工作线程执行)"""
        if self._state != CloudSyncState.RUNNING or self._pulling:
            return
        self._pulling = True
        self._trigger_pull.emit(self._last_sync_id)

    @Slot(list, int)
    def _on_pull_done(self, new_items: list, max_server_id: int):
        """拉取完成回调（主线程）。
        游标只更新内存, 由 stop() 统一落盘, 避免每秒一次 settings 全量对比。"""
        self._pulling = False
        if max_server_id > self._last_sync_id:
            self._last_sync_id = max_server_id

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
        """拉取失败回调(主线程)"""
        self._pulling = False
        if status_code == 401:
            logger.warning("云端认证失败,请重新登录")
            # 停止轮询,避免反复刷 401 日志
            self._pull_timer.stop()
            self._push_timer.stop()
            self._transition(CloudSyncState.AUTH_FAILED)
            self.sync_error.emit("云端认证失败,请在设置中重新登录")
        else:
            logger.error(f"云端拉取失败: {message}")
            self.sync_error.emit(message)

    def restart_after_reauth(self):
        """重新登录后恢复同步定时器"""
        if self._state != CloudSyncState.AUTH_FAILED:
            return
        self._transition(CloudSyncState.RUNNING)
        self._current_interval = self._MIN_INTERVAL_MS
        self._pull_timer.setInterval(self._current_interval)
        self._pull_timer.start()
        self._push_timer.start()
        logger.info("认证恢复,同步定时器已重启")

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
        """将本地待上传条目推送到云端(主线程调度,实际 HTTP 在工作线程执行)"""
        if self._state != CloudSyncState.RUNNING or self._pushing:
            return
        if not self._pending_upload_queue and not self._retry_queue:
            return

        self._pushing = True

        # 每 10 次推送检查一次配额
        self._quota_check_counter += 1
        if self._quota_check_counter % 10 == 1:
            QMetaObject.invokeMethod(self._worker, "do_check_quota", Qt.QueuedConnection)

        # 优先处理重试队列，其次新数据
        batch = []
        while self._retry_queue and len(batch) < self._UPLOAD_BATCH_SIZE:
            batch.append(self._retry_queue.popleft())
        while self._pending_upload_queue and len(batch) < self._UPLOAD_BATCH_SIZE:
            batch.append(self._pending_upload_queue.popleft())

        self._trigger_push.emit(batch)

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
            # 失败批次进入独立 retry_queue，不挤占新数据队列
            retry_max = self._retry_queue.maxlen
            for item in failed_batch:
                if len(self._retry_queue) >= retry_max:
                    # retry_queue 已满，丢弃最旧重试项
                    dropped = self._retry_queue.popleft()
                    self._dropped_count += 1
                    logger.warning(
                        f"重试队列已满 ({retry_max})，丢弃最旧重试项 id={getattr(dropped, 'id', None)}，累计丢弃 {self._dropped_count}"
                    )
                    self.queue_overflow.emit(getattr(dropped, 'id', 0) or 0)
                self._retry_queue.append(item)
        self.sync_error.emit(f"上传失败: {message}")
