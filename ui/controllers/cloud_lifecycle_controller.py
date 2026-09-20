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

    def bootstrap_files_stack_after_login(self, activate: bool = False):
        """未登录启动后首次登录成功:补建 entitlement + 文件仓 + 文件同步,
        并把"我的文件"的升级占位替换成真实的 FileListWidget。

        用户主动打开文件页时，即使后台文件同步开关关闭，也启动本次文件管理。
        """
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

            if parent.file_sync_service is None and (settings().files_sync_enabled or activate):
                from core.file_sync_service import FileCloudSyncService
                parent.file_sync_service = FileCloudSyncService(
                    parent.file_repository,
                    parent.cloud_api,
                    parent.entitlement_service,
                    parent.repository,
                )
            if parent.file_sync_service is not None and (settings().files_sync_enabled or activate):
                try:
                    parent.file_sync_service.start()
                except Exception as e:
                    logger.warning(f"文件云同步启动失败: {e}", exc_info=True)
            if self.ctx is not None:
                self.ctx.cloud_api = parent.cloud_api
                self.ctx.entitlement_service = parent.entitlement_service
                self.ctx.file_repository = parent.file_repository
                self.ctx.file_sync_service = parent.file_sync_service
        except Exception as e:
            logger.warning(f"登录后补建文件同步栈失败: {e}", exc_info=True)
            return

        if not (parent.file_sync_service and parent.file_repository and parent.entitlement_service):
            return

        if parent.file_list_widget is not None:
            parent.file_list_widget.rebind_services(
                parent.file_repository,
                parent.file_sync_service,
                parent.entitlement_service,
                parent.cloud_api,
            )
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
                    self._refresh_cloud_state_after_upload
                )
                parent._cloud_sync_ui_connected = True

            if self.ctx is not None:
                self.ctx.cloud_api = parent.cloud_api
                self.ctx.cloud_sync_service = parent.cloud_sync_service
            QTimer.singleShot(0, parent.cloud_sync_service.start)
        except Exception as e:
            logger.warning(f"登录后补建云端同步失败: {e}", exc_info=True)

    def _refresh_cloud_state_after_upload(self, _count: int):
        self._parent.list_controller.refresh_cloud_state()

    def teardown_cloud_sync_after_logout(self):
        """登出：停止并释放云端同步 + 文件同步。

        Why: 两个 service 各自持有 worker QThread，必须在丢弃引用前 stop()，
        否则线程仍运行时对象被 GC → Qt qFatal("QThread: Destroyed while thread
        is still running") abort 进程。同时同步清理 ctx 上的引用保持一致。
        """
        parent = self._parent
        ctx = self.ctx
        if parent.cloud_sync_service is not None:
            cloud_sync_service = parent.cloud_sync_service
            try:
                # 先解绑长期存活的 clipboard_monitor sender，否则它会继续持有
                # 已停止的旧 service；重新登录后还会叠加一条新连接。
                if parent._cloud_sync_item_added_connected:
                    try:
                        self.clipboard_monitor.item_added.disconnect(
                            cloud_sync_service.enqueue_upload
                        )
                    except (RuntimeError, TypeError):
                        pass
                if parent._cloud_sync_ui_connected:
                    connections = (
                        (
                            cloud_sync_service.new_items_available,
                            parent.list_controller.on_new_items,
                        ),
                        (
                            cloud_sync_service.new_items_available,
                            self.advance_sync_after_cloud,
                        ),
                        (
                            cloud_sync_service.upload_completed,
                            self._refresh_cloud_state_after_upload,
                        ),
                    )
                    for signal, slot in connections:
                        try:
                            signal.disconnect(slot)
                        except (RuntimeError, TypeError):
                            pass
                cloud_sync_service.stop()
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
        
        # 清理 parent 与 AppContext 的其余凭证/文件服务缓存，防止旧实例残留
        parent.entitlement_service = None
        parent.file_repository = None
        if ctx is not None:
            ctx.cloud_api = None
            ctx.entitlement_service = None
            ctx.file_repository = None
