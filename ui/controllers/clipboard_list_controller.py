"""ClipboardListController — 列表加载、分页、搜索、侧栏/视图切换。"""
from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QListWidgetItem, QMessageBox

from core import analytics
from core.models import ClipboardItem
from config import PAGE_SIZE, PRICING_URL
from i18n import t

from ..clipboard_item import ClipboardItemWidget

logger = logging.getLogger(__name__)


class ClipboardListController(QObject):
    """负责列表渲染、分页、搜索、侧栏路由、视图切换。"""

    # 单项点击转发给 ItemActionController(由 shell 串接)
    item_clicked = Signal(object)
    # 单项基本操作(由 widget 信号转发,shell 串到 ItemActionController)
    item_delete_requested = Signal(object)
    item_star_requested = Signal(object)
    item_save_requested = Signal(object)
    cloud_delete_requested = Signal(object)
    image_url_copy_requested = Signal(object)

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self._parent = parent
        self.ctx = ctx
        # 状态
        self._current_page = 0
        self._total_pages = 1
        self._page_size = PAGE_SIZE
        self._search_query = ""
        self._starred_only = False
        self._items: List[ClipboardItem] = []
        self._current_space_id: Optional[str] = None
        self._current_tag_id: Optional[str] = None
        self._view_mode = "list"
        self._load_error_notified = False

        # 搜索防抖定时器(_setup_ui 时 parent 还没有创建 search_input,这里只起 timer)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.do_search)

        # list 宽度变化时重算行高(防抖)
        self._resize_debounce = QTimer(self)
        self._resize_debounce.setSingleShot(True)
        self._resize_debounce.setInterval(80)
        self._resize_debounce.timeout.connect(self.refresh_row_sizes)
        self._resize_filter_installed = False
        self._last_viewport_w = 0

    # ---------- 内部便捷访问 ----------

    @property
    def repository(self):
        return self.ctx.repository if self.ctx is not None else self._parent.repository

    # ========== 加载 / 渲染 ==========

    def load_items(self):
        try:
            if self._search_query:
                # search() 的 space_id 语义：None=仅个人空间(space_id IS NULL)，
                # ""=不过滤。而本 controller 里 _current_space_id=None 表示
                # "未选择特定空间，显示全部"（与 get_items 路径一致），所以这里
                # 要把 None 翻译成 "" 才能让搜索覆盖所有空间。
                search_space_id = (
                    "" if self._current_space_id is None else self._current_space_id
                )
                items, total = self.repository.search_by_keyword(
                    self._search_query, self._current_page, self._page_size,
                    starred_only=self._starred_only,
                    space_id=search_space_id,
                )
            elif self._current_tag_id:
                items = self.repository.get_items_by_tag(
                    self._current_tag_id,
                    page=self._current_page + 1,
                    page_size=self._page_size,
                )
                total = len(items)
            else:
                # _current_space_id 语义：None = 显示全部空间；具体值 = 过滤到该空间。
                # get_items 的 space_id 语义：None = 仅个人空间(IS NULL)；"" = 全部空间。
                # 因此 controller 的 None 必须翻译为 ""，具体值原样透传。
                get_space_id = "" if self._current_space_id is None else self._current_space_id
                items, total = self.repository.get_items(
                    self._current_page, self._page_size,
                    starred_only=self._starred_only,
                    space_id=get_space_id,
                )

            self._items = items
            self._total_pages = max(1, (total + self._page_size - 1) // self._page_size)
            self.update_list()
            self.update_pagination()
            self._load_error_notified = False
        except Exception as e:
            logger.error(f"加载剪贴板条目失败: {e}", exc_info=True)
            self._items = []
            self._total_pages = 1
            try:
                self.update_list()
                self.update_pagination()
                self._parent.list_widget.clear()
                placeholder = QListWidgetItem("加载失败，请查看日志或重启应用。")
                placeholder.setFlags(Qt.NoItemFlags)
                self._parent.list_widget.addItem(placeholder)
            except Exception:
                logger.error("更新失败占位 UI 时出错", exc_info=True)
            if not self._load_error_notified:
                self._load_error_notified = True
                QMessageBox.warning(
                    self._parent,
                    t("error") if callable(t) else "错误",
                    f"加载剪贴板条目失败：{e}\n\n请查看日志，必要时重启应用。",
                )

    def make_list_item(self, item: ClipboardItem):
        """创建 ClipboardItemWidget 和对应的 QListWidgetItem，连接信号。"""
        widget = ClipboardItemWidget(item)
        widget.clicked.connect(self.item_clicked)
        widget.delete_clicked.connect(self.item_delete_requested)
        widget.star_clicked.connect(self.item_star_requested)
        widget.save_clicked.connect(self.item_save_requested)
        widget.cloud_delete_clicked.connect(self.cloud_delete_requested)
        widget.image_url_clicked.connect(self.image_url_copy_requested)

        list_item = QListWidgetItem()
        hint = widget.sizeHint()
        if widget.hasHeightForWidth():
            target_w = self._target_row_width(hint.width())
            # +8: QListWidget::item 的 margin(3+3) + border(1+1) 占据的纵向空间
            hint_h = widget.heightForWidth(target_w) + 8
        else:
            hint_h = hint.height()
        min_h = 92 if item.is_image else 76
        # 宽度仍用 widget 的 sizeHint().width(),让 QListView 自行扩展到 viewport;
        # 若强行写 viewport 宽,纵向滚动条出现后 viewport 变窄,行会比 viewport 宽,
        # 导致右侧按钮被滚动条遮挡。
        list_item.setSizeHint(QSize(hint.width(), max(hint_h, min_h)))
        return list_item, widget

    def _target_row_width(self, fallback: int) -> int:
        """list viewport 的可用宽度,优先用真实值,启动期回退到 fallback。"""
        try:
            vw = self._parent.list_widget.viewport().width()
        except Exception:
            vw = 0
        return vw if vw > 50 else max(fallback, 400)

    def refresh_row_sizes(self):
        """list 宽度变化时按真实宽度重算各行高度,避免文字裁切。"""
        lw = getattr(self._parent, "list_widget", None)
        if lw is None:
            return
        target_w = self._target_row_width(lw.viewport().width() or 600)
        for i in range(lw.count()):
            li = lw.item(i)
            if li is None:
                continue
            w = lw.itemWidget(li)
            if isinstance(w, ClipboardItemWidget) and w.hasHeightForWidth():
                h = w.heightForWidth(target_w) + 8
                min_h = 92 if w.item.is_image else 76
                cur_w = li.sizeHint().width()
                li.setSizeHint(QSize(cur_w, max(h, min_h)))

    def _install_resize_filter(self):
        if self._resize_filter_installed:
            return
        lw = getattr(self._parent, "list_widget", None)
        if lw is None:
            return
        try:
            lw.viewport().installEventFilter(self)
            self._resize_filter_installed = True
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            try:
                w = obj.width()
                if w != self._last_viewport_w:
                    self._last_viewport_w = w
                    self._resize_debounce.start()
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def update_list(self):
        list_widget = self._parent.list_widget
        self._install_resize_filter()
        list_widget.clear()
        for item in self._items:
            list_item, widget = self.make_list_item(item)
            list_widget.addItem(list_item)
            list_widget.setItemWidget(list_item, widget)
        if getattr(self._parent, "timeline_view", None) is not None:
            self._parent.timeline_view.set_items(self._items)

    def prepend_item(self, item: ClipboardItem):
        """在列表顶部插入单个新条目，避免全量重建。"""
        list_widget = self._parent.list_widget
        if item.id is not None:
            for idx, existing in enumerate(self._items):
                if existing.id == item.id:
                    list_widget.takeItem(idx)
                    self._items.pop(idx)
                    break

        list_item, widget = self.make_list_item(item)
        list_widget.insertItem(0, list_item)
        list_widget.setItemWidget(list_item, widget)
        self._items.insert(0, item)

        if list_widget.count() > self._page_size:
            list_widget.takeItem(list_widget.count() - 1)
            if len(self._items) > self._page_size:
                self._items.pop()

    def on_item_added(self, item: ClipboardItem):
        if self._current_page == 0 and not self._search_query and not self._starred_only:
            self.prepend_item(item)
        elif self._current_page == 0 and not self._search_query:
            self.load_items()
        try:
            analytics.mark_first(analytics.FIRST_RECORD)
        except Exception:
            pass
        onboarding = getattr(self._parent, "_onboarding_dialog", None)
        if onboarding is not None:
            try:
                onboarding.advance_on_copy()
            except Exception:
                pass

    def refresh_cloud_state(self):
        """上传完成后，把当前列表里 cloud_id=None 但 DB 已经写入 cloud_id 的条目
        刷新成"已同步"外观（出现 ☁ 按钮，图片条目出现 🔗）。

        Why: ClipboardItemWidget 在构造时一次性根据 is_cloud_synced 决定按钮列；
        云同步 worker 写 DB 后不会回写内存 item，也未触发任何 UI 刷新，导致
        云图标永远不出现，除非整页重载。
        """
        if not self._items:
            return
        pending_ids = [it.id for it in self._items if it.id and it.cloud_id is None]
        if not pending_ids:
            return
        try:
            mapping = self.repository.get_cloud_ids_for_ids(pending_ids)
        except Exception as e:
            logger.debug(f"刷新云端标记失败: {e}")
            return

        list_widget = self._parent.list_widget
        changed_idx = []
        for idx, item in enumerate(self._items):
            if item.id is None or item.cloud_id is not None:
                continue
            new_cid = mapping.get(item.id)
            if new_cid:
                item.cloud_id = new_cid
                changed_idx.append(idx)
        if not changed_idx:
            return

        for idx in changed_idx:
            li = list_widget.item(idx)
            if li is None:
                continue
            new_widget = ClipboardItemWidget(self._items[idx])
            new_widget.clicked.connect(self.item_clicked)
            new_widget.delete_clicked.connect(self.item_delete_requested)
            new_widget.star_clicked.connect(self.item_star_requested)
            new_widget.save_clicked.connect(self.item_save_requested)
            new_widget.cloud_delete_clicked.connect(self.cloud_delete_requested)
            new_widget.image_url_clicked.connect(self.image_url_copy_requested)
            list_widget.setItemWidget(li, new_widget)
            if new_widget.hasHeightForWidth():
                target_w = self._target_row_width(li.sizeHint().width())
                h = new_widget.heightForWidth(target_w) + 8
                min_h = 92 if self._items[idx].is_image else 76
                li.setSizeHint(QSize(li.sizeHint().width(), max(h, min_h)))

    def on_new_items(self, items: List[ClipboardItem]):
        # 来自其他设备的新记录
        if self._current_page == 0 and not self._search_query:
            self.load_items()

    # ========== 搜索 ==========

    def on_search_changed(self, text: str):
        self._search_timer.stop()
        self._search_timer.start(300)
        if text.strip():
            try:
                analytics.mark_first(analytics.FIRST_SEARCH)
            except Exception:
                pass

    def do_search(self):
        self._search_query = self._parent.search_input.text().strip()
        self._current_page = 0
        self.load_items()

    def show_search_help(self):
        QMessageBox.information(
            self._parent,
            "搜索语法",
            "支持以下结构化搜索：\n\n"
            "关键词：直接输入即可（多个关键词 AND 连接）\n"
            "from:chrome — 按来源 App 过滤\n"
            "tag:work — 按标签过滤\n"
            "space:<id> — 按空间过滤\n"
            "after:2026-04-01 / before:2026-05-01 — 日期范围\n"
            "size:>1MB / size:<=500KB — 内容大小\n"
            "is:starred / is:text / is:image — 类型过滤\n"
            '"引号短语" — 精确短语匹配\n'
            "/正则/ — 正则表达式\n"
            "-key:value — 取反（如 -from:chrome）\n",
        )

    # ========== 分页 ==========

    def update_pagination(self):
        self._parent.page_label.setText(f"{self._current_page + 1} / {self._total_pages}")
        self._parent.prev_btn.setEnabled(self._current_page > 0)
        self._parent.next_btn.setEnabled(self._current_page < self._total_pages - 1)

    def prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self.load_items()

    def next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self.load_items()

    def toggle_starred_filter(self):
        self._starred_only = not self._starred_only
        self._parent.star_filter_btn.setText("★" if self._starred_only else "☆")
        self._current_page = 0
        self.load_items()

    # ========== 视图 / 侧栏 ==========

    def on_view_changed(self, view_id: int):
        if view_id == 1:
            self._view_mode = "timeline"
            timeline_view = getattr(self._parent, "timeline_view", None)
            if timeline_view is not None:
                self._parent._view_stack.setCurrentWidget(timeline_view)
                timeline_view.set_items(self._items)
        else:
            self._view_mode = "list"
            self._parent._view_stack.setCurrentWidget(self._parent.list_widget)

    def on_timeline_item_clicked(self, item_id: int):
        for it in self._items:
            if it.id == item_id:
                self.item_clicked.emit(it)
                return

    def on_sidebar_space_changed(self, space_id):
        self._current_space_id = space_id
        space_service = self.ctx.space_service if self.ctx is not None else self._parent.space_service
        if space_service is not None:
            try:
                space_service.set_current_space(space_id)
            except Exception as exc:
                logger.debug(f"set_current_space 失败: {exc}")
        self._current_page = 0
        self.load_items()

    def on_sidebar_tag_changed(self, tag_id):
        self._current_tag_id = tag_id
        self._current_page = 0
        self.load_items()

    def on_sidebar_create_space(self):
        sidebar = getattr(self._parent, "sidebar", None)
        if sidebar is not None:
            sidebar.refresh_spaces()

    def on_sidebar_manage_team(self):
        # 打开设置对话框，默认切到"团队" tab
        self._parent._show_settings(initial_tab="team")

    def on_sidebar_upgrade(self):
        QDesktopServices.openUrl(QUrl(PRICING_URL))

    # ========== Tab 切换 ==========

    def on_tab_changed(self, index: int):
        self._parent._stack.setCurrentIndex(index)
        file_list_widget = getattr(self._parent, "file_list_widget", None)
        if index == 1 and file_list_widget is not None:
            file_list_widget.reload()
            ent = self.ctx.entitlement_service if self.ctx is not None else self._parent.entitlement_service
            if ent:
                ent.refresh_async()

    # ========== 提供给其它控制器/shell 的只读访问 ==========

    @property
    def items(self) -> List[ClipboardItem]:
        return self._items

    @property
    def current_space_id(self) -> Optional[str]:
        return self._current_space_id
