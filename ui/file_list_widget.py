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

    def __init__(self, path: str, device_id: str, device_name: str):
        super().__init__()
        self._path = path
        self._device_id = device_id
        self._device_name = device_name

    def run(self):
        try:
            # 超过 1 GB 直接在 stat 后拦截，避免先写后删
            size = os.path.getsize(self._path)
            if size > MAX_SINGLE_FILE_BYTES:
                self.done.emit(None, f"单文件不能超过 1 GB（当前 {_fmt_gb(size)}）")
                return
            sha, size, dest = hash_and_copy_into_container(self._path)
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
            self.done.emit(f, "")
        except Exception as e:
            logger.error(f"导入文件失败: {e}", exc_info=True)
            self.done.emit(None, str(e))


class FileListWidget(QWidget):
    """主 widget。外部注入 CloudFileRepository + FileCloudSyncService + EntitlementService。"""

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
        self._last_usage_pct: int = -1
        self._setup_ui()
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
        self.gate_banner_text = QLabel("文件云同步需要付费订阅（Basic / Super / Ultimate）")
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
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DropOnly)
        self.table.viewport().setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(FileListModel.COL_NAME, QHeaderView.Stretch)
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
        self.sync_service.sync_error.connect(self._on_sync_error)
        self.entitlement.entitlement_changed.connect(lambda *_: self._refresh_gate_view())

    # ---------- data ----------

    def reload(self):
        try:
            files = self.repo.list_files(include_deleted=False)
        except Exception as e:
            logger.warning(f"加载文件列表失败: {e}")
            files = []
        self.model.load(files)

    def _on_file_added_or_updated(self, f: CloudFile):
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

    def _show_sync_status(self, text: str) -> None:
        try:
            self.sync_status_label.setText(text)
            self.sync_status_label.setVisible(True)
            QTimer.singleShot(8000, lambda: self.sync_status_label.setVisible(False))
        except Exception:
            pass

    # ---------- entitlement / gate ----------

    def _refresh_gate_view(self):
        ent = self.entitlement.current()
        self.plan_label.setText({
            Plan.FREE: "套餐: 免费版",
            Plan.BASIC: "套餐: Basic",
            Plan.SUPER: "套餐: Super",
            Plan.ULTIMATE: "套餐: Ultimate",
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
        self.add_btn.setEnabled(enabled)
        self.table.setEnabled(True)  # 仍允许查看本地记录
        self.gate_banner.setVisible(not enabled)
        self.upgrade_btn.setVisible(not enabled)
        if not enabled:
            self.gate_banner_text.setText(reason or "文件云同步需要付费订阅")

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
        w = _ImportWorker(path, s.device_id, s.device_name)
        w.done.connect(lambda f, err, thr=w: self._after_import(f, err, thr))
        # thread 结束后统一清理 Python 引用 + Qt 对象
        w.finished.connect(lambda thr=w: self._import_threads.remove(thr)
                           if thr in self._import_threads else None)
        w.finished.connect(w.deleteLater)
        self._import_threads.append(w)
        w.start()

    def closeEvent(self, event):
        for thr in list(self._import_threads):
            thr.requestInterruption()
            thr.quit()
            thr.wait(1500)
        self._import_threads.clear()
        super().closeEvent(event)

    def _after_import(self, f, err: str, thread: _ImportWorker):
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
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.model.upsert(f)
        self.sync_service.enqueue_upload(f.id)

    # ---------- table interactions ----------

    def _has_local_copy(self, f: CloudFile) -> bool:
        return bool(f.local_path) and os.path.exists(f.local_path)

    def _can_download(self, f: CloudFile) -> bool:
        """云端有副本且本地没有——无论 state 是 REMOTE_ONLY 还是 SYNCED 但沙盒文件丢了。"""
        return bool(f.cloud_id) and not self._has_local_copy(f)

    def _on_double_click(self, index):
        f = self.model.file_at(index.row())
        if not f:
            return
        if self._has_local_copy(f):
            try:
                open_path = materialize_for_open(f.local_path, f.name)
            except Exception as e:
                logger.warning(f"准备打开路径失败，退回沙盒副本: {e}")
                open_path = f.local_path
            QDesktopServices.openUrl(QUrl.fromLocalFile(open_path))
            return
        if self._can_download(f):
            self.sync_service.enqueue_download(f.id)
            QMessageBox.information(
                self, "正在下载",
                f"本地副本缺失，已开始下载 '{f.name}'，完成后可再次双击打开。",
            )
            return
        QMessageBox.information(self, "无法打开", "本地副本缺失且云端没有可用副本。")

    def _on_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        f = self.model.file_at(idx.row())
        if not f:
            return
        menu = QMenu(self)
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
        del_act = menu.addAction("删除（本地 + 云端）")
        del_act.triggered.connect(lambda: self._delete_file(f))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _delete_file(self, f: CloudFile):
        reply = QMessageBox.question(
            self, "确认删除",
            f"删除 '{f.name}'？\n本地副本和云端副本都会被清除。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # 云端删（同步调用，失败仅提示；实际生产可放到后台）
        if f.cloud_id and self.cloud_api:
            try:
                self.cloud_api.files_delete(f.cloud_id)
            except Exception as e:
                logger.warning(f"云端删除失败: {e}")
        # 本地
        try:
            if f.local_path and os.path.exists(f.local_path):
                os.unlink(f.local_path)
        except OSError:
            pass
        self.repo.mark_deleted(f.id)
        self.model.remove_by_local_id(f.id)
