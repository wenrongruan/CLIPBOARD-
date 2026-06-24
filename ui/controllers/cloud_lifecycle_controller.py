"""CloudLifecycleController — 登录/登出引发的 stack 切换 + 云同步启停。"""
from __future__ import annotations

import logging
from typing import List

from PySide6.QtCore import QObject, QTimer

from config import settings
from core.models import ClipboardItem

logger = logging.getLogger(__name__)


class CloudLifecycleController(QObject):
    """登录/登出引发的 stack 切换 + 云同步启停 + 同步游标推进。"""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self._parent = parent
        self.ctx = ctx

    # ---------- 便捷访问 ----------

    @property
    def repository(self):
        return self.ctx.repository if self.ctx is not None else self._parent.repository

    @property
    def sync_service(self):
        return self.ctx.sync_service if self.ctx is not None else self._parent.sync_service

    @property
    def clipboard_monitor(self):
        return self.ctx.clipboard_monitor if self.ctx is not None else self._parent.clipboard_monitor

    # ========== 主入口 ==========

    def bootstrap_files_stack_after_login(self):
        """未登录启动后首次登录成功:补建 entitlement + 文件仓 + 文件同步,
        并把"我的文件"的升级占位替换成真实的 FileListWidget。"""
        parent = self._parent
        if parent.cloud_api is None or not parent.cloud_api.is_authenticated:
            return
        try:
            if parent.entitlement_service is None:
                from core.entitlement_service import get_entitlement_service
                parent.entitlement_service = get_entitlement_service(
                    cloud_api=parent.cloud_api, repository=parent.repository,
                )
            else:
                parent.entitlement_service.set_cloud_api(parent.cloud_api)
            parent.entitlement_service.refresh_async()

            if parent.file_repository is None:
                from core.file_repository import CloudFileRepository
                parent.file_repository = CloudFileRepository(parent.repository.db)

            if parent.file_sync_service is None and settings().files_sync_enabled:
                from core.file_sync_service import FileCloudSyncService
                parent.file_sync_service = FileCloudSyncService(
                    parent.file_repository,
                    parent.cloud_api,
                    parent.entitlement_service,
                    parent.repository,
                )
                try:
                    parent.file_sync_service.start()
                except Exception as e:
                    logger.warning(f"文件云同步启动失败: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"登录后补建文件同步栈失败: {e}", exc_info=True)
            return

        if parent.file_list_widget is not None:
            parent.file_list_widget.reload()
            return

        if not (parent.file_sync_service and parent.file_repository and parent.entitlement_service):
            return

        try:
            from ..file_list_widget import FileListWidget
            widget = FileListWidget(
                parent.file_repository,
                parent.file_sync_service,
                parent.entitlement_service,
                parent.cloud_api,
            )
        except Exception as e:
            logger.warning(f"初始化文件页失败: {e}", exc_info=True)
            return

        if parent._file_page_placeholder is not None:
            idx = parent._stack.indexOf(parent._file_page_placeholder)
            if idx >= 0:
                parent._stack.removeWidget(parent._file_page_placeholder)
            parent._file_page_placeholder.deleteLater()
            parent._file_page_placeholder = None
        parent.file_list_widget = widget
        parent._stack.addWidget(widget)
        if parent._stack.currentIndex() == 1:
            parent._stack.setCurrentIndex(1)

    def advance_sync_after_cloud(self, items: List[ClipboardItem]):
        if not items:
            return
        max_id = max((item.id for item in items if item.id), default=0)
        if max_id:
            self.sync_service.advance_sync_id(max_id)

    def bootstrap_cloud_sync_after_login(self):
        parent = self._parent
        if parent.cloud_api is None or not parent.cloud_api.is_authenticated:
            return
        try:
            if parent.cloud_sync_service is None:
                from core.cloud_sync_service import CloudSyncService

                parent.cloud_sync_service = CloudSyncService(
                    parent.repository,
                    parent.cloud_api,
                    parent.entitlement_service,
                )

            if not parent._cloud_sync_item_added_connected:
                self.clipboard_monitor.item_added.connect(parent.cloud_sync_service.enqueue_upload)
                parent._cloud_sync_item_added_connected = True

            if not parent._cloud_sync_ui_connected:
                parent.cloud_sync_service.new_items_available.connect(
                    parent.list_controller.on_new_items
                )
                parent.cloud_sync_service.new_items_available.connect(self.advance_sync_after_cloud)
                parent.cloud_sync_service.upload_completed.connect(
                    lambda _count: parent.list_controller.refresh_cloud_state()
                )
                parent._cloud_sync_ui_connected = True

            QTimer.singleShot(0, parent.cloud_sync_service.start)
        except Exception as e:
            logger.warning(f"登录后补建云端同步失败: {e}", exc_info=True)

    def teardown_cloud_sync_after_logout(self):
        """登出：停止并释放云端同步 + 文件同步。

        Why: 两个 service 各自持有 worker QThread，必须在丢弃引用前 stop()，
        否则线程仍运行时对象被 GC → Qt qFatal("QThread: Destroyed while thread
        is still running") abort 进程。同时同步清理 ctx 上的引用保持一致。
        """
        parent = self._parent
        ctx = self.ctx
        if parent.cloud_sync_service is not None:
            try:
                parent.cloud_sync_service.stop()
            except Exception as e:
                logger.warning(f"退出登录后停止云端同步失败: {e}", exc_info=True)
            finally:
                parent.cloud_sync_service = None
                parent._cloud_sync_item_added_connected = False
                parent._cloud_sync_ui_connected = False
                if ctx is not None:
                    ctx.cloud_sync_service = None
        # 文件同步此前在登出路径被遗漏：worker 线程会一直运行，直到对象被 GC
        # 或进程退出时触发 abort。这里一并停止并释放引用。
        fss = getattr(parent, "file_sync_service", None)
        if fss is not None:
            try:
                fss.stop()
            except Exception as e:
                logger.warning(f"退出登录后停止文件同步失败: {e}", exc_info=True)
            finally:
                parent.file_sync_service = None
                if ctx is not None:
                    ctx.file_sync_service = None
