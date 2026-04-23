"""云端同步服务:通过 REST API 与云端服务器双向同步剪贴板数据。"""

import json
import logging
import platform
import time
from collections import deque
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer, QThread, Slot, QMetaObject, Qt

from .models import ClipboardItem, TextClipboardItem, ImageClipboardItem, ContentType
from .repository import ClipboardRepository
from .cloud_api import CloudAPIClient, CloudAPIError
from config import settings, SYNC_INTERVAL_MS

logger = logging.getLogger(__name__)


class CloudSyncState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    AUTH_FAILED = "auth_failed"


class _SyncWorker(QObject):
    """在工作线程中执行同步 HTTP 请求，避免阻塞主线程"""
    # space_id=None 表示个人空间；带 str 才是团队空间。
    # 信号携带 space_key (None 或 str) 便于主线程按空间分别维护游标。
    pull_done = Signal(object, list, int)   # (space_key, new_items, max_server_id)
    pull_error = Signal(object, str, int)   # (space_key, message, status_code)
    push_done = Signal(object, int)         # (space_key, uploaded_count)
    push_error = Signal(object, str, int, list)  # (space_key, message, status_code, failed_batch)
    quota_warning = Signal(int, int)
    device_registered = Signal()    # 设备注册成功
    spaces_pulled = Signal(list)    # list_spaces 成功后发射 [dict, ...]

    # app_meta 表中存放永久放弃同步的 server_id 集合（JSON list）
    # Why: 进程重启后若某 server_id 的图片下载始终失败，无持久化时会从该 id
    # 处再次阻塞 _MAX_IMAGE_RETRY 次。落盘达阈值 id 后重启即永久放弃。
    _META_SKIP_KEY = "cloud_sync_permanently_skipped"

    def __init__(self, cloud_api: CloudAPIClient, repository: ClipboardRepository):
        super().__init__()
        self.cloud_api = cloud_api
        self.repository = repository
        s = settings()
        self._device_id = s.device_id
        self._device_name = s.device_name

        # server_id → 累计失败次数。计数 >= _MAX_IMAGE_RETRY 即视为永久放弃；
        # 单一事实来源避免"counter + set"双状态。惰性加载，首次查询才读 DB。
        self._skip_counter: dict[int, int] = {}
        self._skip_counter_loaded: bool = False
        self._skip_counter_dirty: bool = False

    @Slot(object, int)
    def do_pull(self, space_key, last_sync_id: int):
        """从云端拉取新记录（在工作线程中执行）

        space_key: None 表示个人空间；str 表示团队空间 id，用于过滤 /clipboard/sync
        并在信号回传时区分落库到哪条游标。
        """
        try:
            data = self.cloud_api.sync(
                since_id=last_sync_id, device_id=self._device_id,
                space_id=space_key if space_key else None,
            )
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
                # 记录来源 space：服务端会在 item 中回填 space_id（None=个人）。
                # 以服务端值为准；fallback 到当前同步的 space_key 保持一致性。
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
            # 本批若有新增永久放弃项，统一落盘一次（避免批内多次写 app_meta）
            if self._skip_counter_dirty:
                self._save_skip_counter()
                self._skip_counter_dirty = False
            self.pull_done.emit(space_key, new_items, max_server_id)

        except CloudAPIError as e:
            self.pull_error.emit(space_key, str(e), e.status_code)
        except Exception as e:
            logger.error(f"云端同步检查失败 (space={space_key}): {e}")
            self.pull_error.emit(space_key, str(e), 0)

    @Slot(object, list)
    def do_push(self, space_key, batch: list):
        """将本地条目推送到云端（在工作线程中执行）

        batch 内的条目已按同一 space 分组，space_key 会作为 item.space_id 透传。
        """
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
                # v3.4：携带 space/来源 App/窗口标题。
                # space_id 以 item 自身为准；None 表示个人空间，服务端按缺字段处理。
                if getattr(item, "space_id", None):
                    item_dict["space_id"] = item.space_id
                elif space_key:
                    # batch 已按 space_key 分组；item 本身没带就用分组键兜底
                    item_dict["space_id"] = space_key
                # 空字符串不发，减少 payload（服务端 coalesce 为 NULL）
                src_app = getattr(item, "source_app", "") or ""
                if src_app:
                    item_dict["source_app"] = src_app
                src_title = getattr(item, "source_title", "") or ""
                if src_title:
                    item_dict["source_title"] = src_title
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
            self.push_done.emit(space_key, uploaded_count)

        except CloudAPIError as e:
            self.push_error.emit(space_key, str(e), e.status_code, batch)
        except Exception as e:
            logger.error(f"云端推送异常 (space={space_key}): {e}")
            self.push_error.emit(space_key, str(e), 0, batch)

    @Slot()
    def do_list_spaces(self):
        """拉取参与的 space 列表（在工作线程中执行）。
        失败静默：外层会 fallback 到只同步个人空间。"""
        try:
            spaces = self.cloud_api.list_spaces()
            self.spaces_pulled.emit(spaces if isinstance(spaces, list) else [])
        except CloudAPIError as e:
            logger.info(f"list_spaces 失败（降级为仅同步个人空间）: {e}")
            self.spaces_pulled.emit([])
        except Exception as e:
            logger.warning(f"list_spaces 异常: {e}")
            self.spaces_pulled.emit([])

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
        """记录某 server_id 因图片/解析失败被跳过；达到阈值标记 dirty 待批量落盘。"""
        if not server_id:
            return
        self._ensure_skip_counter_loaded()
        current = self._skip_counter.get(server_id, 0)
        if current >= self._MAX_IMAGE_RETRY:
            return
        new_count = current + 1
        self._skip_counter[server_id] = new_count
        if new_count >= self._MAX_IMAGE_RETRY:
            # 延迟到 _on_pull_done 整批处理完再落盘，避免批内多条各写一次 app_meta
            self._skip_counter_dirty = True

    def _is_permanently_skipped(self, server_id: int) -> bool:
        if not server_id:
            return True
        self._ensure_skip_counter_loaded()
        return self._skip_counter.get(server_id, 0) >= self._MAX_IMAGE_RETRY

    def _ensure_skip_counter_loaded(self) -> None:
        if self._skip_counter_loaded:
            return
        # 从 app_meta 读已达阈值的 id 列表；每个初始化为 MAX 即代表"已永久放弃"
        try:
            raw = self.repository.get_meta(self._META_SKIP_KEY, "[]")
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    for x in data:
                        if isinstance(x, (int, str)) and str(x).isdigit():
                            self._skip_counter[int(x)] = self._MAX_IMAGE_RETRY
        except Exception as e:
            logger.debug(f"加载永久放弃集合失败: {e}")
        self._skip_counter_loaded = True

    def _save_skip_counter(self) -> None:
        try:
            # 仅持久化达阈值的 id；保底截断 5000 项防 JSON 膨胀
            ids = sorted(
                sid for sid, c in self._skip_counter.items() if c >= self._MAX_IMAGE_RETRY
            )[-5000:]
            self.repository.set_meta(self._META_SKIP_KEY, json.dumps(ids))
        except Exception as e:
            logger.debug(f"持久化永久放弃集合失败: {e}")

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

    @Slot()
    def do_starred_sync(self):
        """推送已收藏但未同步到云端的条目（在工作线程中执行）

        确保收藏条目一定存在于云端，配额管理由服务端负责。
        """
        try:
            unsynced = self.repository.get_starred_unsynced()
            if not unsynced:
                return

            upload_items = []
            image_items = []
            for item in unsynced:
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
                # v3.4：同样透传 space / source_app / source_title
                if getattr(item, "space_id", None):
                    item_dict["space_id"] = item.space_id
                src_app = getattr(item, "source_app", "") or ""
                if src_app:
                    item_dict["source_app"] = src_app
                src_title = getattr(item, "source_title", "") or ""
                if src_title:
                    item_dict["source_title"] = src_title
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
                for item in unsynced
                if item.id and item.content_hash in hash_to_server_id
            ]
            self.repository.set_cloud_ids_bulk(cloud_id_pairs)

            for item in image_items:
                server_id = hash_to_server_id.get(item.content_hash)
                if server_id:
                    self._upload_image_for_item(item, server_id)

            logger.info(f"收藏同步：已推送 {len(unsynced)} 条收藏条目到云端")
        except CloudAPIError as e:
            logger.warning(f"收藏同步推送失败: {e}")
        except Exception as e:
            logger.error(f"收藏同步推送异常: {e}")


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
    # v3.4：space 维度
    spaces_pulled = Signal(list)         # list_spaces 成功后发射，便于 UI / SpaceService 更新
    space_sync_progress = Signal(object, int, int)  # (space_key, current, total)

    # 内部信号：跨线程调度 worker 方法（避免 Q_ARG 不支持 list 类型）
    _trigger_push = Signal(object, list)   # (space_key, batch)
    _trigger_pull = Signal(object, int)    # (space_key, last_sync_id)
    _trigger_list_spaces = Signal()

    # 自适应轮询参数（与 SyncService 一致）
    _MIN_INTERVAL_MS = 1000
    _MAX_INTERVAL_MS = 30000
    _INTERVAL_STEP_MS = 2000

    # 上传批次大小
    _UPLOAD_BATCH_SIZE = 20

    # 数据库扫描未同步条目的最小间隔（秒）
    _DB_SCAN_INTERVAL_SEC = 10

    # app_meta 中存放云同步游标的键名（兼容旧版本：无 space_id 的单一游标）
    _META_CURSOR_KEY = "cloud_last_sync_id"
    # v3.4：按 space 区分的游标前缀；key 形如 cloud_sync_cursor:personal / cloud_sync_cursor:<uuid>
    _META_CURSOR_KEY_PREFIX = "cloud_sync_cursor:"
    # 持久化参与的 space 列表（用于无网络启动时也能按上次的 space 集合同步）
    _META_SPACES_KEY = "cloud_sync_spaces"

    # 游标节流落盘阈值：每 N 次推进或经过 SEC 秒才写一次，避免热路径频繁 DB 写。
    # 崩溃场景最多丢 N 条 / SEC 秒的进度，由 stop() 与 atexit 兜底收敛。
    _PERSIST_EVERY_N = 10
    _PERSIST_EVERY_SEC = 120.0

    def __init__(
        self,
        repository: ClipboardRepository,
        cloud_api: CloudAPIClient,
        entitlement_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.cloud_api = cloud_api
        self._entitlement_service = entitlement_service  # 可选，用于降级策略判断
        s = settings()
        self._device_id = s.device_id
        self._device_name = s.device_name
        # Why: 游标改为优先从 app_meta 读（轻量 key-value 落盘），兼容旧版本
        # 时 fallback 到 settings.json；读取到任意一处有值就用，用后不再写回老字段。
        self._last_sync_id = self._load_cursor_from_meta(s.cloud_last_sync_id)
        # v3.4：按 space 区分的游标。key=None 为个人空间；其余为 space_id (str)。
        # 个人空间游标从旧的 _last_sync_id 继承，确保升级后不重拉全量。
        self._space_cursors: dict = {None: self._last_sync_id}
        # 已知的 space id 列表（None 恒在内）。list_spaces 成功后刷新。
        self._known_spaces: list = [None]
        self._load_known_spaces_from_meta()
        self._state: CloudSyncState = CloudSyncState.STOPPED
        self._current_interval = self._MIN_INTERVAL_MS
        # in-flight 标志按 space 维护；存活 key = 正在拉/推的 space
        self._pulling_spaces: set = set()
        self._pushing_spaces: set = set()
        # 向后兼容：供老代码/测试读（值为 any space 在途）
        self._pulling = False
        self._pushing = False

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
        # 显式 QueuedConnection：信号发自 worker 线程，槽要在主线程写 _device_registered
        self._worker.device_registered.connect(
            lambda: setattr(self, '_device_registered', True), Qt.QueuedConnection
        )
        # 用信号槽替代 QMetaObject.invokeMethod + Q_ARG 传递 list
        self._trigger_push.connect(self._worker.do_push, Qt.QueuedConnection)
        self._trigger_pull.connect(self._worker.do_pull, Qt.QueuedConnection)
        self._trigger_list_spaces.connect(self._worker.do_list_spaces, Qt.QueuedConnection)
        self._worker.spaces_pulled.connect(self._on_spaces_pulled, Qt.QueuedConnection)
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

        self._cursor_persist_counter = 0
        self._last_cursor_persist_ts = time.monotonic()
        self._last_db_scan_ts = 0.0  # DB 扫描未同步条目的上次时间

        # v3.4：把 CloudAPIClient 注入 ShareService（如果该模块存在）
        # Why: ShareService 用 cloud_api_factory 做依赖注入，这里是 CloudSyncService
        # 首次拿到 cloud_api 的中心点，避免在 main.py 加专门连线。导入失败则静默跳过。
        try:
            from core import share_service as _share_service  # type: ignore
            factory_setter = getattr(_share_service, "set_cloud_api_factory", None)
            if callable(factory_setter):
                factory_setter(lambda: self.cloud_api)
            else:
                # 直接把 cloud_api 赋给模块级属性作兜底
                setattr(_share_service, "cloud_api_factory", lambda: self.cloud_api)
        except ImportError:
            pass  # share_service 未实现，跳过
        except Exception as e:
            logger.debug(f"ShareService 注入失败（忽略）: {e}")

    def _load_cursor_from_meta(self, fallback: int) -> int:
        """从 app_meta 读游标；读不到时用传入的 settings.json 值兜底（向后兼容）。
        个人空间的游标优先读 v3.4 新 key（cloud_sync_cursor:personal），
        失败回落到旧 key（cloud_last_sync_id），再回落到 settings。"""
        try:
            new_key = f"{self._META_CURSOR_KEY_PREFIX}personal"
            raw = self.repository.get_meta(new_key, None)
            if raw is not None and str(raw).strip():
                return int(raw)
        except Exception as e:
            logger.debug(f"读取新格式游标失败: {e}")
        try:
            raw = self.repository.get_meta(self._META_CURSOR_KEY, None)
            if raw is not None and str(raw).strip():
                return int(raw)
        except Exception as e:
            logger.debug(f"读取云同步游标失败（走 settings.json 兜底）: {e}")
        return fallback

    def _cursor_meta_key(self, space_key) -> str:
        """生成 app_meta 中该 space 对应的 key。"""
        suffix = "personal" if space_key is None else str(space_key)
        return f"{self._META_CURSOR_KEY_PREFIX}{suffix}"

    def _load_cursor_for_space(self, space_key) -> int:
        """按 space 读游标；个人空间走 _load_cursor_from_meta 的兜底逻辑。"""
        if space_key is None:
            return self._space_cursors.get(None, 0)
        try:
            raw = self.repository.get_meta(self._cursor_meta_key(space_key), None)
            if raw is not None and str(raw).strip():
                return int(raw)
        except Exception as e:
            logger.debug(f"读取 space={space_key} 游标失败: {e}")
        return 0

    def _persist_cursor(self) -> None:
        """把内存中所有 space 游标落盘到 app_meta。失败静默（热路径不要抛）。"""
        try:
            # 兼容旧 key：个人空间同时写 cloud_last_sync_id，便于降级回退。
            personal = self._space_cursors.get(None, self._last_sync_id)
            self._last_sync_id = personal  # 保持双字段同步
            self.repository.set_meta(self._META_CURSOR_KEY, str(personal))
            for space_key, cursor in self._space_cursors.items():
                self.repository.set_meta(
                    self._cursor_meta_key(space_key), str(int(cursor)),
                )
        except Exception as e:
            logger.debug(f"写入云同步游标失败: {e}")

    def _load_known_spaces_from_meta(self) -> None:
        """启动时加载持久化的 space 列表（离线启动时仍能按上次集合同步）。"""
        try:
            raw = self.repository.get_meta(self._META_SPACES_KEY, None)
            if raw:
                ids = json.loads(raw)
                if isinstance(ids, list):
                    self._known_spaces = [None] + [str(x) for x in ids if x]
                    # 把各 space 游标加载进来
                    for sid in self._known_spaces:
                        if sid not in self._space_cursors:
                            self._space_cursors[sid] = self._load_cursor_for_space(sid)
        except Exception as e:
            logger.debug(f"加载 known_spaces 失败: {e}")

    def _persist_known_spaces(self) -> None:
        try:
            ids = [s for s in self._known_spaces if s is not None]
            self.repository.set_meta(self._META_SPACES_KEY, json.dumps(ids))
        except Exception as e:
            logger.debug(f"写入 known_spaces 失败: {e}")

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

        # v3.4：启动时先刷一次 space 列表，回调里会把 _known_spaces 更新。
        # 失败不阻断——会 fallback 到仅同步个人空间。
        self._trigger_list_spaces.emit()

        # 启动拉取定时器
        self._pull_timer.start(interval_ms)

        # 推送定时器间隔为拉取的 2 倍
        self._push_timer.start(interval_ms * 2)

        # 启动后延迟 5 秒执行初始收藏同步（推送未同步的收藏 + 清理非收藏云端副本）
        QTimer.singleShot(5000, self._trigger_starred_sync)

        logger.info(f"云端同步服务已启动,拉取间隔 {interval_ms}ms")

    def _trigger_starred_sync(self):
        """触发收藏同步（在工作线程执行）"""
        if self._state != CloudSyncState.RUNNING:
            return
        QMetaObject.invokeMethod(
            self._worker, "do_starred_sync", Qt.QueuedConnection,
        )

    def stop(self):
        """停止云端同步服务"""
        if self._state == CloudSyncState.STOPPED:
            return
        self._transition(CloudSyncState.STOPPED)
        self._pull_timer.stop()
        self._push_timer.stop()
        # 退出时落盘游标（改走 app_meta，单条 key-value 比全量 settings 便宜）
        self._persist_cursor()
        # 先请求中断 + 关闭 httpx 客户端，强行解除阻塞中的网络 I/O，否则 wait 会被耗尽
        self._worker_thread.requestInterruption()
        try:
            self.cloud_api.close()
        except Exception as e:
            logger.debug(f"关闭 cloud_api 客户端失败（忽略）: {e}")
        self._worker_thread.quit()
        self._worker_thread.wait(3000)
        logger.info("云端同步服务已停止")

    def force_sync(self):
        """强制立即同步(拉取 + 推送)"""
        if self._state != CloudSyncState.RUNNING:
            logger.debug(f"force_sync 被忽略,当前状态: {self._state.value}")
            return
        self._pulling_spaces.clear()
        self._pushing_spaces.clear()
        self._pulling = False
        self._pushing = False
        self._pull_from_cloud()
        self._push_to_cloud()

    def reset_sync_position(self):
        """重置同步位置（全部 space 清零）"""
        self._last_sync_id = 0
        for key in list(self._space_cursors.keys()):
            self._space_cursors[key] = 0
        self._persist_cursor()
        logger.info("云端同步位置已重置")

    def persist_sync_cursor(self) -> None:
        """atexit / 崩溃兜底调用：立即把内存游标落盘到 app_meta。"""
        self._persist_cursor()

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

    def _get_spaces_to_sync(self) -> list:
        """返回本轮需要同步的 space key 列表；个人空间（None）恒在首位。
        未能获得 space 列表（未登录/网络差）时只同步个人空间。"""
        spaces = [None]
        for sid in self._known_spaces:
            if sid is not None and sid not in spaces:
                spaces.append(sid)
        return spaces

    def _pull_from_cloud(self):
        """从云端拉取新记录(主线程调度,实际 HTTP 在工作线程执行)。
        v3.4：对所有 space（个人 + team）各拉一次，由 worker 并行（实际上 Qt 队列串行）。"""
        if self._state != CloudSyncState.RUNNING:
            return
        for space_key in self._get_spaces_to_sync():
            if space_key in self._pulling_spaces:
                continue
            self._pulling_spaces.add(space_key)
            self._pulling = True  # 向后兼容
            cursor = self._space_cursors.get(space_key, 0)
            self._trigger_pull.emit(space_key, cursor)

    @Slot(object, list, int)
    def _on_pull_done(self, space_key, new_items: list, max_server_id: int):
        """拉取完成回调（主线程）。
        游标以节流方式增量落盘（每 N 次或每 T 秒任一触发），stop()/atexit 兜底。"""
        self._pulling_spaces.discard(space_key)
        self._pulling = bool(self._pulling_spaces)
        cursor_advanced = False
        cur = self._space_cursors.get(space_key, 0)
        if max_server_id > cur:
            self._space_cursors[space_key] = max_server_id
            if space_key is None:
                self._last_sync_id = max_server_id  # 双字段同步
            cursor_advanced = True

        if new_items:
            logger.debug(f"从云端拉取了 {len(new_items)} 条新记录 (space={space_key})")
            self.new_items_available.emit(new_items)
            if self._current_interval != self._MIN_INTERVAL_MS:
                self._current_interval = self._MIN_INTERVAL_MS
                self._pull_timer.setInterval(self._current_interval)
        elif not self._pulling_spaces:
            # 所有 space 都空才退化间隔；否则过于激进
            self._increase_interval()

        # Why: 仅在游标真正推进时才计数，避免空轮询刷满节流窗口。
        if cursor_advanced:
            self._cursor_persist_counter += 1
            now = time.monotonic()
            if (self._cursor_persist_counter >= self._PERSIST_EVERY_N
                    or now - self._last_cursor_persist_ts >= self._PERSIST_EVERY_SEC):
                self._cursor_persist_counter = 0
                self._last_cursor_persist_ts = now
                self._persist_cursor()

    @Slot(object, str, int)
    def _on_pull_error(self, space_key, message: str, status_code: int):
        """拉取失败回调(主线程)"""
        self._pulling_spaces.discard(space_key)
        self._pulling = bool(self._pulling_spaces)
        if status_code == 401:
            logger.warning("云端认证失败,请重新登录")
            # 停止轮询,避免反复刷 401 日志
            self._pull_timer.stop()
            self._push_timer.stop()
            self._transition(CloudSyncState.AUTH_FAILED)
            self.sync_error.emit("云端认证失败,请在设置中重新登录")
        elif status_code == 403:
            # 订阅不够权限访问该 space（例如降级后）；记录但不 crash，不打断其他 space
            logger.warning(
                f"云端拉取 403 (space={space_key}): {message}；可能订阅不支持此空间",
            )
            self.sync_error.emit(f"无权限访问空间 {space_key}: {message}")
        else:
            logger.error(f"云端拉取失败 (space={space_key}): {message}")
            self.sync_error.emit(message)

    @Slot(list)
    def _on_spaces_pulled(self, spaces: list):
        """list_spaces 成功后的回调：更新 _known_spaces，落盘，发 signal 给 UI/SpaceService。"""
        try:
            ids = [None]
            for sp in spaces or []:
                sid = sp.get("id") if isinstance(sp, dict) else None
                if sid and sid not in ids:
                    ids.append(str(sid))
            self._known_spaces = ids
            # 为新 space 初始化游标
            for sid in ids:
                if sid not in self._space_cursors:
                    self._space_cursors[sid] = self._load_cursor_for_space(sid)
            self._persist_known_spaces()
            self.spaces_pulled.emit(spaces or [])
        except Exception as e:
            logger.debug(f"_on_spaces_pulled 处理异常: {e}")

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
        """将本地待上传条目推送到云端(主线程调度,实际 HTTP 在工作线程执行)。
        v3.4：按 space_id 分组，每组一次 batch_create。订阅降级后 team space 不 push。"""
        if self._state != CloudSyncState.RUNNING:
            return

        # 队列为空时，定期从数据库扫描未同步的条目
        if not self._pending_upload_queue and not self._retry_queue:
            self._load_unsynced_from_db()

        if not self._pending_upload_queue and not self._retry_queue:
            return

        # 每 10 次推送检查一次配额
        self._quota_check_counter += 1
        if self._quota_check_counter % 10 == 1:
            QMetaObject.invokeMethod(self._worker, "do_check_quota", Qt.QueuedConnection)

        # 优先处理重试队列，其次新数据
        batch: list = []
        while self._retry_queue and len(batch) < self._UPLOAD_BATCH_SIZE:
            batch.append(self._retry_queue.popleft())
        while self._pending_upload_queue and len(batch) < self._UPLOAD_BATCH_SIZE:
            batch.append(self._pending_upload_queue.popleft())

        if not batch:
            return

        # 按 space_id 分组
        groups: dict = {}
        for item in batch:
            key = getattr(item, "space_id", None) or None
            groups.setdefault(key, []).append(item)

        # 订阅降级策略：非 team 计划禁止推送 team space（但仍允许个人空间）
        can_push_team = self._can_edit_team_space()
        for space_key, items in groups.items():
            if space_key is not None and not can_push_team:
                logger.info(
                    f"订阅不支持 team space 编辑，跳过 push {len(items)} 条 (space={space_key})",
                )
                continue
            if space_key in self._pushing_spaces:
                # 把这批退回 retry_queue 下轮再推
                for it in items:
                    if len(self._retry_queue) < self._retry_queue.maxlen:
                        self._retry_queue.append(it)
                continue
            self._pushing_spaces.add(space_key)
            self._pushing = True
            logger.warning(
                f"云端推送：发送 {len(items)} 条记录 (space={space_key})",
            )
            self._trigger_push.emit(space_key, items)

    def _can_edit_team_space(self) -> bool:
        """订阅降级后 team space 为只读（不 push）；team 计划允许编辑所有空间。
        没有 entitlement_service 时默认 True（兼容老启动路径；服务端会兜底拒绝）。"""
        svc = self._entitlement_service
        if svc is None:
            return True
        try:
            ent = svc.current()
        except Exception:
            return True
        # 约定：ultimate / super 及其他付费档位视为 team，free / basic 不能编辑 team space。
        # plan 名取自 entitlement_service.Plan 枚举；其 .value 为小写字符串。
        plan_value = getattr(getattr(ent, "plan", None), "value", "") or ""
        return plan_value in ("super", "ultimate")

    def _load_unsynced_from_db(self):
        """从数据库扫描未同步的条目加入上传队列（有冷却间隔避免频繁查询）"""
        now = time.monotonic()
        if now - self._last_db_scan_ts < self._DB_SCAN_INTERVAL_SEC:
            return
        self._last_db_scan_ts = now
        try:
            unsynced = self.repository.get_unsynced_items(limit=self._UPLOAD_BATCH_SIZE)
            for item in unsynced:
                self._pending_upload_queue.append(item)
            if unsynced:
                logger.warning(f"数据库扫描：加载了 {len(unsynced)} 条未同步条目到上传队列")
        except Exception as e:
            logger.warning(f"数据库扫描未同步条目失败: {e}")

    @Slot(object, int)
    def _on_push_done(self, space_key, uploaded_count: int):
        """推送完成回调（主线程）"""
        self._pushing_spaces.discard(space_key)
        self._pushing = bool(self._pushing_spaces)
        self.upload_completed.emit(uploaded_count)
        logger.warning(
            f"云端推送成功：已上传 {uploaded_count} 条记录 (space={space_key})",
        )

    @Slot(object, str, int, list)
    def _on_push_error(self, space_key, message: str, status_code: int, failed_batch: list):
        """推送失败回调（主线程）"""
        self._pushing_spaces.discard(space_key)
        self._pushing = bool(self._pushing_spaces)
        logger.error(f"云端推送失败 (space={space_key}): {message}")
        # 配额不足（403）时不重试
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
