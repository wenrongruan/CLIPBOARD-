"""时间线视图：按日期分组展示剪贴板条目。

特点：
- 按 created_at 的日期分组（Header 显示"YYYY-MM-DD (N)"）
- 每组内部复用 ClipboardItemWidget 渲染单条目
- 条目 > 500 条时，只展开最近 7 天的详情，其余日期只显示计数

信号：
- item_clicked(int)：单击一个条目，参数是 item_id
- item_context_menu(int, QPoint)：右键条目，参数是 item_id 和全局坐标
"""

from __future__ import annotations

import datetime as _dt
import logging
from collections import OrderedDict
from typing import Iterable, List, Optional

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.models import ClipboardItem
from .clipboard_item import ClipboardItemWidget

logger = logging.getLogger(__name__)


_DETAIL_WINDOW_DAYS = 7
_LARGE_DATASET_THRESHOLD = 500


class TimelineView(QWidget):
    """可滚动的时间线视图。"""

    item_clicked = Signal(int)                   # item_id
    item_context_menu = Signal(int, QPoint)      # item_id, global pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[ClipboardItem] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self._scroll, 1)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(6, 6, 6, 6)
        self._content_layout.setSpacing(8)
        self._content_layout.addStretch(1)  # 底部 stretch，使 group 向上堆积

        self._scroll.setWidget(self._content)
        # 记录日期 -> group widget（便于 scroll_to_date）
        self._group_widgets: "OrderedDict[_dt.date, QWidget]" = OrderedDict()

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    def set_items(self, items: Iterable[ClipboardItem]) -> None:
        """替换当前展示的条目列表。"""
        self._items = list(items or [])
        self._rebuild()

    def clear(self) -> None:
        self._items = []
        self._rebuild()

    def scroll_to_date(self, date: _dt.date) -> None:
        widget = self._group_widgets.get(date)
        if widget is None:
            return
        self._scroll.ensureWidgetVisible(widget)

    # ------------------------------------------------------------------
    # 内部：重建布局
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        # 清空现有 group widgets（保留末尾 stretch）
        layout = self._content_layout
        # 倒着移除：最后一项是 stretch，跳过
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._group_widgets.clear()

        if not self._items:
            empty = QLabel("暂无条目")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color:#888;padding:24px;")
            layout.insertWidget(layout.count() - 1, empty)
            self._group_widgets[_dt.date.today()] = empty  # 占位避免后续 None
            return

        # 按日期分组（新日期在上）
        groups: "OrderedDict[_dt.date, List[ClipboardItem]]" = OrderedDict()
        for item in self._items:
            try:
                d = _dt.datetime.fromtimestamp((item.created_at or 0) / 1000).date()
            except (OSError, ValueError, OverflowError):
                d = _dt.date.today()
            groups.setdefault(d, []).append(item)

        # 大数据集模式：仅渲染最近 N 天详情
        large_dataset = len(self._items) > _LARGE_DATASET_THRESHOLD
        today = _dt.date.today()
        cutoff = today - _dt.timedelta(days=_DETAIL_WINDOW_DAYS)

        # 日期倒序插入
        for day, day_items in sorted(groups.items(), key=lambda kv: kv[0], reverse=True):
            show_details = (not large_dataset) or (day >= cutoff)
            group_widget = self._build_group(day, day_items, show_details)
            layout.insertWidget(layout.count() - 1, group_widget)
            self._group_widgets[day] = group_widget

    def _build_group(
        self, day: _dt.date, items: List[ClipboardItem], show_details: bool,
    ) -> QWidget:
        frame = QFrame()
        frame.setObjectName("timelineGroup")
        frame.setStyleSheet(
            "QFrame#timelineGroup { background:#2a2a2a; border:1px solid #3c3c3c; "
            "border-radius:6px; }"
        )
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        header = QLabel(f"{day.isoformat()}  ({len(items)})")
        header.setStyleSheet("color:#e8e8e8;font-weight:600;font-size:12px;")
        v.addWidget(header)

        if not show_details:
            # 仅显示计数，不渲染每个条目
            hint = QLabel(f"共 {len(items)} 条（大数据集折叠）")
            hint.setStyleSheet("color:#888;font-size:11px;")
            v.addWidget(hint)
            return frame

        for item in items:
            try:
                row = ClipboardItemWidget(item)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"创建时间线条目 widget 失败: {exc}")
                continue
            # 点击 → emit item_id（复用同一信号）
            item_id = item.id
            if item_id is not None:
                row.clicked.connect(lambda it, iid=item_id: self.item_clicked.emit(iid))
            # 右键菜单：用 row 的 customContextMenu 复用起来比较重，直接
            # 借用 contextMenuEvent 不太好；这里只用 item_clicked 即可，
            # 右键菜单由上层 MainWindow 的列表视图提供。
            v.addWidget(row)

        return frame


__all__ = ["TimelineView"]
