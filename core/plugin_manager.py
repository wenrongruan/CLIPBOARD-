"""
插件管理器模块

负责插件的完整生命周期:
- 扫描、加载、卸载插件
- 版本校验、依赖检查
- 异步执行（含取消、超时、并发互斥）
- 插件配置管理
- 插件日志初始化
"""

import contextlib
import importlib
import importlib.util
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt

from config import (
    APP_VERSION,
    IS_APPSTORE_BUILD,
    get_config_dir,
    get_user_plugins_dir,
    is_plugin_enabled,
)
from i18n import t
from .models import ClipboardItem
from .plugin_api import PluginBase, PluginAction, PluginResult

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


# 插件可直接读取的只读属性（不含任何凭据）。base_url 用于插件向子进程传递服务端地址。
_PLUGIN_PUBLIC_ATTRS = frozenset({"base_url"})

# 权限代理只扫描 facade 的这 4 个 domain client。
# Why 不扫 facade 本身：facade 上有 get_tokens()/set_tokens()/_access_token 等
# 凭据入口，它们都没有 _plugin_permission 标注 —— 旧实现"带标注才拦、无标注放行"
# 属于默认允许，插件一行 get_tokens() 就能拿走长期凭据。改为默认拒绝后，
# 只有在 domain client 上显式标注了 @requires_plugin_permission 的方法才可被插件调用。
_PLUGIN_CLIENT_ATTRS = ("auth", "sync_client", "files", "spaces")


def _collect_plugin_allowed_methods(real_client) -> dict:
    """扫描 domain client，收集所有标注了 _plugin_permission 的方法。

    返回 {方法名: (bound_method, 所需权限)}。跨 client 同名方法后者覆盖前者，
    但所需权限一致（都由装饰器决定），不会产生权限缝隙。
    """
    allowed: dict = {}
    for sub_name in _PLUGIN_CLIENT_ATTRS:
        sub = getattr(real_client, sub_name, None)
        if sub is None:
            continue
        for name in dir(sub):
            if name.startswith("_"):
                continue
            try:
                attr = getattr(sub, name)
            except Exception:
                continue
            required = getattr(attr, "_plugin_permission", None)
            if required:
                allowed[name] = (attr, required)
    return allowed


def _make_plugin_cloud_client_proxy(real_client, permissions: list):
    """构造默认拒绝的 CloudAPIClient 权限代理。

    Why 闭包捕获而不是实例属性：旧实现把 real client 存在实例 __dict__ 里
    （object.__setattr__(self, "_real", ...)），而 __getattr__ 只在常规查找
    失败时才触发 —— `proxy._real` 直接绕过全部权限检查。现在 real client 与
    白名单都捕获在闭包里，实例没有 __dict__（__slots__ = ()），插件访问任何
    属性（包括 _real / __dict__）都只能落到 __getattr__ 的权限判定上。
    """
    perms = frozenset(permissions or ())
    allowed = _collect_plugin_allowed_methods(real_client)

    class _PluginCloudClientProxy:
        """按 manifest.permissions 拦截 CloudAPIClient 调用（默认拒绝）。"""

        __slots__ = ()

        def __getattr__(self, name):
            if name in _PLUGIN_PUBLIC_ATTRS:
                return getattr(real_client, name)
            entry = allowed.get(name)
            if entry is not None:
                attr, required = entry
                if required and required not in perms:
                    raise PermissionError(
                        f"插件未声明 '{required}' 权限，禁止调用 CloudAPIClient.{name}"
                    )
                return attr
            if name.startswith("_") and name != "__class__":
                raise PermissionError(f"插件禁止访问 CloudAPIClient 私有属性: {name}")
            raise PermissionError(
                f"CloudAPIClient.{name} 未登记为插件可用 API（默认拒绝）。"
                f"如确需开放，请在对应 domain client 方法上标注 @requires_plugin_permission"
            )

        def __setattr__(self, name, value):
            # 拒绝写入，防止插件改 token / 覆盖代理状态
            raise PermissionError(f"插件禁止写入 CloudAPIClient 属性: {name}")

    return _PluginCloudClientProxy()


@contextlib.contextmanager
def _project_root_in_syspath():
    """临时将项目根加入 sys.path,退出时恢复原状。

    插件在 `exec_module` 阶段会执行顶层 import,需要能解析 `core.*`/`config`
    等项目内模块。永久 insert 会污染全局命名空间,因此只在加载窗口内生效。

    Why（并发注意）: 当前 load_plugins 是顺序调用，_load_single_plugin 同步执行，
    sys.path 的瞬时修改不会产生并发冲突。若未来改为并行加载（如 ThreadPool
    同时 exec 多个插件），全局 sys.path 的临时注入会出现竞态（一个线程提前
    恢复导致另一个线程 import 失败）。届时应改为向 spec 直接传递
    submodule_search_locations，而不是修改全局 sys.path。
    """
    already_present = _PROJECT_ROOT in sys.path
    if not already_present:
        sys.path.insert(0, _PROJECT_ROOT)
    try:
        yield
    finally:
        if not already_present:
            try:
                sys.path.remove(_PROJECT_ROOT)
            except ValueError:
                pass


class PluginWorker(QThread):
    """在工作线程中执行插件操作，支持取消"""
    progress = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, plugin: PluginBase, action_id: str, item: ClipboardItem):
        super().__init__()
        self._plugin = plugin
        self._action_id = action_id
        self._item = item
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            result = self._plugin.execute(
                self._action_id,
                self._item,
                progress_callback=self._on_progress,
                cancel_check=lambda: self._cancelled,
            )
            if self._cancelled:
                # 取消后仍需发射信号，确保 _cleanup_worker 被调用
                self.finished.emit(PluginResult(success=False, cancelled=True))
                return
            self.finished.emit(result)
        except Exception as e:
            self._plugin.logger.exception(
                f"Plugin execution failed: {self._action_id}"
            )
            if self._cancelled:
                self.finished.emit(PluginResult(success=False, cancelled=True))
            else:
                self.error.emit(f"{self._plugin.get_name()}: {str(e)}")

    def _on_progress(self, percent: int, message: str):
        if not self._cancelled:
            self.progress.emit(percent, message)


class PluginManager(QObject):
    """插件管理器 — 管理插件的完整生命周期"""

    # 信号
    action_progress = Signal(int, str)        # (进度百分比, 消息)
    action_finished = Signal(object, object)  # (PluginResult, 原始 ClipboardItem)
    action_error = Signal(str)                # 错误消息

    plugins_changed = Signal()

    def __init__(self, parent=None, extension_points=None):
        super().__init__(parent)
        self._plugins: Dict[str, PluginBase] = {}
        self._manifests: Dict[str, dict] = {}
        self._plugin_status: Dict[str, dict] = {}  # {id: {status, message}}
        self._plugin_paths: Dict[str, Path] = {}   # {id: plugin_dir_path}
        self._active_worker: Optional[PluginWorker] = None
        self._timeout_timer: Optional[QTimer] = None
        self._cloud_client = None  # 共享的云端客户端实例
        # Phase 7: 可选的扩展点注册表，由 AppContext 注入；插件加载/卸载时同步。
        self._extension_points = extension_points

    # ========== 生命周期 ==========

    def load_plugins(self):
        """扫描并加载所有插件"""
        plugin_dirs = self._get_plugin_dirs()
        for plugin_dir in plugin_dirs:
            if not plugin_dir.exists():
                continue
            # 内置目录（打包进 .app / exe）之外的用户目录：权限过宽就整体跳过。
            # Why: exec_module 是以主程序全部权限执行的任意代码，目录若被
            # group/other 可写，同机其他用户的进程即可投放插件拿到代码执行。
            if not self._is_builtin_plugin_dir(plugin_dir) and self._is_unsafe_plugin_dir(plugin_dir):
                logger.error(
                    f"插件目录权限过宽（group/other 可写），已拒绝加载: {plugin_dir}"
                )
                continue
            for entry in sorted(plugin_dir.iterdir()):
                if entry.is_dir() and (entry / "manifest.json").exists():
                    self._load_single_plugin(entry)

        self.plugins_changed.emit()

    @staticmethod
    def _is_builtin_plugin_dir(plugin_dir: Path) -> bool:
        """内置插件目录：frozen 时在 _MEIPASS，源码运行时在项目根。"""
        if getattr(sys, "frozen", False):
            builtin = Path(getattr(sys, "_MEIPASS", ""))
        else:
            builtin = Path(__file__).parent.parent
        try:
            plugin_dir.resolve(strict=False).relative_to(builtin.resolve(strict=False))
            return True
        except (ValueError, OSError):
            return False

    @staticmethod
    def _is_unsafe_plugin_dir(plugin_dir: Path) -> bool:
        """目录被 group/other 可写视为不安全。

        Windows 的 ACL 语义与 POSIX 不同（即使用户目录默认也带继承 ACL），
        不在此判断范围。
        """
        if sys.platform == "win32":
            return False
        try:
            st = plugin_dir.stat()
        except OSError:
            return True
        return bool(st.st_mode & 0o022)

    def _load_single_plugin(self, plugin_path: Path):
        """加载单个插件"""
        manifest_path = plugin_path / "manifest.json"
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read manifest: {manifest_path}: {e}")
            return

        plugin_id = manifest.get("id")
        if not plugin_id:
            logger.warning(f"Missing 'id' in manifest: {manifest_path}")
            return

        # 禁用的插件不执行任何代码。旧实现 load_plugins 不看 is_plugin_enabled，
        # "禁用"只过滤了菜单 —— 用户在设置里关掉插件后，重启前其 on_load() 仍会
        # 执行一次，禁用状态形同虚设（对恶意插件尤其危险）。
        if not is_plugin_enabled(plugin_id):
            logger.info(f"Plugin {plugin_id} is disabled by user, skipping load")
            self._manifests[plugin_id] = manifest
            self._plugin_paths[plugin_id] = plugin_path
            self._plugin_status[plugin_id] = {
                "status": "disabled",
                "message": "已在设置中禁用",
            }
            return

        # 校验 plugin_id 安全性（仅允许字母、数字、下划线、连字符）
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', plugin_id):
            logger.warning(f"不安全的插件 ID: {plugin_id}")
            return

        # 避免重复加载
        if plugin_id in self._plugins:
            logger.debug(f"插件 {plugin_id} 已加载，跳过重复加载")
            return

        self._manifests[plugin_id] = manifest
        self._plugin_paths[plugin_id] = plugin_path

        # 版本兼容性检查
        if not self._check_version_compat(manifest):
            self._plugin_status[plugin_id] = {
                "status": "incompatible",
                "message": f"需要 SharedClipboard >= {manifest.get('min_app_version')}",
            }
            logger.warning(f"Plugin {plugin_id} incompatible: requires app >= {manifest.get('min_app_version')}")
            return

        # 依赖检查
        deps_ok, missing = self._check_dependencies(manifest)
        if not deps_ok:
            self._plugin_status[plugin_id] = {
                "status": "missing_deps",
                "message": f"缺少依赖: {', '.join(missing)}",
                "missing_deps": missing,
            }
            logger.warning(f"Plugin {plugin_id} missing deps: {missing}")
            return

        # 动态导入（防止路径遍历攻击）
        entry_point = manifest.get("entry_point", "plugin.py")
        if os.path.isabs(entry_point):
            logger.warning(f"Suspicious entry_point in {plugin_id}: {entry_point}")
            self._plugin_status[plugin_id] = {
                "status": "error",
                "message": f"不安全的入口路径: {entry_point}",
            }
            return
        module_path = plugin_path / entry_point
        # resolve 后校验最终路径仍在插件目录内，防止 .. 或软链逃逸
        try:
            resolved_module = module_path.resolve(strict=False)
            resolved_plugin = plugin_path.resolve(strict=False)
            resolved_module.relative_to(resolved_plugin)
        except (ValueError, OSError) as e:
            logger.warning(f"Entry point escapes plugin dir in {plugin_id}: {entry_point} ({e})")
            self._plugin_status[plugin_id] = {
                "status": "error",
                "message": f"入口路径越界: {entry_point}",
            }
            return
        if not module_path.exists():
            logger.warning(f"Entry point not found: {module_path}")
            self._plugin_status[plugin_id] = {
                "status": "error",
                "message": f"入口文件不存在: {entry_point}",
            }
            return

        try:
            spec = importlib.util.spec_from_file_location(
                f"plugins.{plugin_id}", str(module_path)
            )
            module = importlib.util.module_from_spec(spec)
            # 插件需要 `from core.xxx`/`from config` 等导入项目根模块。
            # 用 contextmanager 临时将项目根加入 sys.path,加载完立即恢复,
            # 避免污染全局命名空间(不同插件可能引入同名模块)。
            with _project_root_in_syspath():
                spec.loader.exec_module(module)
        except Exception as e:
            logger.exception(f"Failed to import plugin {plugin_id}")
            self._plugin_status[plugin_id] = {
                "status": "error",
                "message": f"导入失败: {str(e)}",
            }
            return

        # 查找 PluginBase 子类并实例化
        plugin_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and issubclass(attr, PluginBase)
                    and attr is not PluginBase):
                plugin_class = attr
                break

        if plugin_class is None:
            logger.warning(f"No PluginBase subclass found in {module_path}")
            self._plugin_status[plugin_id] = {
                "status": "error",
                "message": "未找到 PluginBase 子类",
            }
            return

        try:
            plugin = plugin_class()
            # 注入 logger、config 和 cloud_client（后者按 permissions 包装）
            plugin._logger = self._init_plugin_logger(plugin_id)
            plugin._config = self._load_plugin_config(plugin_id)
            plugin._cloud_client = self._wrap_cloud_client_for(plugin_id)
            plugin.on_load()
            self._plugins[plugin_id] = plugin
            self._plugin_status[plugin_id] = {"status": "loaded", "message": ""}
            # Phase 7: 同步到扩展点注册表（如已注入）。
            if self._extension_points is not None:
                try:
                    self._extension_points.register_context_menu(
                        plugin_id, plugin.get_name(), plugin.get_actions(),
                    )
                except Exception:
                    logger.exception(f"Failed to register context menu for {plugin_id}")
            logger.info(f"Plugin loaded: {plugin_id} v{manifest.get('version', '?')}")
        except Exception as e:
            logger.exception(f"Failed to instantiate plugin {plugin_id}")
            self._plugin_status[plugin_id] = {
                "status": "error",
                "message": f"实例化失败: {str(e)}",
            }

    def unload_all(self):
        """卸载所有插件"""
        for plugin_id, plugin in self._plugins.items():
            try:
                plugin.on_unload()
            except Exception:
                logger.exception(f"Error unloading plugin {plugin_id}")
            # Phase 7: 从扩展点注册表移除。
            if self._extension_points is not None:
                try:
                    self._extension_points.unregister_plugin(plugin_id)
                except Exception:
                    logger.exception(f"Failed to unregister extension points for {plugin_id}")
            # 关闭 logger handler 防止文件句柄泄漏
            plugin_logger = logging.getLogger(f"plugin.{plugin_id}")
            for handler in plugin_logger.handlers[:]:
                handler.close()
                plugin_logger.removeHandler(handler)
        self._plugins.clear()
        self._manifests.clear()
        self._plugin_status.clear()
        self._plugin_paths.clear()

    def reload_plugins(self):
        """重新加载所有插件"""
        self.unload_all()
        self.load_plugins()

    # ========== 云端客户端 ==========

    def set_cloud_client(self, client):
        """设置云端 API 客户端，所有插件共享此实例（但各自走权限代理）。"""
        self._cloud_client = client
        # 同步更新已加载插件的 cloud_client（每个插件拿到自己的权限代理）
        for pid, plugin in self._plugins.items():
            plugin._cloud_client = self._wrap_cloud_client_for(pid)

    def _wrap_cloud_client_for(self, plugin_id: str):
        """根据插件 manifest.permissions 包装 cloud_client。
        未声明 credits / network 的插件调用对应方法时抛 PermissionError。
        """
        if self._cloud_client is None:
            return None
        permissions = self._manifests.get(plugin_id, {}).get("permissions", [])
        return _make_plugin_cloud_client_proxy(self._cloud_client, permissions)

    # ========== 查询 ==========

    def get_loaded_plugins(self) -> List[dict]:
        """返回所有已扫描插件的信息列表"""
        result = []
        for plugin_id, manifest in self._manifests.items():
            status_info = self._plugin_status.get(plugin_id, {})
            info = {
                "id": plugin_id,
                "name": manifest.get("name", plugin_id),
                "version": manifest.get("version", "?"),
                "description": manifest.get("description", ""),
                "author": manifest.get("author", ""),
                "enabled": is_plugin_enabled(plugin_id),
                "status": status_info.get("status", "unknown"),
                "status_message": status_info.get("message", ""),
                "permissions": manifest.get("permissions", []),
                "missing_deps": status_info.get("missing_deps", []),
                "has_config": bool(manifest.get("config_schema")),
                "config_schema": manifest.get("config_schema", {}),
            }
            result.append(info)
        return result

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        return is_plugin_enabled(plugin_id)

    def get_plugin_name(self, plugin_id: str) -> str:
        """返回插件显示名称"""
        manifest = self._manifests.get(plugin_id)
        if manifest:
            return manifest.get("name", plugin_id)
        return plugin_id

    def get_plugin_permissions(self, plugin_id: str) -> list:
        """返回插件 manifest 声明的 permissions 列表（无声明则空 list）。"""
        manifest = self._manifests.get(plugin_id)
        if not manifest:
            return []
        perms = manifest.get("permissions") or []
        return list(perms)

    def get_plugin_actions_grouped(self, item: ClipboardItem) -> List[dict]:
        """返回按插件分组的动作列表（用于构建菜单）

        返回: [{plugin_id, plugin_name, actions: [PluginAction, ...]}, ...]
        """
        groups = {}
        for plugin_id, plugin in self._plugins.items():
            if not is_plugin_enabled(plugin_id):
                continue
            try:
                matching_actions = [
                    a for a in plugin.get_actions()
                    if item.content_type in a.supported_types
                ]
                if matching_actions:
                    groups[plugin_id] = {
                        "plugin_id": plugin_id,
                        "plugin_name": plugin.get_name(),
                        "actions": matching_actions,
                    }
            except Exception:
                logger.exception(f"Error getting actions from {plugin_id}")
        return list(groups.values())

    # ========== 执行 ==========

    def run_action(self, plugin_id: str, action_id: str, item: ClipboardItem) -> bool:
        """在工作线程中执行插件动作。返回 True 表示已启动，False 表示被拒绝。"""
        if self._active_worker is not None:
            self.action_error.emit(t("plugin_busy"))
            return False

        plugin = self._plugins.get(plugin_id)
        if not plugin:
            self.action_error.emit(t("plugin_not_loaded", id=plugin_id))
            return False

        # 创建 worker
        worker = PluginWorker(plugin, action_id, item)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(lambda result: self._on_worker_finished(result, item))
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._cleanup_worker)
        worker.error.connect(self._cleanup_worker)

        self._active_worker = worker

        # 启动超时计时器
        timeout_s = self._manifests.get(plugin_id, {}).get("timeout", 30)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(timeout_s * 1000)

        worker.start()
        return True

    def cancel_action(self):
        """取消当前执行的插件动作"""
        if self._active_worker:
            self._active_worker.cancel()
            # 不立即清理 _active_worker，等线程的 finished/error 信号自然触发 _cleanup_worker
            if self._timeout_timer:
                self._timeout_timer.stop()
                self._timeout_timer = None

    def _on_worker_progress(self, percent: int, message: str):
        self.action_progress.emit(percent, message)

    def _on_worker_finished(self, result: PluginResult, original_item: ClipboardItem):
        self.action_finished.emit(result, original_item)

    def _on_worker_error(self, message: str):
        self.action_error.emit(message)

    def _on_timeout(self):
        if self._active_worker and not self._active_worker.is_cancelled:
            self._active_worker.cancel()
            self.action_error.emit(t("plugin_timeout"))
            # worker.cancel() 后 run() 会发射 finished 信号触发 _cleanup_worker

    def _cleanup_worker(self):
        if self._timeout_timer:
            self._timeout_timer.stop()
            self._timeout_timer = None
        if not self._active_worker:
            return
        worker = self._active_worker
        self._active_worker = None
        # Why: finished/error 都 connect 到 _cleanup_worker，第一个触发时另一个
        # 可能已在队列中；一次性断开全部信号-槽连接，消除重入竞态。
        try:
            QObject.disconnect(worker, None, None, None)
        except (RuntimeError, TypeError):
            pass

        if worker.isFinished():
            worker.deleteLater()
            return

        # 5s 兜底：线程未结束则强制 terminate，避免泄漏。
        cleanup_timer = QTimer(self)
        cleanup_timer.setSingleShot(True)

        def _on_finished():
            if cleanup_timer.isActive():
                cleanup_timer.stop()
            worker.deleteLater()
            # QTimer 以 self(plugin_manager) 为父不会被 GC，显式回收避免长期累积
            cleanup_timer.deleteLater()

        def _force_cleanup():
            if not worker.isFinished():
                logger.warning("plugin worker did not finish within 5s, terminating")
                worker.terminate()
                worker.wait(1000)
            worker.deleteLater()
            cleanup_timer.deleteLater()

        cleanup_timer.timeout.connect(_force_cleanup)
        # Why: SingleShotConnection 让 _on_finished 只响应一次就自动断开；
        # PySide6 6.7+ 有，6.6.x（requirements 下限）需手动 disconnect 降级。
        single_shot = getattr(Qt.ConnectionType, "SingleShotConnection", None)
        if single_shot is not None:
            worker.finished.connect(_on_finished, single_shot)
        else:
            def _once(*_args, _slot=_on_finished):
                try:
                    worker.finished.disconnect(_once)
                except (RuntimeError, TypeError):
                    pass
                _slot()
            worker.finished.connect(_once)

        if worker.isFinished():
            # disconnect 和 connect 之间线程已结束，手动触发清理
            _on_finished()
        else:
            cleanup_timer.start(5000)

    # ========== 配置 ==========

    def get_plugin_config(self, plugin_id: str) -> dict:
        return self._load_plugin_config(plugin_id)

    def save_plugin_config(self, plugin_id: str, config: dict):
        """保存插件配置并通知插件"""
        self._save_plugin_config(plugin_id, config)
        plugin = self._plugins.get(plugin_id)
        if plugin:
            plugin._config = config
            try:
                plugin.on_config_changed(config)
            except Exception:
                logger.exception(f"Error in on_config_changed for {plugin_id}")

    def get_config_schema(self, plugin_id: str) -> dict:
        return self._manifests.get(plugin_id, {}).get("config_schema", {})

    # ========== 内部方法 ==========

    def _get_plugin_dirs(self) -> List[Path]:
        """获取插件搜索目录列表"""
        dirs = []
        # 内置插件：frozen 时从 _MEIPASS 目录找，源码时从项目根找
        if getattr(sys, 'frozen', False):
            # 用 getattr 兜底：极端情况下 frozen 但 _MEIPASS 缺失时退化到空路径
            app_root = Path(getattr(sys, '_MEIPASS', ''))
        else:
            app_root = Path(__file__).parent.parent
        builtin_dir = app_root / "plugins"
        dirs.append(builtin_dir)
        # App Store / 沙盒构建禁止加载任何外部插件（App Review 2.5.2）。
        # 只信任打包进 .app 的内置插件。
        if IS_APPSTORE_BUILD:
            return dirs
        # 用户安装插件
        user_dir = get_user_plugins_dir()
        if user_dir != builtin_dir:
            dirs.append(user_dir)
        # exe 同级目录的 plugins（方便不重新编译就添加插件）
        if getattr(sys, 'frozen', False):
            exe_plugins = Path(sys.executable).parent / "plugins"
            if exe_plugins not in dirs:
                dirs.append(exe_plugins)
        return dirs

    def _check_version_compat(self, manifest: dict) -> bool:
        min_ver = manifest.get("min_app_version")
        if not min_ver:
            return True
        try:
            min_parts = tuple(int(x) for x in min_ver.split("."))
            app_parts = tuple(int(x) for x in APP_VERSION.split("."))
            return app_parts >= min_parts
        except (ValueError, AttributeError):
            return True

    def _check_dependencies(self, manifest: dict) -> Tuple[bool, List[str]]:
        missing = []
        for dep in manifest.get("dependencies", {}).get("pip", []):
            pkg_name = dep.split(">=")[0].split("==")[0].split("<")[0].split("[")[0].strip()
            # 常见包名映射（pip 包名和 import 名不一致的情况）
            import_map = {
                "pillow": "PIL",
                "pyside6": "PySide6",
                "pymysql": "pymysql",
                "openai": "openai",
            }
            import_name = import_map.get(pkg_name.lower(), pkg_name)
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(dep)
        return len(missing) == 0, missing

    def _init_plugin_logger(self, plugin_id: str) -> logging.Logger:
        plugin_logger = logging.getLogger(f"plugin.{plugin_id}")
        # 避免重复添加 handler
        if not plugin_logger.handlers:
            log_dir = get_config_dir() / "logs"
            log_dir.mkdir(exist_ok=True)
            handler = RotatingFileHandler(
                str(log_dir / f"plugin_{plugin_id}.log"),
                maxBytes=1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"
            ))
            plugin_logger.addHandler(handler)
        plugin_logger.setLevel(logging.DEBUG)
        return plugin_logger

    def _load_plugin_config(self, plugin_id: str) -> dict:
        config_path = get_config_dir() / "plugins" / plugin_id / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load config for {plugin_id}: {e}")
        return {}

    def _save_plugin_config(self, plugin_id: str, config: dict):
        try:
            config_dir = get_config_dir() / "plugins" / plugin_id
            config_dir.mkdir(parents=True, exist_ok=True)
            with open(config_dir / "config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except (IOError, OSError) as e:
            logger.error(f"Failed to save config for {plugin_id}: {e}")

    # ========== 插件商店 ==========

    def uninstall_plugin(self, plugin_id: str) -> bool:
        """卸载插件，删除其目录。只允许删除已知插件目录内的内容。"""
        import shutil
        path = self._plugin_paths.get(plugin_id)
        if not path or not path.exists():
            return False
        resolved = path.resolve()
        for known_dir in self._get_plugin_dirs():
            try:
                resolved.relative_to(known_dir.resolve())
                shutil.rmtree(path)
                self.plugins_changed.emit()
                return True
            except ValueError:
                continue
        return False
