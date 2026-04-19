"""文件列表的 QAbstractTableModel 与进度条 delegate。"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, Qt, QSize,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QStyleOptionProgressBar, QApplication, QStyle, QStyledItemDelegate,
)

from core.file_models import CloudFile, FileSyncState


_HEADERS = ["名称", "大小", "修改时间", "状态", "设备"]

_STATE_DISPLAY = {
    FileSyncState.PENDING.value: "待上传",
    FileSyncState.SYNCING.value: "同步中",
    FileSyncState.SYNCED.value: "已同步",
    FileSyncState.ERROR.value: "失败",
    FileSyncState.REMOTE_ONLY.value: "仅云端",
}


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1 << 20:
        return f"{n / 1024:.1f} KB"
    if n < 1 << 30:
        return f"{n / (1 << 20):.1f} MB"
    return f"{n / (1 << 30):.2f} GB"


def _fmt_ts(ms: int) -> str:
    import datetime as _dt
    if not ms:
        return "--"
    try:
        return _dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return "--"


class FileListModel(QAbstractTableModel):
    """表格数据源。进度以 `progress` dict 按 local id 存 (done, total)。"""

    COL_NAME = 0
    COL_SIZE = 1
    COL_MTIME = 2
    COL_STATE = 3
    COL_DEVICE = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: List[CloudFile] = []
        self._progress: dict[int, tuple[int, int]] = {}

    # ---- data ----
    def load(self, files: list) -> None:
        self.beginResetModel()
        self._files = list(files)
        self._progress.clear()
        self.endResetModel()

    def upsert(self, f: CloudFile) -> None:
        for i, existing in enumerate(self._files):
            if existing.id == f.id:
                self._files[i] = f
                top = self.index(i, 0)
                bot = self.index(i, self.columnCount() - 1)
                self.dataChanged.emit(top, bot)
                return
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._files.insert(0, f)
        self.endInsertRows()

    def remove_by_local_id(self, local_id: int) -> None:
        for i, existing in enumerate(self._files):
            if existing.id == local_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._files.pop(i)
                self.endRemoveRows()
                self._progress.pop(local_id, None)
                return

    def file_at(self, row: int) -> Optional[CloudFile]:
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def set_progress(self, local_id: int, done: int, total: int) -> None:
        prev = self._progress.get(local_id)
        if prev == (done, total):
            return
        self._progress[local_id] = (done, total)
        for i, f in enumerate(self._files):
            if f.id == local_id:
                idx = self.index(i, self.COL_STATE)
                self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.UserRole + 1])
                return

    def progress_for(self, local_id: int) -> tuple[int, int]:
        return self._progress.get(local_id, (0, 0))

    # ---- Qt interface ----
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._files)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(_HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        if 0 <= section < len(_HEADERS):
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        f = self._files[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == self.COL_NAME:
                return f.name or "(未命名)"
            if col == self.COL_SIZE:
                return _fmt_size(f.size_bytes)
            if col == self.COL_MTIME:
                return _fmt_ts(f.mtime)
            if col == self.COL_STATE:
                return _STATE_DISPLAY.get(f.sync_state, f.sync_state)
            if col == self.COL_DEVICE:
                return f.device_name or f.device_id or ""
        elif role == Qt.ToolTipRole:
            if col == self.COL_NAME and f.local_path:
                return f.local_path
            if col == self.COL_STATE and f.last_error:
                return f.last_error
        elif role == Qt.ForegroundRole and col == self.COL_STATE:
            if f.sync_state == FileSyncState.ERROR.value:
                return QColor("#f87171")
            if f.sync_state == FileSyncState.SYNCED.value:
                return QColor("#4ade80")
        elif role == Qt.UserRole:
            return f
        elif role == Qt.UserRole + 1 and col == self.COL_STATE:
            # 返回 (is_syncing, done, total)
            if f.sync_state == FileSyncState.SYNCING.value:
                done, total = self._progress.get(f.id or 0, (0, f.size_bytes))
                return (True, done, total or f.size_bytes or 1)
            return (False, 0, 0)
        return None


class ProgressDelegate(QStyledItemDelegate):
    """状态列：同步中时画进度条，其余画文字。"""

    def paint(self, painter, option, index):
        data = index.data(Qt.UserRole + 1)
        if data and isinstance(data, tuple) and data[0]:
            done, total = data[1], max(1, data[2])
            opt = QStyleOptionProgressBar()
            opt.rect = option.rect.adjusted(4, 6, -4, -6)
            opt.minimum = 0
            opt.maximum = 100
            pct = int(min(100, max(0, done * 100 / total)))
            opt.progress = pct
            opt.textVisible = True
            opt.text = f"{pct}%"
            QApplication.style().drawControl(QStyle.CE_ProgressBar, opt, painter)
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 24))
        return size
