"""常用文件云端同步服务（付费用户专用）。

依赖 EntitlementService 做"能否上传"的强前置校验——若未付费 / 配额满，入队即被拒。
"""

from __future__ import annotations

import logging
import os
import re
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
    delete_finished = Signal(int, bool, str)
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
        # cloud_id -> 连续处理失败次数（用于失败项的重试与最终放弃，见 _process_page）
        self._pull_skip: dict = {}

    # ---------- pull ----------
    # 单轮 do_pull 最多连续翻多少页（服务端一页 100 条）。防止 has_more 恒为真时
    # 把 worker 线程占满。
    _MAX_PULL_PAGES = 20
    # 同一条云端记录连续解析失败达到该次数后放弃并推进游标，避免一条坏数据把
    # 同步永久卡住（不推进则它会每轮都被重新拉取、反复失败）。
    _MAX_PULL_SKIP = 5

    @Slot(int)
    def do_pull(self, last_sync_id: int):
        parsed: list[CloudFile] = []
        cursor = last_sync_id

        try:
            for _ in range(self._MAX_PULL_PAGES):
                try:
                    data = self.cloud_api.files_list(cursor, self._device_id)
                except CloudAPIError as e:
                    # 取舍说明：翻到第 N 页失败时，前 N-1 页已 add_file 落库但
                    # 只发 pull_error，cursor 不动。下轮重拉靠 get_by_cloud_id
                    # 幂等去重自愈，已落库条目不会重复入库，只是 UI 通知晚一轮。
                    self.pull_error.emit(str(e), e.status_code)
                    return
                except Exception as e:
                    logger.warning(f"文件拉取异常: {e}")
                    self.pull_error.emit(str(e), 0)
                    return

                items = data.get("items", []) or []
                page_parsed, cursor = self._process_page(items, cursor)
                parsed.extend(page_parsed)

                # Why: 旧实现从不读 has_more，首次全量同步/长离线恢复时每个同步
                # 周期只推进 100 条，积压追赶极慢。
                if not items or not data.get("has_more"):
                    break
                if cursor <= last_sync_id and not page_parsed:
                    logger.warning("文件拉取本页无进展，停止翻页以免死循环")
                    break
        except Exception as e:
            logger.exception("文件拉取处理异常")
            self.pull_error.emit(str(e), 0)
            return

        self.pull_done.emit(parsed, cursor)

    def _process_page(self, items: list, last_sync_id: int):
        """处理一页云端记录，返回 (parsed, new_cursor)。

        游标只对「处理成功」或「已放弃重试」的条目推进。旧实现在解析/校验之前
        就先 `max_id = cid`，一旦字段名对不上（后端返回 sha256，这里读
        content_sha256）所有条目都会失败被跳过，而游标已经越过它们 —— 数据
        永久丢失且不可恢复。
        """
        parsed: list[CloudFile] = []
        max_id = last_sync_id

        for srv in items:
            cid = int(srv.get("id") or srv.get("cloud_id") or 0)
            if cid <= 0:
                continue

            # 后端 /files/sync 的 serializeFileRow() 返回的是 sha256，历史上这里读
            # content_sha256 导致恒为空。两个键都接受，避免再次被契约变更打穿。
            sha = srv.get("content_sha256") or srv.get("sha256") or ""
            is_deleted = bool(srv.get("is_deleted", False))

            ok = False
            try:
                ok = self._apply_remote_file(srv, cid, sha, is_deleted, parsed)
            except Exception as e:
                logger.debug(f"处理云端文件条目 {cid} 失败: {e}")

            if ok:
                if cid > max_id:
                    max_id = cid
                self._pull_skip.pop(cid, None)
                continue

            attempts = self._pull_skip.get(cid, 0) + 1
            self._pull_skip[cid] = attempts
            if attempts >= self._MAX_PULL_SKIP:
                logger.error(
                    f"云端文件 {cid} 连续 {attempts} 次处理失败，放弃并推进游标"
                )
                self._pull_skip.pop(cid, None)
                if cid > max_id:
                    max_id = cid

        return parsed, max_id

    def _apply_remote_file(self, srv: dict, cid: int, sha, is_deleted: bool, parsed: list) -> bool:
        """落地单条云端记录，返回是否处理成功。"""
        # 删除事件只需 cloud_id 即可定位。服务端 tombstone 可能不再携带
        # sha，不能先做 SHA 校验，否则游标会越过删除事件但本地记录永久残留。
        if is_deleted:
            existing = self.repo.get_by_cloud_id(cid)
            if (
                existing is None
                and isinstance(sha, str)
                and re.fullmatch(r"[a-fA-F0-9]{64}", sha) is not None
            ):
                existing = self.repo.get_by_sha(sha.lower())
            if existing is None:
                # 本地本来就没有这条，无事可做，游标可以安全推进。
                return True
            if existing.id:
                # 服务端已确认删除，不再标成 pending 回推。
                self.repo.update_meta(
                    existing.id,
                    is_deleted=1,
                    sync_state=FileSyncState.SYNCED.value,
                    last_error=None,
                )
                # update_meta 只改 DB；同步翻 in-memory 对象的 is_deleted，
                # 否则 _on_pull_done 里 `if f.is_deleted` 为假，会错把删除事件发成 file_added。
                existing.is_deleted = True
                parsed.append(existing)
            return True

        if not isinstance(sha, str) or re.fullmatch(r"[a-fA-F0-9]{64}", sha) is None:
            return False
        # hashlib.hexdigest() 固定返回小写；入口统一规范化，避免合法的大写
        # SHA-256 在下载完整性校验时被误判。
        sha = sha.lower()
        existing = self.repo.get_by_cloud_id(cid) or self.repo.get_by_sha(sha)
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
        return True

    # ---------- delete ----------
    @Slot(int)
    def do_delete(self, local_id: int):
        f = self.repo.get_by_id(local_id)
        if not f or not f.is_deleted:
            self.delete_finished.emit(local_id, True, "")
            return
        if not f.cloud_id:
            self.repo.update_meta(
                local_id,
                sync_state=FileSyncState.SYNCED.value,
                last_error=None,
            )
            self.delete_finished.emit(local_id, True, "")
            return

        try:
            deleted = self.cloud_api.files_delete(f.cloud_id)
            if not deleted:
                raise CloudAPIError("云端删除未成功", 0)
            self.repo.update_meta(
                local_id,
                sync_state=FileSyncState.SYNCED.value,
                last_error=None,
            )
            self.delete_finished.emit(local_id, True, "")
        except Exception as e:
            logger.warning(
                "云端文件删除失败 local_id=%s cloud_id=%s: %s",
                local_id,
                f.cloud_id,
                e,
            )
            self.repo.set_sync_state(local_id, FileSyncState.ERROR.value, str(e))
            self.delete_finished.emit(local_id, False, str(e))

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

            import os
            import hashlib
            if os.path.getsize(dest) != f.size_bytes:
                os.remove(dest)
                self.download_finished.emit(local_id, False, "下载文件大小不匹配")
                return
            
            h = hashlib.sha256()
            with open(dest, "rb") as fp:
                while True:
                    chunk = fp.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            if h.hexdigest() != f.content_sha256:
                os.remove(dest)
                self.download_finished.emit(local_id, False, "下载文件校验和不匹配")
                return

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
    delete_finished = Signal(int, bool, str)
    sync_error = Signal(str, int)
    quota_warning = Signal(int, int)            # (used, total)

    _trigger_pull = Signal(int)
    _trigger_upload = Signal(int)
    _trigger_download = Signal(int)
    _trigger_delete = Signal(int)

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
        # 删除 tombstone 本身只占一个整数，使用无界队列避免批量删除超过
        # maxlen 时静默挤掉尚未提交的云端删除；数据库仍是最终恢复来源。
        self._delete_queue: deque = deque()
        self._pulling = False
        self._uploading = False
        self._downloading = False
        self._deleting = False

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
        self._worker.delete_finished.connect(self._on_delete_finished)

        self._trigger_pull.connect(self._worker.do_pull, Qt.QueuedConnection)
        self._trigger_upload.connect(self._worker.do_upload, Qt.QueuedConnection)
        self._trigger_download.connect(self._worker.do_download, Qt.QueuedConnection)
        self._trigger_delete.connect(self._worker.do_delete, Qt.QueuedConnection)

        self._worker_thread.start()

        self._pull_timer = QTimer(self)
        self._pull_timer.timeout.connect(self._tick_pull)

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self._state != CloudSyncState.STOPPED:
            return
        self._state = CloudSyncState.RUNNING
        # 启动时扫残留状态入队；删除失败会持久化为 error，下次启动继续重试。
        try:
            for f in self.repo.list_by_states([
                FileSyncState.PENDING.value,
                FileSyncState.SYNCING.value,
                FileSyncState.ERROR.value,
            ]):
                if not f.id:
                    continue
                if f.is_deleted:
                    if f.cloud_id:
                        self._delete_queue.append(f.id)
                    else:
                        self.repo.update_meta(
                            f.id,
                            sync_state=FileSyncState.SYNCED.value,
                            last_error=None,
                        )
                elif (
                    f.sync_state != FileSyncState.ERROR.value
                    and f.local_path
                    and os.path.exists(f.local_path)
                ):
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
        # 同 cloud_sync_service.stop：3s 等待，避免退出时 OSS / httpx 阻塞导致卡死
        if not self._worker_thread.wait(3000):
            logger.warning("文件云同步 worker 线程未在 3s 内退出，触发 terminate 兜底")
            try:
                self._worker_thread.terminate()
                self._worker_thread.wait()
            except Exception as e:
                logger.debug(f"terminate file sync worker 失败（忽略）: {e}")
        logger.info("文件云同步服务已停止")

    def __del__(self):
        """析构兜底：绝不让运行中的 worker QThread 随对象一起析构。"""
        try:
            t = self.__dict__.get("_worker_thread")
            if t is not None and t.isRunning():
                t.quit()
                if not t.wait(2000):
                    t.terminate()
                    t.wait()
        except Exception:
            pass

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

    def enqueue_delete(self, local_id: int) -> None:
        """安排已落盘 tombstone 的云端删除；停止态由下次 start() 自动恢复。"""
        if self._state != CloudSyncState.RUNNING:
            return
        if local_id not in self._delete_queue:
            self._delete_queue.append(local_id)
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
        # Why 没有整体 early-return：三条管道（上传/下载/删除）各自有独立 busy
        # 标志，逐条判断即可。旧实现写了一行
        # `if self._uploading and self._downloading and self._deleting: return`，
        # 只有三者全部在忙才返回 —— 对结果无任何影响（下面各分支本来就会跳过
        # 忙的管道），纯冗余且误导读者以为需要整体互斥，已删除。
        if not self._uploading and self._upload_queue:
            lid = self._upload_queue.popleft()
            self._uploading = True
            self._trigger_upload.emit(lid)
        if not self._downloading and self._download_queue:
            lid = self._download_queue.popleft()
            self._downloading = True
            self._trigger_download.emit(lid)
        if not self._deleting and self._delete_queue:
            lid = self._delete_queue.popleft()
            self._deleting = True
            self._trigger_delete.emit(lid)

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

    @Slot(int, bool, str)
    def _on_delete_finished(self, local_id: int, ok: bool, err: str):
        self._deleting = False
        if not ok:
            self.sync_error.emit(err or "云端文件删除失败", 0)
        self.delete_finished.emit(local_id, ok, err)
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
