"""常用文件云端同步服务（付费用户专用）。

依赖 EntitlementService 做"能否上传"的强前置校验——若未付费 / 配额满，入队即被拒。
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer, QThread, Slot, Qt

from core.cloud_api import CloudAPIClient, CloudAPIError
from core.cloud_sync_service import CloudSyncState
from core.entitlement_service import EntitlementService
from core.file_models import CloudFile, FileSyncState
from core.file_repository import CloudFileRepository
from core.repository import ClipboardRepository
from config import settings

logger = logging.getLogger(__name__)


_META_CURSOR_KEY = "files_last_sync_id"
_UPLOAD_QUEUE_MAX = 500
_DOWNLOAD_QUEUE_MAX = 500


def _pick_upload_headers(obj: dict) -> Optional[dict]:
    """从 plan / part 里取 upload_headers，非 dict 时返回 None。

    服务端要求客户端原样透传签名头给 OSS，否则 403 SignatureDoesNotMatch。
    """
    h = obj.get("upload_headers")
    return h if isinstance(h, dict) else None


class _FileSyncWorker(QObject):
    """后台 HTTP 工作者。所有发起请求的槽都运行在 worker 线程。"""

    upload_progress = Signal(int, int, int)    # (local_id, done, total)
    download_progress = Signal(int, int, int)
    upload_started = Signal(int)               # (local_id) 用于通知 UI 状态已翻到 syncing
    upload_finished = Signal(int, bool, str)   # (local_id, success, err)
    download_finished = Signal(int, bool, str)
    pull_done = Signal(list, int)              # (list[CloudFile], max_server_id)
    pull_error = Signal(str, int)

    def __init__(
        self,
        cloud_api: CloudAPIClient,
        repo: CloudFileRepository,
        entitlement: EntitlementService,
    ):
        super().__init__()
        self.cloud_api = cloud_api
        self.repo = repo
        self.entitlement = entitlement
        s = settings()
        self._device_id = s.device_id
        self._device_name = s.device_name

    # ---------- pull ----------
    @Slot(int)
    def do_pull(self, last_sync_id: int):
        try:
            data = self.cloud_api.files_list(last_sync_id, self._device_id)
        except CloudAPIError as e:
            self.pull_error.emit(str(e), e.status_code)
            return
        except Exception as e:
            logger.warning(f"文件拉取异常: {e}")
            self.pull_error.emit(str(e), 0)
            return

        items = data.get("items", []) or []
        parsed: list[CloudFile] = []
        max_id = last_sync_id
        for srv in items:
            try:
                cid = int(srv.get("id") or srv.get("cloud_id") or 0)
                if cid > max_id:
                    max_id = cid
                sha = srv.get("content_sha256", "") or ""
                if not sha:
                    continue
                is_deleted = bool(srv.get("is_deleted", False))
                existing = self.repo.get_by_cloud_id(cid) or self.repo.get_by_sha(sha)
                if is_deleted and existing is not None and existing.id:
                    self.repo.mark_deleted(existing.id)
                    # mark_deleted 只改 DB；同步翻 in-memory 对象的 is_deleted，
                    # 否则 _on_pull_done 里 `if f.is_deleted` 为假，会错把删除事件发成 file_added。
                    existing.is_deleted = True
                    parsed.append(existing)
                    continue
                if existing is None:
                    f = CloudFile(
                        cloud_id=cid,
                        name=srv.get("name", "unknown"),
                        size_bytes=int(srv.get("size_bytes", 0)),
                        mime_type=srv.get("mime_type", ""),
                        content_sha256=sha,
                        mtime=int(srv.get("mtime", 0)),
                        device_id=srv.get("device_id", ""),
                        device_name=srv.get("device_name", ""),
                        created_at=int(srv.get("created_at", int(time.time() * 1000))),
                        sync_state=FileSyncState.REMOTE_ONLY.value,
                    )
                    f.id = self.repo.add_file(f)
                    parsed.append(f)
                else:
                    # 覆盖元数据（远端为准）
                    changes = {
                        "cloud_id": cid,
                        "name": srv.get("name", existing.name),
                        "size_bytes": int(srv.get("size_bytes", existing.size_bytes)),
                        "mime_type": srv.get("mime_type", existing.mime_type),
                        "mtime": int(srv.get("mtime", existing.mtime)),
                    }
                    self.repo.update_meta(existing.id, **changes)
                    parsed.append(self.repo.get_by_id(existing.id) or existing)
            except Exception as e:
                logger.debug(f"处理云端文件条目失败: {e}")
                continue

        self.pull_done.emit(parsed, max_id)

    # ---------- upload ----------
    @Slot(int)
    def do_upload(self, local_id: int):
        f = self.repo.get_by_id(local_id)
        if not f or f.is_deleted:
            self.upload_finished.emit(local_id, False, "条目不存在或已删除")
            return
        if not f.local_path or not os.path.exists(f.local_path):
            self.upload_finished.emit(local_id, False, "本地文件缺失")
            return

        # 最后一道付费闸（服务端也会拒，但避免发无用请求）
        ok, reason = self.entitlement.can_upload(f.size_bytes)
        if not ok:
            self.repo.set_sync_state(local_id, FileSyncState.ERROR.value, reason)
            self.upload_finished.emit(local_id, False, reason)
            return

        try:
            meta = {
                "name": f.name,
                "size": f.size_bytes,
                "sha256": f.content_sha256,
                "mime_type": f.mime_type or "application/octet-stream",
                "mtime": f.mtime,
                "device_id": self._device_id,
                "device_name": self._device_name,
            }
            plan = self.cloud_api.files_request_upload(meta)
        except CloudAPIError as e:
            detail = str(e)
            debug = (e.payload or {}).get("debug")
            sqlstate = (e.payload or {}).get("sqlstate")
            if debug or sqlstate:
                detail = f"{e} [debug={debug} sqlstate={sqlstate}]"
            logger.warning(
                "request_upload 失败 local_id=%s name=%s size=%s status=%s: %s",
                local_id, f.name, f.size_bytes, e.status_code, detail,
            )
            self.repo.set_sync_state(local_id, FileSyncState.ERROR.value, detail)
            self.upload_finished.emit(local_id, False, detail)
            return

        cloud_id = int(plan.get("cloud_id") or plan.get("file_id") or 0)
        # 一次 update：cloud_id + SYNCING，避免两次 round-trip
        self.repo.update_meta(
            local_id,
            cloud_id=cloud_id or None,
            sync_state=FileSyncState.SYNCING.value,
            last_error=None,
        )
        # 通知 UI 状态已变：否则 model 里的 CloudFile 仍是 PENDING，
        # ProgressDelegate 永远画不出"同步中"的进度条（只显示"待上传"文字）。
        self.upload_started.emit(local_id)

        mode = plan.get("upload_mode", "single")
        upload_headers = _pick_upload_headers(plan)
        try:
            if mode == "exists":
                self.repo.update_meta(
                    local_id, sync_state=FileSyncState.SYNCED.value, last_error=None,
                )
                self.repo.clear_parts(local_id)
                self.upload_finished.emit(local_id, True, "")
                return
            if mode == "multipart":
                self._do_multipart(local_id, f, plan, cloud_id)
            else:
                url = plan.get("upload_url", "")
                if upload_headers is None:
                    upload_headers = {"x-oss-object-acl": "private"}
                etag = self.cloud_api.upload_file_to_url(
                    url, f.local_path,
                    progress_cb=lambda done, total: self.upload_progress.emit(local_id, done, total),
                    extra_headers=upload_headers,
                )
                # 单段不需 complete，但服务端若需要我们也发一次
                if plan.get("complete_url") or cloud_id:
                    # Why: complete 用于把服务端 upload_status 从 1 翻到 2；失败时
                    # 服务端会记录为 file not ready，其它设备下载时会拿到 409。
                    # 以前这里直接吞掉异常，客户端把本地翻成 SYNCED 但服务端永远不可达。
                    self.cloud_api.files_complete_upload(
                        cloud_id, [{"part_number": 1, "etag": etag}] if etag else [],
                    )
            self.repo.update_meta(
                local_id, sync_state=FileSyncState.SYNCED.value, last_error=None,
            )
            self.repo.clear_parts(local_id)
            self.upload_finished.emit(local_id, True, "")
            if mode != "exists":
                self.entitlement.record_local_upload(f.size_bytes)
        except CloudAPIError as e:
            self.repo.set_sync_state(local_id, FileSyncState.ERROR.value, str(e))
            self.upload_finished.emit(local_id, False, str(e))
        except Exception as e:
            logger.error(f"上传异常 local_id={local_id}: {e}", exc_info=True)
            self.repo.set_sync_state(local_id, FileSyncState.ERROR.value, str(e))
            self.upload_finished.emit(local_id, False, str(e))

    def _do_multipart(self, local_id: int, f: CloudFile, plan: dict, cloud_id: int):
        parts_plan = plan.get("parts") or []
        if not parts_plan:
            raise CloudAPIError("服务端未返回 multipart parts", 0)
        already = self.repo.get_parts(local_id)  # {part_number: etag}
        part_size = int(plan.get("part_size") or self.cloud_api.FILE_PART_SIZE)
        total = f.size_bytes
        # 签名头可能在 plan 顶层（各 part 共用）或每个 part 里，per-part 优先
        plan_headers = _pick_upload_headers(plan)
        done_before_current = 0
        for p in parts_plan:
            pn = int(p["part_number"])
            if pn in already:
                done_before_current += part_size
                continue
        for p in parts_plan:
            pn = int(p["part_number"])
            if pn in already:
                continue
            offset = (pn - 1) * part_size
            this_size = min(part_size, total - offset)

            snap_done_before = done_before_current

            def _cb(done_in_part, _part_total, _snap=snap_done_before, _total=total):
                # emit 时传入全局进度，便于 UI 渲染整体百分比
                self.upload_progress.emit(local_id, _snap + done_in_part, _total)

            part_headers = _pick_upload_headers(p) or plan_headers
            # OSS multipart 的 UploadPart presigned URL 通常不签 Content-Type，
            # 客户端硬塞会导致签名不匹配 → 403；除非服务端在 upload_headers 里显式指定，否则不发。
            part_ct = (part_headers or {}).get("Content-Type") if part_headers else None
            etag = self.cloud_api.upload_file_to_url(
                p["url"], f.local_path,
                part_offset=offset, part_size=this_size,
                progress_cb=_cb,
                extra_headers=part_headers,
                default_content_type=part_ct,
            )
            self.repo.record_part(local_id, pn, etag)
            done_before_current += this_size
            self.upload_progress.emit(local_id, done_before_current, total)

        # complete：读取 DB 里全部 etag
        all_parts = self.repo.get_parts(local_id)
        etags = [{"part_number": pn, "etag": tag} for pn, tag in sorted(all_parts.items())]
        try:
            self.cloud_api.files_complete_upload(cloud_id, etags)
        except CloudAPIError as e:
            raise

    # ---------- download ----------
    @Slot(int)
    def do_download(self, local_id: int):
        f = self.repo.get_by_id(local_id)
        if not f or not f.cloud_id:
            self.download_finished.emit(local_id, False, "无云端映射")
            return
        try:
            url = self.cloud_api.files_get_download_url(f.cloud_id)
            if not url:
                self.download_finished.emit(local_id, False, "下载链接为空")
                return
            from core.file_storage import sandbox_path_for
            dest = str(sandbox_path_for(f.content_sha256))
            self.cloud_api.download_file_to(
                url, dest,
                progress_cb=lambda done, total: self.download_progress.emit(local_id, done, total),
            )
            self.repo.update_meta(
                local_id, local_path=dest, sync_state=FileSyncState.SYNCED.value,
            )
            self.download_finished.emit(local_id, True, "")
        except CloudAPIError as e:
            self.repo.set_sync_state(local_id, FileSyncState.ERROR.value, str(e))
            self.download_finished.emit(local_id, False, str(e))
        except Exception as e:
            logger.error(f"下载异常 local_id={local_id}: {e}", exc_info=True)
            self.repo.set_sync_state(local_id, FileSyncState.ERROR.value, str(e))
            self.download_finished.emit(local_id, False, str(e))


class FileCloudSyncService(QObject):
    """对外的 Qt 服务层：队列管理 + 定时器 + 信号转发。"""

    file_added = Signal(object)       # CloudFile
    file_updated = Signal(object)
    file_deleted = Signal(int)
    upload_progress = Signal(int, int, int)     # (local_id, done, total)
    download_progress = Signal(int, int, int)
    upload_finished = Signal(int, bool, str)
    download_finished = Signal(int, bool, str)
    sync_error = Signal(str, int)
    quota_warning = Signal(int, int)            # (used, total)

    _trigger_pull = Signal(int)
    _trigger_upload = Signal(int)
    _trigger_download = Signal(int)

    _PULL_INTERVAL_MS = 30_000

    def __init__(
        self,
        repository: CloudFileRepository,
        cloud_api: CloudAPIClient,
        entitlement: EntitlementService,
        meta_store: ClipboardRepository,
        parent=None,
    ):
        super().__init__(parent)
        self.repo = repository
        self.cloud_api = cloud_api
        self.entitlement = entitlement
        self._meta = meta_store
        self._state = CloudSyncState.STOPPED

        self._upload_queue: deque = deque(maxlen=_UPLOAD_QUEUE_MAX)
        self._download_queue: deque = deque(maxlen=_DOWNLOAD_QUEUE_MAX)
        self._pulling = False
        self._uploading = False
        self._downloading = False

        self._last_sync_id = self._load_cursor()

        self._worker_thread = QThread(self)
        self._worker = _FileSyncWorker(cloud_api, repository, entitlement)
        self._worker.moveToThread(self._worker_thread)
        self._worker.pull_done.connect(self._on_pull_done)
        self._worker.pull_error.connect(self._on_pull_error)
        self._worker.upload_progress.connect(self.upload_progress)
        self._worker.download_progress.connect(self.download_progress)
        self._worker.upload_started.connect(self._on_upload_started)
        self._worker.upload_finished.connect(self._on_upload_finished)
        self._worker.download_finished.connect(self._on_download_finished)

        self._trigger_pull.connect(self._worker.do_pull, Qt.QueuedConnection)
        self._trigger_upload.connect(self._worker.do_upload, Qt.QueuedConnection)
        self._trigger_download.connect(self._worker.do_download, Qt.QueuedConnection)

        self._worker_thread.start()

        self._pull_timer = QTimer(self)
        self._pull_timer.timeout.connect(self._tick_pull)

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self._state != CloudSyncState.STOPPED:
            return
        self._state = CloudSyncState.RUNNING
        # 启动时扫残留 pending/syncing 入队
        try:
            for f in self.repo.list_by_states([
                FileSyncState.PENDING.value,
                FileSyncState.SYNCING.value,
            ]):
                if f.id and not f.is_deleted and f.local_path and os.path.exists(f.local_path):
                    self._upload_queue.append(f.id)
        except Exception as e:
            logger.debug(f"加载待上传失败: {e}")
        self._pull_timer.start(self._PULL_INTERVAL_MS)
        QTimer.singleShot(500, self._tick_pull)
        QTimer.singleShot(1000, self._drive_queues)
        logger.info("文件云同步服务已启动")

    def stop(self) -> None:
        if self._state == CloudSyncState.STOPPED:
            return
        self._state = CloudSyncState.STOPPED
        self._pull_timer.stop()
        self.persist_sync_cursor()
        self._worker_thread.requestInterruption()
        self._worker_thread.quit()
        self._worker_thread.wait(3000)
        logger.info("文件云同步服务已停止")

    # ---------- 公共 API（供 UI / 其它服务调用） ----------

    def enqueue_upload(self, local_id: int) -> None:
        if self._state != CloudSyncState.RUNNING:
            return
        self.repo.set_sync_state(local_id, FileSyncState.PENDING.value)
        self._upload_queue.append(local_id)
        QTimer.singleShot(0, self._drive_queues)

    def enqueue_download(self, local_id: int) -> None:
        if self._state != CloudSyncState.RUNNING:
            return
        self._download_queue.append(local_id)
        QTimer.singleShot(0, self._drive_queues)

    def force_sync(self) -> None:
        if self._state == CloudSyncState.RUNNING:
            self._tick_pull()
            self._drive_queues()

    def persist_sync_cursor(self) -> None:
        try:
            self._save_cursor()
        except Exception:
            logger.debug("持久化 files 游标失败", exc_info=True)

    # ---------- queue driver ----------

    def _drive_queues(self) -> None:
        if self._state != CloudSyncState.RUNNING:
            return
        if self._uploading and self._downloading:
            return
        if not self._uploading and self._upload_queue:
            lid = self._upload_queue.popleft()
            self._uploading = True
            self._trigger_upload.emit(lid)
        if not self._downloading and self._download_queue:
            lid = self._download_queue.popleft()
            self._downloading = True
            self._trigger_download.emit(lid)

    # ---------- pull ----------

    def _tick_pull(self) -> None:
        if self._state != CloudSyncState.RUNNING or self._pulling:
            return
        if self.cloud_api is None or not self.cloud_api.is_authenticated:
            return
        ok, _ = self.entitlement.can_use_files()
        if not ok:
            return
        self._pulling = True
        self._trigger_pull.emit(self._last_sync_id)

    @Slot(list, int)
    def _on_pull_done(self, items: list, max_id: int):
        self._pulling = False
        if max_id > self._last_sync_id:
            self._last_sync_id = max_id
            try:
                self._save_cursor()
            except Exception:
                logger.debug("保存 files 游标失败", exc_info=True)
        # 发出信号驱动 UI 刷新；自动下载策略：files_auto_download 下小于阈值的自动入队
        s = settings()
        auto = s.files_auto_download
        max_auto = int(s.files_max_autodownload_mb) * (1 << 20)
        for f in items:
            if f.is_deleted:
                self.file_deleted.emit(f.id or 0)
                continue
            self.file_added.emit(f)
            if auto and f.sync_state == FileSyncState.REMOTE_ONLY.value:
                if max_auto == 0 or f.size_bytes <= max_auto:
                    self.enqueue_download(f.id)

    @Slot(str, int)
    def _on_pull_error(self, msg: str, status: int):
        self._pulling = False
        if status == 401:
            self._state = CloudSyncState.AUTH_FAILED
            self.sync_error.emit("云端认证失败，请重新登录", status)
        else:
            logger.debug(f"文件拉取失败（不阻塞）: {msg}")

    # ---------- upload/download callbacks ----------

    @Slot(int)
    def _on_upload_started(self, local_id: int):
        f = self.repo.get_by_id(local_id)
        if f:
            self.file_updated.emit(f)

    @Slot(int, bool, str)
    def _on_upload_finished(self, local_id: int, ok: bool, err: str):
        self._uploading = False
        # 不管成功失败，都把当前行刷一遍：失败时 worker 已把 sync_state 翻到 ERROR，
        # UI 靠这次 file_updated 才能把"同步中"的进度条换成"错误 + 原因"。
        f = self.repo.get_by_id(local_id)
        if f:
            self.file_updated.emit(f)
        if not ok:
            self.sync_error.emit(err or "上传失败", 0)
        # 转发给 UI：之前只偷偷把成功刷到 file_updated，失败连信号都不发，
        # 导致 file_list_widget 里对 upload_finished 的订阅形同虚设。
        self.upload_finished.emit(local_id, ok, err)
        QTimer.singleShot(0, self._drive_queues)

    @Slot(int, bool, str)
    def _on_download_finished(self, local_id: int, ok: bool, err: str):
        self._downloading = False
        f = self.repo.get_by_id(local_id)
        if f:
            self.file_updated.emit(f)
        if not ok:
            self.sync_error.emit(err or "下载失败", 0)
        self.download_finished.emit(local_id, ok, err)
        QTimer.singleShot(0, self._drive_queues)

    # ---------- cursor ----------

    def _load_cursor(self) -> int:
        raw = self._meta.get_meta(_META_CURSOR_KEY, None)
        try:
            return int(raw) if raw else 0
        except (TypeError, ValueError):
            return 0

    def _save_cursor(self) -> None:
        self._meta.set_meta(_META_CURSOR_KEY, str(self._last_sync_id))
