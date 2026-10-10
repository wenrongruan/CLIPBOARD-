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
        self._services_account = (settings().cloud_user_email or "").strip().casefold()
        self._services_api = getattr(parent, "cloud_api", None)
        self._retiring_services = []
        self._retiring_entitlements = []
        self._retiring_executors = []
        self._auth_callbacks = []
        self._auth_changing = False
        self._shutting_down = False
        self._pending_files_bootstrap = False
        self._pending_files_activate = False
        self._pending_cloud_bootstrap = False
        self._retire_timer = QTimer(self)
        self._retire_timer.setInterval(50)
        self._retire_timer.timeout.connect(self._poll_retiring)

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

    def retiring_resources(self):
        return (tuple(self._retiring_services), tuple(self._retiring_entitlements),
                tuple(self._retiring_executors))

    def begin_shutdown(self):
        self._shutting_down = True
        self._auth_callbacks.clear()
        self._retire_timer.stop()

    def _stop_and_retain(self, service):
        try:
            stopped = service.stop(timeout_ms=0)
        except Exception:
            logger.warning("停止旧账号同步服务失败，将继续保留并等待", exc_info=True)
            stopped = False
        thread = getattr(service, "_worker_thread", None)
        if (stopped is False or (thread is not None and not thread.wait(0))):
            if service not in self._retiring_services:
                self._retiring_services.append(service)

    def prepare_auth_change(self, callback):
        """等待旧账号后台任务收尾后才允许更换客户端或凭证。"""
        if self._shutting_down:
            return
        self._auth_changing = True
        self._auth_callbacks.append(callback)
        self.teardown_cloud_sync_after_logout()
        parent = self._parent
        for widget in [parent] + parent.findChildren(QObject):
            executor = getattr(widget, "_cloud_executor", None) if widget is parent else getattr(widget, "_executor", None)
            if executor is not None and executor not in self._retiring_executors:
                executor.shutdown(wait=False, cancel_futures=True)
                self._retiring_executors.append(executor)
                if widget is parent:
                    parent._cloud_executor = None
                else:
                    widget._executor = None
        manager = getattr(parent, "plugin_manager", None)
        if manager is not None:
            manager.cancel_action()
            manager.set_cloud_client(None)
        self._retire_timer.start()
        self._poll_retiring()

    def _poll_retiring(self):
        if self._shutting_down:
            return
        for service in list(self._retiring_services):
            thread = getattr(service, "_worker_thread", None)
            if thread is not None and not thread.wait(0):
                continue
            if thread is None and service.stop(timeout_ms=0) is False:
                continue
            try:
                service.persist_sync_cursor()
            except Exception:
                logger.warning("保存旧账号同步游标失败", exc_info=True)
            self._retiring_services.remove(service)
        for entitlement in list(self._retiring_entitlements):
            if not any(thread.is_alive() for thread in entitlement.active_refresh_threads()):
                self._retiring_entitlements.remove(entitlement)
        self._retiring_executors[:] = [
            executor for executor in self._retiring_executors
            if any(thread.is_alive() for thread in executor._threads)
        ]
        page = getattr(self._parent, "file_list_widget", None)
        imports_pending = bool(page is not None and page._import_threads)
        manager = getattr(self._parent, "plugin_manager", None)
        plugins_pending = bool(manager is not None and any(
            not worker.wait(0) for worker in manager.active_workers()
        ))
        from ui.cloud_login_widget import active_login_futures
        login_pending = any(not future.done() for future in active_login_futures())
        if (self._retiring_services or self._retiring_entitlements or self._retiring_executors
                or imports_pending or plugins_pending or login_pending):
            return
        if self._auth_callbacks:
            callback = self._auth_callbacks.pop(0)
            from concurrent.futures import ThreadPoolExecutor
            if getattr(self._parent, "_cloud_executor", None) is None:
                self._parent._cloud_executor = ThreadPoolExecutor(max_workers=1)
            callback()
            return
        self._retire_timer.stop()
        if self._pending_cloud_bootstrap:
            self._pending_cloud_bootstrap = False
            self.bootstrap_cloud_sync_after_login()
        if self._pending_files_bootstrap:
            activate = self._pending_files_activate
            self._pending_files_bootstrap = self._pending_files_activate = False
            self.bootstrap_files_stack_after_login(activate=activate)

    def _prepare_bootstrap(self, files=False, activate=False):
        if self._shutting_down:
            return False
        from ui.cloud_login_widget import active_login_futures
        if self._auth_callbacks or any(not future.done() for future in active_login_futures()):
            if files:
                self._pending_files_bootstrap = True
                self._pending_files_activate |= activate
            else:
                self._pending_cloud_bootstrap = True
            self._retire_timer.start()
            return False
        account = (settings().cloud_user_email or "").strip().casefold()
        if self._auth_changing:
            self._auth_changing = False
            self._services_account, self._services_api = account, self._parent.cloud_api
        elif account != self._services_account or self._services_api is not self._parent.cloud_api:
            self.teardown_cloud_sync_after_logout()
            self._services_account, self._services_api = account, self._parent.cloud_api
        if self._retiring_services or self._retiring_entitlements or self._retiring_executors:
            if files:
                self._pending_files_bootstrap = True
                self._pending_files_activate |= activate
            else:
                self._pending_cloud_bootstrap = True
            self._retire_timer.start()
            return False
        return True

    def bootstrap_files_stack_after_login(self, activate: bool = False):
        """未登录启动后首次登录成功:补建 entitlement + 文件仓 + 文件同步,
        并把"我的文件"的升级占位替换成真实的 FileListWidget。

        用户主动打开文件页时，即使后台文件同步开关关闭，也启动本次文件管理。
        """
        parent = self._parent
        if parent.cloud_api is None or not parent.cloud_api.is_authenticated:
            return
        if not self._prepare_bootstrap(files=True, activate=activate):
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
                parent.file_repository = CloudFileRepository(
                    parent.repository.db,
                    account_identifier=settings().cloud_user_email,
                )
            else:
                parent.file_repository.bind_account(settings().cloud_user_email)

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
        if not self._prepare_bootstrap():
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
            service = parent.cloud_sync_service

            def start_if_current():
                if (not self._shutting_down and not self._auth_changing
                        and parent.cloud_sync_service is service):
                    service.start()

            QTimer.singleShot(0, start_if_current)
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
        page = getattr(parent, "file_list_widget", None)
        if page is not None:
            page.suspend_services()
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
                self._stop_and_retain(cloud_sync_service)
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
                self._stop_and_retain(fss)
            except Exception as e:
                logger.warning(f"退出登录后停止文件同步失败: {e}", exc_info=True)
            finally:
                parent.file_sync_service = None
                if ctx is not None:
                    ctx.file_sync_service = None
        
        # 清理 parent 与 AppContext 的其余凭证/文件服务缓存，防止旧实例残留
        entitlement = getattr(parent, "entitlement_service", None)
        if entitlement is not None and hasattr(entitlement, "active_refresh_threads"):
            entitlement.set_cloud_api(None)
            self._retiring_entitlements.append(entitlement)
        parent.entitlement_service = None
        parent.file_repository = None
        if ctx is not None:
            ctx.cloud_api = None
            ctx.entitlement_service = None
            ctx.file_repository = None
        if self._retiring_services or self._retiring_entitlements:
            self._retire_timer.start()
