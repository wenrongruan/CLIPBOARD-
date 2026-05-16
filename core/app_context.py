"""应用装配层（ServiceRegistry）。

bootstrap() 在 main 线程一次性装配所有 service；构造完即视为 immutable。
所有 UI / controller / 旧的全局取值入口（如 get_cloud_client）都从这里取。

设计说明：
- 与 main.py 中现有的初始化逻辑等价：未登录用户不会持有 CloudSyncService / FileCloudSyncService /
  EntitlementService 实例（这些字段保持 None），避免无网络/无 token 场景下的多余开销。
- cloud_api 始终构造（即使未登录也作为登录表单 client 持有），与现有 get_cloud_client() 行为一致。
- 不在 bootstrap 阶段调用 plugin_manager.load_plugins() / clipboard_monitor.start() / sync_service.start()，
  这些 lifecycle 由 main.py 在 UI 准备好后触发。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# bootstrap() 名义上只在主线程调用，但用 module-level 锁把契约写死，
# 防止偶发的并发误用造成 service 重复装配。
_bootstrap_lock = threading.Lock()


class AppContext:
    _instance: "Optional[AppContext]" = None

    def __init__(self):
        self.db = None
        self.repository = None
        self.clipboard_monitor = None
        self.sync_service = None
        self.cloud_api = None
        self.cloud_sync_service = None
        self.file_sync_service = None
        self.file_repository = None
        self.entitlement_service = None
        self.space_service = None
        self.tag_service = None
        self.share_service = None
        self.plugin_manager = None
        self.extension_points = None  # filled in Phase 7
        self._cloud_sync_error: Optional[str] = None
        self._lock = threading.Lock()

    @classmethod
    def bootstrap(cls) -> "AppContext":
        with _bootstrap_lock:
            if cls._instance is not None:
                return cls._instance
            return cls._do_bootstrap()

    @classmethod
    def _do_bootstrap(cls) -> "AppContext":
        from config import get_cloud_access_token, settings
        from core.db_factory import create_database_manager
        from core.repository import ClipboardRepository
        from core.clipboard_monitor import ClipboardMonitor
        from core.sync_service import SyncService
        from core.cloud_api import get_cloud_client
        from core.plugin_manager import PluginManager
        from core.space_service import SpaceService
        from core.tag_service import TagService
        from core.share_service import ShareService

        ctx = cls()

        # ---------- 基础 ----------
        ctx.db = create_database_manager()
        ctx.repository = ClipboardRepository(ctx.db)
        ctx.clipboard_monitor = ClipboardMonitor(ctx.repository)
        ctx.sync_service = SyncService(ctx.repository)

        # ---------- 云端 API client（始终构造，未登录时仍可作为登录表单 client） ----------
        ctx.cloud_api = get_cloud_client()

        # ---------- 云端业务服务（仅登录后装配；保持与 main.py 历史行为一致） ----------
        if get_cloud_access_token():
            try:
                from core.cloud_sync_service import CloudSyncService

                ctx.cloud_sync_service = CloudSyncService(ctx.repository, ctx.cloud_api)

                # 付费闸 + 文件云同步
                try:
                    from core.entitlement_service import get_entitlement_service
                    from core.file_repository import CloudFileRepository
                    from core.file_sync_service import FileCloudSyncService

                    ctx.entitlement_service = get_entitlement_service(
                        cloud_api=ctx.cloud_api, repository=ctx.repository,
                    )
                    ctx.entitlement_service.refresh_async()

                    ctx.file_repository = CloudFileRepository(ctx.db)
                    if settings().files_sync_enabled:
                        ctx.file_sync_service = FileCloudSyncService(
                            ctx.file_repository,
                            ctx.cloud_api,
                            ctx.entitlement_service,
                            ctx.repository,
                        )
                except Exception as ent_err:
                    logger.warning(f"文件云同步初始化失败: {ent_err}", exc_info=True)
                    ctx.file_repository = None
                    ctx.file_sync_service = None

                logger.info("云端同步已启用（叠加模式）")
            except Exception as e:
                logger.error(f"云端同步启动失败，已降级到本地存储: {e}", exc_info=True)
                ctx.cloud_sync_service = None
                ctx._cloud_sync_error = str(e)

        # ---------- 插件 ----------
        from core.plugin_extension_points import ExtensionPointRegistry
        ctx.extension_points = ExtensionPointRegistry()
        ctx.plugin_manager = PluginManager(extension_points=ctx.extension_points)

        # ---------- v3.4：空间 / 标签 / 分享 ----------
        try:
            ctx.space_service = SpaceService(ctx.repository)
            ctx.tag_service = TagService(ctx.repository)
            # ShareService 用 factory 懒取 cloud_api（登录状态动态）
            ctx.share_service = ShareService(
                ctx.repository,
                cloud_api_factory=lambda: ctx.cloud_api,
            )
        except Exception as svc_err:
            logger.warning(f"v3.4 服务初始化失败（侧栏/分享功能将降级）: {svc_err}", exc_info=True)

        cls._instance = ctx
        logger.info("AppContext bootstrapped")
        return ctx

    @classmethod
    def current(cls) -> "AppContext":
        if cls._instance is None:
            raise RuntimeError("AppContext.bootstrap() has not been called")
        return cls._instance

    def shutdown(self) -> None:
        with self._lock:
            try:
                # 顺序：monitor → 3 个 sync service → plugin manager → cloud client reset → db
                # 异常隔离：每个 stop 单独 try，确保后续 teardown 不被前一个失败阻塞。
                if self.clipboard_monitor:
                    try:
                        self.clipboard_monitor.stop()
                    except Exception:
                        logger.exception("clipboard_monitor.stop() 异常")
                if self.sync_service:
                    try:
                        self.sync_service.stop()
                    except Exception:
                        logger.exception("sync_service.stop() 异常")
                if self.cloud_sync_service:
                    try:
                        self.cloud_sync_service.stop()
                    except Exception:
                        logger.exception("cloud_sync_service.stop() 异常")
                if self.file_sync_service:
                    try:
                        self.file_sync_service.stop()
                    except Exception:
                        logger.exception("file_sync_service.stop() 异常")
                if self.plugin_manager:
                    try:
                        # PluginManager 用 unload_all() 释放插件，没有 shutdown()
                        self.plugin_manager.unload_all()
                    except Exception:
                        logger.exception("plugin_manager.unload_all() 异常")
                try:
                    from core.cloud_api import reset_cloud_client
                    reset_cloud_client()
                except Exception:
                    logger.exception("reset_cloud_client() 异常")
                if self.db:
                    try:
                        if hasattr(self.db, "close"):
                            self.db.close()
                    except Exception:
                        logger.exception("db.close() 异常")
            finally:
                AppContext._instance = None
                logger.info("AppContext shutdown")
