"""云端文件管理视图（付费用户）。

职责：
- 列表展示本地+云端文件条目（调 CloudFileRepository.list_files）
- 拖拽 / "添加文件" 按钮导入（自动走 EntitlementService 付费闸与 1 GB 单文件上限）
- 顶部显示配额进度条（数据源 EntitlementService.current()）
- 未付费时以半透明覆盖 + 升级引导横幅
- 订阅 FileCloudSyncService 的进度信号，驱动状态列的 QProgressBar
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QThread, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableView,
    QAbstractItemView, QHeaderView, QFileDialog, QMessageBox, QMenu,
    QProgressBar, QFrame,
)

from config import settings, PRICING_URL
from core.cloud_api import CloudAPIClient
from core.entitlement_service import EntitlementService, Plan, MAX_SINGLE_FILE_BYTES
from core.file_models import CloudFile, FileSyncState
from core.file_repository import CloudFileRepository
from core.file_storage import (
    hash_and_copy_into_container,
    guess_mime,
    make_bookmark,
    materialize_for_open,
    remove_from_container,
    FileCopyCancelledError,
)

from .file_list_model import FileListModel, ProgressDelegate

logger = logging.getLogger(__name__)


def _fmt_gb(n: int) -> str:
    if n <= 0:
        return "0"
    return f"{n / (1 << 30):.2f} GB" if n >= (1 << 30) else f"{n / (1 << 20):.1f} MB"


class _ImportWorker(QThread):
    """后台导入：单次 pass 算 sha256 + 复制到沙盒。"""

    done = Signal(object, str)  # (CloudFile or None, error)

    def __init__(self, path: str, device_id: str, device_name: str,
                 *, generation: int = 0, account_identifier: str = ""):
        super().__init__()
        self._path = path
        self._device_id = device_id
        self._device_name = device_name
        self.generation = generation
        self.account_identifier = account_identifier
        self.result: CloudFile | None = None

    def run(self):
        try:
            # 超过 1 GB 直接在 stat 后拦截，避免先写后删
            size = os.path.getsize(self._path)
            if size > MAX_SINGLE_FILE_BYTES:
                self.done.emit(None, f"单文件不能超过 1 GB（当前 {_fmt_gb(size)}）")
                return
            sha, size, dest = hash_and_copy_into_container(
                self._path, is_cancelled=self.isInterruptionRequested,
            )
            now = int(time.time() * 1000)
            name = os.path.basename(self._path)
            f = CloudFile(
                name=name,
                original_path=self._path,
                local_path=str(dest),
                size_bytes=size,
                mime_type=guess_mime(name),
                content_sha256=sha,
                mtime=now,
                device_id=self._device_id,
                device_name=self._device_name,
                created_at=now,
                sync_state=FileSyncState.PENDING.value,
                bookmark=make_bookmark(self._path),
            )
            self.result = f
            self.done.emit(f, "")
        except FileCopyCancelledError:
            self.done.emit(None, "")
        except Exception as e:
            logger.error(f"导入文件失败: {e}", exc_info=True)
            self.done.emit(None, str(e))


class FileListWidget(QWidget):
    """主 widget。外部注入 CloudFileRepository + FileCloudSyncService + EntitlementService。"""

    _open_done = Signal(str, str)

    def __init__(
        self,
        repository: CloudFileRepository,
        sync_service,
        entitlement: EntitlementService,
        cloud_api: CloudAPIClient | None,
        parent=None,
    ):
        super().__init__(parent)
        self.repo = repository
        self.sync_service = sync_service
        self.entitlement = entitlement
        self.cloud_api = cloud_api
        self._import_threads: list[_ImportWorker] = []
        self._orphan_imports: dict[str, CloudFile] = {}
        self._import_generation = 0
        self._account_identifier = self._current_account()
        self._closing = False
        self._services_connected = False
        self._executor: ThreadPoolExecutor | None = None
        self._open_done.connect(self._on_open_ready)
        self._last_usage_pct: int = -1
        self._initial_cloud_refresh = False
        self._setup_ui()
        self._status_hide_timer = QTimer(self)
        self._status_hide_timer.setSingleShot(True)
        self._status_hide_timer.timeout.connect(self.sync_status_label.hide)
        self._inventory_timer = QTimer(self)
        self._inventory_timer.setSingleShot(True)
        self._inventory_timer.timeout.connect(self._refresh_inventory)
        self._connect_signals()
        self.reload()
        self._refresh_gate_view()

    # ---------- UI ----------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # 顶部配额条
        quota_row = QHBoxLayout()
        self.plan_label = QLabel("套餐: --")
        self.plan_label.setStyleSheet("color: #58a6ff; font-weight: bold;")
        quota_row.addWidget(self.plan_label)
        quota_row.addSpacing(10)
        self.quota_label = QLabel("已用 0 / 0")
        self.quota_label.setStyleSheet("color: #aaa;")
        quota_row.addWidget(self.quota_label)
        quota_row.addStretch()
        self.add_btn = QPushButton("添加文件")
        self.add_btn.clicked.connect(self._on_add_clicked)
        quota_row.addWidget(self.add_btn)
        self.upgrade_btn = QPushButton("升级套餐")
        self.upgrade_btn.clicked.connect(self._open_pricing)
        self.upgrade_btn.setVisible(False)
        quota_row.addWidget(self.upgrade_btn)
        root.addLayout(quota_row)

        manage_row = QHBoxLayout()
        self.scope_label = QLabel("当前账号的文件")
        self.scope_label.setStyleSheet("color:#aaa;font-size:11px;")
        manage_row.addWidget(self.scope_label)
        manage_row.addStretch()
        self.refresh_btn = QPushButton("刷新云端")
        self.refresh_btn.clicked.connect(self._refresh_inventory)
        manage_row.addWidget(self.refresh_btn)
        self.delete_btn = QPushButton("删除所选")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_selected)
        manage_row.addWidget(self.delete_btn)
        root.addLayout(manage_row)

        self.usage_bar = QProgressBar()
        self.usage_bar.setRange(0, 100)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setFixedHeight(6)
        self.usage_bar.setStyleSheet(
            "QProgressBar{background:#333;border:none;border-radius:3px;}"
            "QProgressBar::chunk{background:#0078d4;border-radius:3px;}"
        )
        root.addWidget(self.usage_bar)

        # 灰化横幅（未付费时显示）
        self.gate_banner = QFrame()
        self.gate_banner.setStyleSheet(
            "QFrame{background:rgba(255,165,0,0.12);border:1px solid #fbbf24;border-radius:6px;padding:8px;}"
        )
        gb_layout = QHBoxLayout(self.gate_banner)
        gb_layout.setContentsMargins(10, 6, 10, 6)
        self.gate_banner_text = QLabel(
            "文件云同步需要付费订阅（Basic / Super / Ultimate / Team）"
        )
        self.gate_banner_text.setStyleSheet("color: #fbbf24; background: transparent; border: none;")
        gb_layout.addWidget(self.gate_banner_text, 1)
        go = QPushButton("去升级")
        go.clicked.connect(self._open_pricing)
        gb_layout.addWidget(go)
        self.gate_banner.setVisible(False)
        root.addWidget(self.gate_banner)

        # 同步状态条（替代弹窗，避免打断主路径）
        self.sync_status_label = QLabel("")
        self.sync_status_label.setStyleSheet(
            "color:#fbbf24;background:rgba(255,165,0,0.10);"
            "border:1px solid rgba(251,191,36,0.4);border-radius:4px;padding:4px 8px;font-size:11px;"
        )
        self.sync_status_label.setWordWrap(True)
        self.sync_status_label.setVisible(False)
        root.addWidget(self.sync_status_label)

        # 表格
        self.table = QTableView()
        self.model = FileListModel(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DropOnly)
        self.table.viewport().setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.selectionModel().selectionChanged.connect(self._update_delete_button)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Stretch only gets space left over by the metadata columns, which can
        # reduce filenames to a few pixels in a narrow window. Keep a readable,
        # user-resizable name column and let the table scroll horizontally.
        header.setSectionResizeMode(FileListModel.COL_NAME, QHeaderView.Interactive)
        header.resizeSection(FileListModel.COL_NAME, 260)
        header.setSectionResizeMode(FileListModel.COL_SIZE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(FileListModel.COL_MTIME, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(FileListModel.COL_STATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(FileListModel.COL_DEVICE, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setCornerButtonEnabled(False)
        self.table.setItemDelegateForColumn(FileListModel.COL_STATE, ProgressDelegate(self.table))
        root.addWidget(self.table, 1)

        # 拖拽入窗级事件
        self.setAcceptDrops(True)

    def _connect_signals(self):
        self.sync_service.file_added.connect(self._on_file_added_or_updated)
        self.sync_service.file_updated.connect(self._on_file_added_or_updated)
        self.sync_service.file_deleted.connect(self.model.remove_by_local_id)
        self.sync_service.upload_progress.connect(self.model.set_progress)
        self.sync_service.download_progress.connect(self.model.set_progress)
        self.sync_service.upload_finished.connect(self._on_upload_finished)
        self.sync_service.download_finished.connect(self._on_upload_finished)
        self.sync_service.delete_finished.connect(self._on_delete_finished)
        self.sync_service.inventory_finished.connect(self._on_inventory_finished)
        self.sync_service.sync_error.connect(self._on_sync_error)
        self.entitlement.entitlement_changed.connect(self._on_entitlement_changed)
        self._services_connected = True

    def _disconnect_signals(self):
        if not self._services_connected:
            return
        connections = (
            (self.sync_service.file_added, self._on_file_added_or_updated),
            (self.sync_service.file_updated, self._on_file_added_or_updated),
            (self.sync_service.file_deleted, self.model.remove_by_local_id),
            (self.sync_service.upload_progress, self.model.set_progress),
            (self.sync_service.download_progress, self.model.set_progress),
            (self.sync_service.upload_finished, self._on_upload_finished),
            (self.sync_service.download_finished, self._on_upload_finished),
            (self.sync_service.delete_finished, self._on_delete_finished),
            (self.sync_service.inventory_finished, self._on_inventory_finished),
            (self.sync_service.sync_error, self._on_sync_error),
            (self.entitlement.entitlement_changed, self._on_entitlement_changed),
        )
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._services_connected = False

    def suspend_services(self) -> None:
        """账号切换前取消导入并停止接收旧服务结果。"""
        self._cancel_imports()
        self._disconnect_signals()
        self.model.load([])
        self.setEnabled(False)

    def rebind_services(
        self,
        repository: CloudFileRepository,
        sync_service,
        entitlement: EntitlementService,
        cloud_api: CloudAPIClient | None,
    ) -> None:
        """重新登录后切换到新服务实例，避免继续调用已停止的旧同步线程。"""
        unchanged = (
            self.repo is repository
            and self.sync_service is sync_service
            and self.entitlement is entitlement
            and self.cloud_api is cloud_api
        )
        account_identifier = self._current_account()
        if not unchanged or account_identifier != self._account_identifier:
            self._cancel_imports()
            self._account_identifier = account_identifier
        if not unchanged:
            self._disconnect_signals()
            self.repo = repository
            self.sync_service = sync_service
            self.entitlement = entitlement
            self.cloud_api = cloud_api
        if not self._services_connected:
            self._connect_signals()
        self.setEnabled(True)
        self.reload()
        self._refresh_gate_view()
        self._initial_cloud_refresh = False
        self.refresh_btn.setEnabled(True)

    # ---------- data ----------

    def reload(self):
        try:
            files = [
                f for f in self.repo.list_files(include_deleted=True)
                if not f.is_deleted or f.sync_state != FileSyncState.SYNCED.value
            ]
        except Exception as e:
            logger.warning(f"加载文件列表失败: {e}")
            files = []
        self.model.load(files)
        self._update_delete_button()

    def _on_file_added_or_updated(self, f: CloudFile):
        if f.is_deleted and f.sync_state == FileSyncState.SYNCED.value:
            self.model.remove_by_local_id(f.id)
        else:
            self.model.upsert(f)

    def _on_upload_finished(self, local_id: int, ok: bool, err: str):
        # 状态由 Worker 已落盘；这里只需刷新一行
        f = self.repo.get_by_id(local_id)
        if f:
            self.model.upsert(f)
        if not ok:
            name = f.name if f else str(local_id)
            self._show_sync_status(f"{name} 传输失败：{err or '未知错误'}")

    def _on_sync_error(self, msg: str, status: int):
        logger.warning(f"文件同步错误: {msg} (status={status})")
        self._show_sync_status(f"文件同步出错：{msg}")

    def _on_entitlement_changed(self, *_):
        self._refresh_gate_view()

    def _show_sync_status(self, text: str) -> None:
        try:
            self.sync_status_label.setText(text)
            self.sync_status_label.setVisible(True)
            self._status_hide_timer.start(8000)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_cloud_refresh:
            self._initial_cloud_refresh = True
            self._inventory_timer.start(0)

    def _refresh_inventory(self):
        if not self.sync_service.refresh_inventory():
            self._show_sync_status("云端文件刷新暂不可用，请确认已登录且文件同步已启动。")
            return
        self.refresh_btn.setEnabled(False)
        self._show_sync_status("正在读取当前账号的云端文件…")

    def _on_inventory_finished(self, count: int, success: bool, message: str):
        self.refresh_btn.setEnabled(True)
        self.reload()
        if success:
            suffix = f"；{message}" if message else ""
            self._show_sync_status(f"已读取 {count} 个云端文件{suffix}")
        else:
            self._show_sync_status(f"读取云端文件失败：{message}")

    def _selected_files(self) -> list[CloudFile]:
        return [
            f for index in self.table.selectionModel().selectedRows()
            if (f := self.model.file_at(index.row())) is not None
        ]

    def _update_delete_button(self, *_):
        files = self._selected_files()
        actionable = [
            f for f in files
            if not f.is_deleted or f.sync_state == FileSyncState.ERROR.value
        ]
        self.delete_btn.setEnabled(bool(actionable))
        self.delete_btn.setText(f"删除所选（{len(actionable)}）" if len(actionable) > 1 else "删除所选")

    def _on_delete_finished(self, local_id: int, ok: bool, err: str):
        f = self.repo.get_by_id(local_id)
        if not f:
            return
        if ok:
            self.model.remove_by_local_id(local_id)
            # 同一内容可能在删除过程中重新导入，不能删掉新记录共用的沙盒副本。
            if not self.repo.get_by_sha(f.content_sha256):
                try:
                    remove_from_container(f.content_sha256, f.local_path)
                except ValueError:
                    logger.warning("文件 %s 的 SHA 无效，跳过清理本地副本", local_id)
            self.entitlement.refresh_async()
            self._show_sync_status(f"已删除 {f.name}；云端用量正在更新。")
        else:
            self.model.upsert(f)
            self._show_sync_status(f"删除 {f.name} 失败：{err or '请稍后重试'}")
        self._update_delete_button()

    # ---------- entitlement / gate ----------

    def _refresh_gate_view(self):
        ent = self.entitlement.current()
        self.scope_label.setText(
            "当前账号的文件 · 团队成员文件不在此列表"
            if ent.plan == Plan.TEAM or getattr(ent, "team_spaces", 0) > 0
            else "当前账号的文件"
        )
        self.plan_label.setText({
            Plan.FREE: "套餐: 免费版",
            Plan.BASIC: "套餐: Basic",
            Plan.SUPER: "套餐: Super",
            Plan.ULTIMATE: "套餐: Ultimate",
            Plan.TEAM: "套餐: Team",
        }.get(ent.plan, f"套餐: {ent.plan.value}"))

        quota = ent.files_quota_bytes
        used = ent.files_used_bytes
        if quota > 0:
            self.quota_label.setText(f"已用 {_fmt_gb(used)} / {_fmt_gb(quota)}")
            pct = min(100, int(used * 100 / max(1, quota)))
            self.usage_bar.setValue(pct)
            if pct != self._last_usage_pct:
                if pct >= 95:
                    color = "#f87171"
                elif pct >= 80:
                    color = "#fbbf24"
                else:
                    color = "#0078d4"
                self.usage_bar.setStyleSheet(
                    f"QProgressBar{{background:#333;border:none;border-radius:3px;}}"
                    f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
                )
                if pct >= 95:
                    threshold = 95
                elif pct >= 85:
                    threshold = 85
                else:
                    threshold = 0
                last_threshold = getattr(self, "_last_quota_threshold", 0)
                if threshold and threshold > last_threshold:
                    if threshold >= 95:
                        msg = (
                            f"文件云同步空间已用 {pct}%，接近上限。"
                            "升级套餐可获得更大容量；或在表格中删除不再需要的文件。"
                        )
                    else:
                        msg = f"文件云同步已用 {pct}%。如需更大容量，可考虑升级套餐。"
                    self._show_sync_status(msg)
                self._last_quota_threshold = threshold
                self._last_usage_pct = pct
        else:
            self.quota_label.setText("已用 -- / --")
            self.usage_bar.setValue(0)
            self._last_usage_pct = 0

        enabled, reason = self.entitlement.can_use_files()
        refreshing, refresh_failed = getattr(
            self.entitlement, "refresh_state", lambda: (False, False)
        )()
        authenticated = self.cloud_api is not None and getattr(
            self.cloud_api, "is_authenticated", False
        )
        verifying = (
            not enabled
            and authenticated
            and not refresh_failed
            and (refreshing or getattr(ent, "fetched_at", 0) == 0)
        )
        verify_failed = not enabled and authenticated and refresh_failed
        self.add_btn.setEnabled(enabled)
        self.table.setEnabled(True)  # 仍允许查看本地记录
        self.gate_banner.setVisible(not enabled)
        self.upgrade_btn.setVisible(not enabled and not verifying and not verify_failed)
        if not enabled:
            self.gate_banner_text.setText(
                "正在验证云端套餐..." if verifying else
                "无法验证云端套餐，请检查网络后重新打开“我的文件”重试。"
                if verify_failed else reason or "文件云同步需要付费订阅"
            )

    def _open_pricing(self):
        QDesktopServices.openUrl(QUrl(PRICING_URL))

    # ---------- add / drag ----------

    def _on_add_clicked(self):
        ok, reason = self.entitlement.can_use_files()
        if not ok:
            QMessageBox.information(self, "需要升级", reason)
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要同步的文件", "", "所有文件 (*)")
        for p in paths:
            self._start_import(p)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        ok, reason = self.entitlement.can_use_files()
        if not ok:
            QMessageBox.information(self, "需要升级", reason)
            return
        for u in urls:
            p = u.toLocalFile()
            if p and os.path.isfile(p):
                self._start_import(p)

    def _start_import(self, path: str):
        if self._closing:
            return
        if self._current_account() != self._account_identifier:
            self._show_sync_status("账号已切换，请重新打开文件页后导入。")
            return
        # 预检：单文件 1 GB
        try:
            size = os.path.getsize(path)
        except OSError:
            QMessageBox.warning(self, "读取失败", f"无法读取文件: {path}")
            return
        ok, reason = self.entitlement.can_upload(size)
        if not ok:
            QMessageBox.warning(self, "无法上传", reason)
            return

        s = settings()
        w = _ImportWorker(
            path, s.device_id, s.device_name,
            generation=self._import_generation,
            account_identifier=self._current_account(),
        )
        w.done.connect(lambda f, err, thr=w: self._after_import(f, err, thr))
        # thread 结束后统一清理 Python 引用 + Qt 对象
        w.finished.connect(lambda thr=w: self._finish_import_thread(thr))
        w.finished.connect(w.deleteLater)
        self._import_threads.append(w)
        w.start()

    @staticmethod
    def _current_account() -> str:
        return (settings().cloud_user_email or "").strip().casefold()

    def _cancel_imports(self) -> None:
        self._import_generation += 1
        for thread in self._import_threads:
            thread.requestInterruption()

    def _finish_import_thread(self, thread: _ImportWorker) -> None:
        if thread in self._import_threads:
            self._import_threads.remove(thread)
        self._drain_orphan_imports()

    def stop_imports(self, timeout_ms: int = 1500) -> bool:
        """取消导入并在总时间预算内等待，未结束的线程继续保留引用。"""
        if not self._closing:
            self._closing = True
            self._cancel_imports()
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        stopped = True
        for thread in list(self._import_threads):
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if thread.isRunning() and not thread.wait(remaining):
                stopped = False
            elif thread.result is not None:
                self._cleanup_import_result(thread.result)
        self._drain_orphan_imports()
        return stopped

    def closeEvent(self, event):
        if not self.stop_imports():
            event.ignore()
            return
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def _cleanup_import_result(self, f: CloudFile) -> None:
        self._orphan_imports[f.content_sha256] = f
        self._drain_orphan_imports()

    def _drain_orphan_imports(self) -> None:
        # 等导入结果全部入库或取消后清理，避免删掉同内容并发导入的新副本。
        if self._import_threads and (not self._closing
                or any(thread.isRunning() for thread in self._import_threads)):
            return
        for sha, f in list(self._orphan_imports.items()):
            try:
                existing = self.repo.get_by_sha(sha, include_deleted=True)
                if existing is None or (existing.is_deleted
                        and existing.sync_state == FileSyncState.SYNCED.value):
                    remove_from_container(sha, f.local_path)
                self._orphan_imports.pop(sha, None)
            except Exception:
                logger.warning("清理过期导入副本失败", exc_info=True)

    def _after_import(self, f, err: str, thread: _ImportWorker):
        if (self._closing or thread.generation != self._import_generation
                or thread.account_identifier != self._current_account()
                or thread.account_identifier != self._account_identifier
                or not getattr(self.cloud_api, "is_authenticated", False)):
            if f is not None:
                self._cleanup_import_result(f)
            return
        if thread.isInterruptionRequested():
            if f is not None:
                self._cleanup_import_result(f)
            return
        if err or f is None:
            QMessageBox.warning(self, "导入失败", err or "未知错误")
            return
        # 相同 sha 已存在则复用
        existing = self.repo.get_by_sha(f.content_sha256)
        if existing is not None:
            QMessageBox.information(self, "已存在", f"该文件已在云端库中: {existing.name}")
            return
        try:
            f.id = self.repo.add_file(f)
        except Exception as e:
            self._cleanup_import_result(f)
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.model.upsert(f)
        self.sync_service.enqueue_upload(f.id)

    # ---------- table interactions ----------

    def _has_local_copy(self, f: CloudFile) -> bool:
        return bool(f.local_path) and os.path.exists(f.local_path)

    def _can_download(self, f: CloudFile) -> bool:
        """云端有副本且本地没有——无论 state 是 REMOTE_ONLY 还是 SYNCED 但沙盒文件丢了。"""
        return not f.is_deleted and bool(f.cloud_id) and not self._has_local_copy(f)

    def _on_double_click(self, index):
        f = self.model.file_at(index.row())
        if not f or f.is_deleted:
            return
        if self._has_local_copy(f):
            if self._closing:
                return
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1)
            local_path, name, signal = f.local_path, f.name, self._open_done

            def prepare():
                try:
                    open_path = materialize_for_open(local_path, name)
                    error = ""
                except Exception as exc:
                    logger.warning("准备打开副本失败: %s", exc)
                    open_path, error = "", str(exc)
                try:
                    signal.emit(open_path, error)
                except RuntimeError:
                    pass

            self._executor.submit(prepare)
            return
        if self._can_download(f):
            self.sync_service.enqueue_download(f.id)
            QMessageBox.information(
                self, "正在下载",
                f"本地副本缺失，已开始下载 '{f.name}'，完成后可再次双击打开。",
            )
            return
        QMessageBox.information(self, "无法打开", "本地副本缺失且云端没有可用副本。")

    def _on_open_ready(self, path: str, error: str):
        if self._closing:
            return
        if error or not path:
            QMessageBox.warning(self, "无法打开", f"无法创建可编辑的临时副本：{error or '未知错误'}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        f = self.model.file_at(idx.row())
        if not f:
            return
        menu = QMenu(self)
        if f.is_deleted:
            if f.sync_state == FileSyncState.ERROR.value:
                retry_act = menu.addAction("重试删除")
                retry_act.triggered.connect(lambda: self._retry_delete(f))
            menu.exec(self.table.viewport().mapToGlobal(pos))
            return
        open_act = menu.addAction("打开")
        open_act.triggered.connect(lambda: self._on_double_click(idx))
        if self._has_local_copy(f):
            reveal_act = menu.addAction("在 Finder/资源管理器中显示")
            reveal_act.triggered.connect(
                lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(Path(f.local_path).parent))
                )
            )
        if self._can_download(f):
            dl_act = menu.addAction("下载到本地")
            dl_act.triggered.connect(lambda: self.sync_service.enqueue_download(f.id))
        if f.sync_state in (FileSyncState.PENDING.value, FileSyncState.ERROR.value):
            retry_act = menu.addAction("重新上传")
            retry_act.triggered.connect(lambda: self.sync_service.enqueue_upload(f.id))
        menu.addSeparator()
        del_act = menu.addAction("删除此文件（本地 + 云端）")
        del_act.triggered.connect(lambda: self._delete_file(f))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _delete_file(self, f: CloudFile):
        self._delete_files([f])

    def _delete_selected(self):
        files = self._selected_files()
        for f in files:
            if f.is_deleted and f.sync_state == FileSyncState.ERROR.value:
                self._retry_delete(f)
        self._delete_files([f for f in files if not f.is_deleted])

    def _delete_files(self, files: list[CloudFile]):
        if not files:
            return
        names = "、".join(f.name for f in files[:3])
        if len(files) > 3:
            names += f" 等 {len(files)} 个文件"
        reply = QMessageBox.question(
            self, "确认删除",
            f"删除 {names}？\n当前账号的云端文件及本地副本都会被清除。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for f in files:
            if not f.id or not self.repo.mark_deleted(f.id):
                self._show_sync_status(f"无法标记 {f.name} 为待删除，请刷新列表后重试。")
                continue
            f.is_deleted = True
            f.sync_state = FileSyncState.PENDING.value
            self.model.upsert(f)
            # 即使此刻尚无 cloud_id，也要入队：进行中的上传可能随后才取得 cloud_id。
            self.sync_service.enqueue_delete(f.id)
        self._show_sync_status("删除请求已排队；云端确认后会释放空间。")
        self._update_delete_button()

    def _retry_delete(self, f: CloudFile):
        if not f.id or not f.is_deleted or f.sync_state != FileSyncState.ERROR.value:
            return
        self.repo.set_sync_state(f.id, FileSyncState.PENDING.value)
        f.sync_state = FileSyncState.PENDING.value
        self.model.upsert(f)
        self.sync_service.enqueue_delete(f.id)
        self._show_sync_status(f"正在重试删除 {f.name}…")
        self._update_delete_button()
