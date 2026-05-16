"""ItemActionController — 单项操作:点击/复制/收藏/删除/保存/分享/打标签。"""
from __future__ import annotations

import logging
from typing import List

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from core import analytics
from core.models import ClipboardItem, ImageClipboardItem
from config import PRICING_URL
from i18n import t

logger = logging.getLogger(__name__)


class ItemActionController(QObject):
    """单项点击/复制反馈/删除/收藏/保存图片/拷云端 URL/分享/加标签。"""

    # 跨线程信号(原 MainWindow 上五个 Signal 的迁移)
    image_load_done = Signal(object)
    save_image_done = Signal(bool, str, str)
    image_url_done = Signal(str)
    cloud_delete_done = Signal(bool, int, str)

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self._parent = parent
        self.ctx = ctx
        # 内部信号串接
        self.image_load_done.connect(self.handle_image_loaded)
        self.save_image_done.connect(self.handle_save_image_done)
        self.image_url_done.connect(self.handle_image_url_done)
        self.cloud_delete_done.connect(self.handle_cloud_delete_done)

    # ---------- 便捷访问 ----------

    @property
    def repository(self):
        return self.ctx.repository if self.ctx is not None else self._parent.repository

    @property
    def clipboard_monitor(self):
        return self.ctx.clipboard_monitor if self.ctx is not None else self._parent.clipboard_monitor

    @property
    def cloud_api(self):
        # cloud_api 是动态的(登录/登出后会变),始终从 parent 取
        return self._parent.cloud_api

    @property
    def cloud_sync_service(self):
        return self._parent.cloud_sync_service

    @property
    def share_service(self):
        return self._parent.share_service

    @property
    def tag_service(self):
        return self._parent.tag_service

    @property
    def entitlement_service(self):
        return self._parent.entitlement_service

    # ========== 复制反馈 ==========

    def show_copy_feedback(self, success: bool):
        label = self._parent.copy_feedback_label
        if success:
            label.setText(t("copied_to_clipboard"))
            label.setObjectName("copyFeedbackSuccess")
        else:
            label.setText(t("copy_failed"))
            label.setObjectName("copyFeedbackError")
        label.style().polish(label)
        label.show()
        self._parent._feedback_timer.start(2000)

    # ========== 点击/复制 ==========

    def on_item_clicked(self, item: ClipboardItem):
        try:
            analytics.mark_first(analytics.FIRST_COPY_HISTORY)
        except Exception:
            pass
        if item.is_image:
            label = self._parent.copy_feedback_label
            label.setText("正在加载图片...")
            label.setObjectName("copyFeedbackSuccess")
            label.style().polish(label)
            label.show()

            item_id = item.id
            repo = self.repository
            signal = self.image_load_done

            def _load():
                try:
                    full = repo.get_item_by_id(item_id)
                except Exception as e:
                    logger.error(f"加载图片失败: {e}")
                    full = None
                signal.emit(full)

            self._parent._copy_executor.submit(_load)
            return

        success = self.clipboard_monitor.copy_to_clipboard(item)
        self.show_copy_feedback(success)

    def handle_image_loaded(self, full_item):
        success = False
        if full_item and getattr(full_item, "image_data", None):
            try:
                success = self.clipboard_monitor.copy_to_clipboard(full_item)
            except Exception as e:
                logger.error(f"写入剪贴板失败: {e}")
        elif full_item:
            logger.warning(f"图片 id={full_item.id} 无完整数据，可能云端尚未下载")
        self.show_copy_feedback(success)

    # ========== 删除 / 云端删除 ==========

    def on_item_delete(self, item: ClipboardItem):
        reply = QMessageBox.question(
            self._parent,
            t("confirm_delete"),
            t("delete_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.repository.delete_item(item.id)
            self._parent.list_controller.load_items()

    def on_cloud_delete(self, item: ClipboardItem):
        if not item.cloud_id or not self.cloud_api:
            return
        reply = QMessageBox.question(
            self._parent,
            "删除云端副本",
            "确定删除该条目的云端副本？\n本地记录不受影响。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        cloud_id = item.cloud_id
        item_id = item.id
        api = self.cloud_api
        signal = self.cloud_delete_done

        def _do_delete():
            try:
                api.delete_item(cloud_id)
                signal.emit(True, item_id, "")
            except Exception as e:
                signal.emit(False, item_id, str(e))

        self._parent._cloud_executor.submit(_do_delete)

    def handle_cloud_delete_done(self, success: bool, item_id: int, error: str):
        if success:
            self.repository.clear_cloud_id(item_id)
            self._parent.list_controller.load_items()
        else:
            logger.warning(f"删除云端副本失败: {error}")

    # ========== 收藏 ==========

    def on_item_star(self, item: ClipboardItem):
        try:
            analytics.mark_first(analytics.FIRST_STAR)
        except Exception:
            pass
        self.repository.toggle_star(item.id)
        new_starred = not item.is_starred

        if item.cloud_id and self.cloud_api:
            cloud_id = item.cloud_id
            api = self.cloud_api
            self._parent._cloud_executor.submit(lambda: api.toggle_star(cloud_id))
        elif new_starred and not item.cloud_id and self.cloud_sync_service:
            full_item = self.repository.get_item_by_id(item.id)
            if full_item:
                full_item.is_starred = True
                self.cloud_sync_service.enqueue_upload(full_item)

        self._parent.list_controller.load_items()

    # ========== 保存图片 ==========

    def on_item_save(self, item: ClipboardItem):
        path, _ = QFileDialog.getSaveFileName(
            self._parent,
            t("save_image"),
            "",
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
        )
        if not path:
            return

        item_id = item.id
        repo = self.repository
        signal = self.save_image_done

        def _do_save():
            try:
                full = repo.get_item_by_id(item_id)
            except Exception as e:
                logger.error(f"加载图片以保存失败: {e}", exc_info=True)
                signal.emit(False, path, str(e))
                return
            if not isinstance(full, ImageClipboardItem) or not full.image_data:
                signal.emit(False, path, "image_load_failed")
                return
            try:
                with open(path, "wb") as f:
                    f.write(full.image_data)
                signal.emit(True, path, "")
            except Exception as e:
                logger.error(f"写入图片文件失败: {e}", exc_info=True)
                signal.emit(False, path, str(e))

        self._parent._copy_executor.submit(_do_save)

    def handle_save_image_done(self, success: bool, path: str, error: str):
        if success:
            QMessageBox.information(
                self._parent,
                t("success") if callable(t) else "成功",
                f"已保存到：{path}",
            )
        else:
            if error == "image_load_failed":
                QMessageBox.warning(self._parent, t("error"), t("image_load_failed"))
            else:
                QMessageBox.critical(self._parent, t("error"), t("save_failed", error=error))

    # ========== 云端图片链接 ==========

    def on_image_url_copy(self, item: ClipboardItem):
        if not item.cloud_id or not self.cloud_api:
            return

        label = self._parent.copy_feedback_label
        label.setText("正在获取图片链接...")
        label.setObjectName("copyFeedbackSuccess")
        label.style().polish(label)
        label.show()

        cloud_id = item.cloud_id
        api = self.cloud_api
        signal = self.image_url_done

        def _fetch_url():
            try:
                url = api.get_image_url(cloud_id) or ""
            except Exception as e:
                logger.warning(f"获取图片链接失败: {e}")
                url = ""
            signal.emit(url)

        self._parent._cloud_executor.submit(_fetch_url)

    def handle_image_url_done(self, url: str):
        if url:
            QApplication.clipboard().setText(url)
            self.show_copy_feedback(True)
        else:
            label = self._parent.copy_feedback_label
            label.setText("获取图片链接失败")
            label.setObjectName("copyFeedbackError")
            label.style().polish(label)
            self._parent._feedback_timer.start(2000)

    # ========== 分享 / 标签 ==========

    def on_share_items(self, items: List[ClipboardItem]):
        if not items:
            return
        if self.share_service is None:
            QMessageBox.warning(self._parent, "分享不可用", "未初始化 ShareService，无法创建分享链接。")
            return

        if self.entitlement_service is not None:
            try:
                can_share = bool(self.entitlement_service.current().can_share_link)
            except Exception:
                can_share = True
            if not can_share:
                box = QMessageBox(self._parent)
                box.setIcon(QMessageBox.Information)
                box.setWindowTitle("分享链接需要升级套餐")
                box.setText(
                    "分享链接是付费增强能力——把这一组文本/图片发给同事、客户"
                    "或自己其他设备一次性使用，链接到期自动失效。\n\n"
                    "你当前的套餐暂不支持创建分享链接。"
                )
                view_btn = box.addButton("查看套餐", QMessageBox.AcceptRole)
                box.addButton("取消", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is view_btn:
                    try:
                        QDesktopServices.openUrl(QUrl(PRICING_URL))
                    except Exception:
                        pass
                return

        try:
            from ..share_dialog import ShareLinkDialog
        except Exception as exc:
            QMessageBox.critical(self._parent, "错误", f"无法加载分享对话框：{exc}")
            return
        dlg = ShareLinkDialog(
            items=items,
            share_service=self.share_service,
            space_id=self._parent.list_controller.current_space_id or "",
            parent=self._parent,
        )
        dlg.exec()

    def on_add_tags(self, item: ClipboardItem):
        if self.tag_service is None:
            QMessageBox.warning(self._parent, "标签不可用", "未初始化 TagService。")
            return
        text, ok = QInputDialog.getText(
            self._parent, "添加标签", "输入标签名（多个用逗号分隔）：",
        )
        if not ok or not text:
            return
        names = [n.strip() for n in text.split(",") if n.strip()]
        if not names:
            return
        space_id = item.space_id or self._parent.list_controller.current_space_id or ""
        try:
            tag_ids = self.tag_service.apply_tag_names(
                item_id=item.id,
                space_id=space_id,
                tag_names=names,
            )
        except Exception as exc:
            logger.warning(f"添加标签失败: {exc}", exc_info=True)
            QMessageBox.warning(self._parent, "添加失败", f"添加标签失败：{exc}")
            return
        sidebar = getattr(self._parent, "sidebar", None)
        if sidebar is not None:
            sidebar.refresh_tags(space_id if space_id else None)
        self.show_copy_feedback(True)
        if hasattr(self._parent, "copy_feedback_label"):
            self._parent.copy_feedback_label.setText(f"已添加 {len(tag_ids)} 个标签")
