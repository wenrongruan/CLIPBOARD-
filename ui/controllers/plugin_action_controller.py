"""PluginActionController — 右键菜单、插件 dispatch 与异步执行回调。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu

from config import settings
from core.models import (
    ClipboardItem,
    ContentType,
    ImageClipboardItem,
    TextClipboardItem,
)
from core.plugin_api import PluginResult, PluginResultAction
from i18n import t

logger = logging.getLogger(__name__)


class PluginActionController(QObject):
    """右键菜单 + 插件异步执行 + 反馈条。"""

    # 工作线程把完整 ClipboardItem 加载完成后回到主线程派发
    plugin_item_loaded = Signal(str, str, object)

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self._parent = parent
        self.ctx = ctx
        self.plugin_item_loaded.connect(self.handle_plugin_item_loaded)

    # ---------- 便捷访问 ----------

    @property
    def plugin_manager(self):
        return self.ctx.plugin_manager if self.ctx is not None else self._parent.plugin_manager

    @property
    def extension_points(self):
        # Phase 7: 优先走扩展点注册表；未注入时回退到 PluginManager 的内置实现。
        if self.ctx is not None and getattr(self.ctx, "extension_points", None) is not None:
            return self.ctx.extension_points
        return None

    @property
    def repository(self):
        return self.ctx.repository if self.ctx is not None else self._parent.repository

    @property
    def clipboard_monitor(self):
        return self.ctx.clipboard_monitor if self.ctx is not None else self._parent.clipboard_monitor

    @property
    def share_service(self):
        return self._parent.share_service

    @property
    def entitlement_service(self):
        return self._parent.entitlement_service

    @property
    def tag_service(self):
        return self._parent.tag_service

    # ========== 右键菜单 ==========

    def show_context_menu(self, pos):
        list_widget = self._parent.list_widget
        list_item = list_widget.itemAt(pos)
        if not list_item:
            return
        row = list_widget.row(list_item)
        items = self._parent.list_controller.items
        if row < 0 or row >= len(items):
            return

        item = items[row]
        menu = QMenu(self._parent)
        item_ctrl = self._parent.item_controller

        copy_action = menu.addAction(f"📋 {t('ctx_copy')}")
        copy_action.triggered.connect(lambda: item_ctrl.on_item_clicked(item))

        if item.is_starred:
            star_action = menu.addAction(f"★ {t('ctx_unstar')}")
        else:
            star_action = menu.addAction(f"☆ {t('ctx_star')}")
        star_action.triggered.connect(lambda: item_ctrl.on_item_star(item))

        delete_action = menu.addAction(f"🗑 {t('ctx_delete')}")
        delete_action.triggered.connect(lambda: item_ctrl.on_item_delete(item))

        # 第二组:扩展能力收纳到「更多操作」子菜单
        menu.addSeparator()
        more_menu = menu.addMenu("⋯ 更多操作")

        share_action = more_menu.addAction("🔗 分享这些条目...")
        share_action.triggered.connect(lambda: item_ctrl.on_share_items([item]))
        if self.share_service is None and self.entitlement_service is None:
            share_action.setEnabled(False)

        tag_action = more_menu.addAction("🏷 添加标签...")
        tag_action.triggered.connect(lambda: item_ctrl.on_add_tags(item))
        if self.tag_service is None:
            tag_action.setEnabled(False)

        # 第三组:插件统一收进「插件」子菜单
        if self.plugin_manager:
            ep = self.extension_points
            if ep is not None:
                groups = ep.context_menu_actions(item)
            else:
                groups = self.plugin_manager.get_plugin_actions_grouped(item)
            if groups:
                plugin_root = menu.addMenu("🧩 插件")
                for group in groups:
                    actions = group["actions"]
                    if len(actions) == 1:
                        a = actions[0]
                        act = plugin_root.addAction(f"{a.icon} {a.label}")
                        act.triggered.connect(
                            lambda checked=False, pid=group["plugin_id"], aid=a.action_id:
                                self.run_plugin_action(pid, aid, item)
                        )
                    else:
                        sub = plugin_root.addMenu(f"{actions[0].icon} {group['plugin_name']}")
                        for a in actions:
                            act = sub.addAction(a.label)
                            act.triggered.connect(
                                lambda checked=False, pid=group["plugin_id"], aid=a.action_id:
                                    self.run_plugin_action(pid, aid, item)
                            )

        menu.exec(list_widget.mapToGlobal(pos))

    # ========== 插件执行 ==========

    def run_plugin_action(self, plugin_id: str, action_id: str, item: ClipboardItem):
        if isinstance(item, ImageClipboardItem):
            self.show_plugin_feedback(
                t("plugin_executing", name="...", percent=0),
                "pluginProgress",
                show_cancel=False,
            )
            item_id = item.id
            repo = self.repository
            signal = self.plugin_item_loaded

            def _load():
                try:
                    full = repo.get_item_by_id(item_id)
                except RuntimeError as e:
                    if "has been deleted" in str(e):
                        return
                    logger.error(f"加载插件所需图片失败: {e}", exc_info=True)
                    full = None
                    signal.emit(plugin_id, action_id, full)
                    return
                except Exception as e:
                    logger.error(f"加载插件所需图片失败: {e}", exc_info=True)
                    full = None
                signal.emit(plugin_id, action_id, full)

            self._parent._copy_executor.submit(_load)
            return

        self.dispatch_plugin_action(plugin_id, action_id, item)

    def handle_plugin_item_loaded(self, plugin_id: str, action_id: str, full_item):
        if not isinstance(full_item, ImageClipboardItem) or not full_item.image_data:
            self.show_plugin_feedback("❌ " + t("plugin_error"), "copyFeedbackError")
            return
        self.dispatch_plugin_action(plugin_id, action_id, full_item)

    def dispatch_plugin_action(self, plugin_id: str, action_id: str, item: ClipboardItem):
        if not self.plugin_manager.run_action(plugin_id, action_id, item):
            return

        plugin_name = self.plugin_manager.get_plugin_name(plugin_id)
        self.show_plugin_feedback(
            t("plugin_executing", name=plugin_name, percent=0),
            "pluginProgress",
            show_cancel=True,
        )

    def on_plugin_progress(self, percent: int, message: str):
        text = message if message else f"{percent}%"
        self.show_plugin_feedback(text, "pluginProgress", show_cancel=True)

    def on_plugin_finished(self, result: PluginResult, original_item: ClipboardItem):
        if not result.success:
            if result.cancelled:
                self._parent.copy_feedback_label.hide()
                return
            self.show_plugin_feedback(
                f"❌ {result.error_message or t('plugin_exec_failed')}", "copyFeedbackError"
            )
            return

        if result.action == PluginResultAction.NONE:
            self._parent.copy_feedback_label.hide()
            return

        if result.action == PluginResultAction.COPY:
            if result.content_type == ContentType.TEXT:
                temp_item: ClipboardItem = TextClipboardItem(
                    text_content=result.text_content or "",
                )
            else:
                temp_item = ImageClipboardItem(
                    image_data=result.image_data,
                    image_thumbnail=None,
                )
            self.clipboard_monitor.copy_to_clipboard(temp_item)
            self.show_plugin_feedback(t("copied_to_clipboard"), "copyFeedbackSuccess")

        elif result.action == PluginResultAction.SAVE:
            from utils.hash_utils import compute_content_hash
            hash_content = result.text_content or result.image_data
            if not hash_content:
                self.show_plugin_feedback("❌ 插件返回空内容", "copyFeedbackError")
                return
            common_kwargs = dict(
                content_hash=compute_content_hash(hash_content),
                preview=(result.text_content or "")[:100],
                device_id=settings().device_id,
                device_name=settings().device_name,
            )
            if result.content_type == ContentType.TEXT:
                new_item: ClipboardItem = TextClipboardItem(
                    **common_kwargs,
                    text_content=result.text_content or "",
                )
            else:
                new_item = ImageClipboardItem(
                    **common_kwargs,
                    image_data=result.image_data,
                    image_thumbnail=None,
                )
            self.repository.add_item(new_item)
            self._parent.list_controller.load_items()
            self.show_plugin_feedback(t("plugin_saved_entry"), "copyFeedbackSuccess")

        elif result.action == PluginResultAction.REPLACE:
            if original_item and original_item.id:
                success = self.repository.update_item_content(
                    original_item.id,
                    text_content=result.text_content,
                    image_data=result.image_data,
                    content_type=result.content_type.value if result.content_type else None,
                )
                if success:
                    self._parent.list_controller.load_items()
                    self.show_plugin_feedback(t("plugin_replaced_entry"), "copyFeedbackSuccess")
                else:
                    self.show_plugin_feedback("❌ " + t("plugin_error"), "copyFeedbackError")

    def on_plugin_error(self, message: str):
        self.show_plugin_feedback(f"❌ {message}", "copyFeedbackError")

    def show_plugin_feedback(self, text: str, object_name: str, show_cancel: bool = False):
        label = self._parent.copy_feedback_label
        if show_cancel:
            label.setText(f"{text}  [✕]")
            label.mousePressEvent = lambda e: self.cancel_plugin()
        else:
            label.setText(text)
            label.mousePressEvent = lambda e: None
            self._parent._feedback_timer.start(3000)
        label.setObjectName(object_name)
        label.style().polish(label)
        label.show()

    def cancel_plugin(self):
        if self.plugin_manager:
            self.plugin_manager.cancel_action()
        self._parent.copy_feedback_label.hide()
