"""MainWindow — 壳 + UI 构造 + 信号路由 + closeEvent 清理。

业务逻辑下沉到 ui/controllers/ 下的四个控制器:
- ClipboardListController:列表加载/分页/搜索/侧栏/视图
- ItemActionController:单项操作 (复制/删除/收藏/保存/链接/分享/标签)
- PluginActionController:右键菜单 + 插件 dispatch
- CloudLifecycleController:登录/登出 引发的 stack 切换 + 云同步启停
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List

from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QButtonGroup,
)

from core.models import ClipboardItem
from config import (
    IS_MACOS,
    settings,
    get_cloud_access_token,
)
from i18n import t
from .edge_window import EdgeHiddenWindow
from .styles import MAIN_STYLE

logger = logging.getLogger(__name__)


def _restore_cloud_api_from_config():
    """返回全局 CloudAPIClient（仅在已登录时返回非 None，用于向后兼容旧调用点）。"""
    if not get_cloud_access_token():
        return None
    try:
        from core.cloud_api import get_cloud_client
        return get_cloud_client()
    except Exception:
        logger.warning("恢复 CloudAPIClient 失败", exc_info=True)
        return None


class MainWindow(EdgeHiddenWindow):
    quit_requested = Signal()  # 退出信号

    def __init__(
        self,
        repository=None,
        clipboard_monitor=None,
        sync_service=None,
        plugin_manager=None,
        cloud_api=None,
        cloud_sync_service=None,
        file_sync_service=None,
        file_repository=None,
        entitlement_service=None,
        space_service=None,
        tag_service=None,
        share_service=None,
        parent=None,
        ctx=None,
    ):
        # 兼容两种调用方式:
        # 1) 旧:MainWindow(repository=..., clipboard_monitor=..., ...)
        # 2) 新:MainWindow(ctx=ctx) —— ctx 优先
        super().__init__(parent)
        self.ctx = ctx
        _services = ("repository", "clipboard_monitor", "sync_service",
                     "plugin_manager", "cloud_api", "cloud_sync_service",
                     "file_sync_service", "file_repository", "entitlement_service",
                     "space_service", "tag_service", "share_service")
        _locals = locals()
        for _name in _services:
            setattr(self, _name,
                    getattr(ctx, _name, None) if ctx is not None else _locals[_name])

        # 如果没有传入 cloud_api,但有已保存的 token,则创建客户端
        if not self.cloud_api:
            self.cloud_api = _restore_cloud_api_from_config()

        # 将 cloud_api 注入到 PluginManager,使插件可以复用登录态
        if self.plugin_manager and self.cloud_api:
            self.plugin_manager.set_cloud_client(self.cloud_api)

        # 共享线程池(controllers 通过 self._parent 访问)
        self._copy_executor = ThreadPoolExecutor(max_workers=1)
        self._cloud_executor = ThreadPoolExecutor(max_workers=1)
        # 云同步连接标记(CloudLifecycleController 管理)
        self._cloud_sync_item_added_connected = False
        self._cloud_sync_ui_connected = False

        # 首启引导槽位
        self._onboarding_dialog = None

        # 先创建控制器再走 UI,_setup_ui 里的 connect 可以直接绑到 controller 方法
        from .controllers.clipboard_list_controller import ClipboardListController
        from .controllers.item_action_controller import ItemActionController
        from .controllers.plugin_action_controller import PluginActionController
        from .controllers.cloud_lifecycle_controller import CloudLifecycleController

        self.list_controller = ClipboardListController(self, self.ctx)
        self.item_controller = ItemActionController(self, self.ctx)
        self.plugin_controller = PluginActionController(self, self.ctx)
        self.cloud_controller = CloudLifecycleController(self, self.ctx)

        self.setStyleSheet(MAIN_STYLE)
        self._setup_ui()
        self._connect_signals()
        self.list_controller.load_items()

        # 首次启动 3 步引导(非阻塞,跳过即关闭)
        if not getattr(settings, "onboarding_done", False):
            QTimer.singleShot(600, self._maybe_show_onboarding)

    # ========== UI 构造 ==========

    def _setup_ui(self):
        # 外层 QHBoxLayout:左侧 Sidebar,右侧主内容
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Sidebar ---
        try:
            from .sidebar import Sidebar
            self.sidebar = Sidebar(
                space_service=self.space_service,
                tag_service=self.tag_service,
                entitlement_service=self.entitlement_service,
            )
            self.sidebar.space_changed.connect(self.list_controller.on_sidebar_space_changed)
            self.sidebar.tag_filter_changed.connect(self.list_controller.on_sidebar_tag_changed)
            self.sidebar.create_space_requested.connect(self.list_controller.on_sidebar_create_space)
            self.sidebar.manage_team_requested.connect(self.list_controller.on_sidebar_manage_team)
            self.sidebar.upgrade_requested.connect(self.list_controller.on_sidebar_upgrade)
            root.addWidget(self.sidebar)
        except Exception as exc:
            logger.warning(f"Sidebar 初始化失败,将继续以无侧栏模式运行: {exc}", exc_info=True)
            self.sidebar = None

        # --- 右侧主内容 ---
        main_container = QWidget()
        layout = QVBoxLayout(main_container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        root.addWidget(main_container, 1)

        # 顶部:搜索和设置
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("search_placeholder"))
        self.search_input.textChanged.connect(self.list_controller.on_search_changed)
        header_layout.addWidget(self.search_input, 1)

        def _mk(text, tip, size, slot):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setFixedSize(size, size)
            btn.clicked.connect(slot)
            header_layout.addWidget(btn)
            return btn

        self.search_help_btn = _mk("ⓘ",
            "支持结构化搜索：\n"
            "  from:chrome  — 按来源 app 过滤\n"
            "  tag:work    — 按标签过滤\n"
            "  after:2026-04-01  before:2026-05-01\n"
            "  size:>1MB\n"
            "  is:starred  is:text  is:image\n"
            "  \"引号短语\"  /正则/\n"
            "  -from:foo   — 否定",
            24, self.list_controller.show_search_help)
        self.star_filter_btn = _mk("☆", t("show_starred_only"), 28, self.list_controller.toggle_starred_filter)
        self.pin_btn = _mk("⇩", t("pin_window"), 28, self._toggle_pin)
        self.settings_btn = _mk("⚙", t("settings"), 28, self._show_settings)
        self.minimize_btn = _mk("—", t("minimize"), 28, self._minimize_window)
        if IS_MACOS:
            self.minimize_btn.setVisible(False)
        self.quit_btn = _mk("✕", t("quit_app"), 28, self._request_quit)

        layout.addLayout(header_layout)

        # Tab 切换:剪贴板 / 我的文件
        tab_row = QHBoxLayout()
        tab_row.setSpacing(12)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        for idx, (label, attr, checked) in enumerate([
            ("剪贴板", "history_tab_btn", True),
            ("我的文件", "files_tab_btn", False),
        ]):
            btn = QPushButton(label)
            btn.setObjectName("tabBtn")
            btn.setCheckable(True)
            btn.setChecked(checked)
            setattr(self, attr, btn)
            self._tab_group.addButton(btn, idx)
            tab_row.addWidget(btn)
        self._tab_group.idClicked.connect(self.list_controller.on_tab_changed)
        tab_row.addStretch()
        layout.addLayout(tab_row)

        # 堆叠容器:页 0 = 剪贴板列表,页 1 = 文件管理
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        # --- 剪贴板页 / 文件页(具体控件构建在 helper 里完成) ---
        from .main_window_helpers import build_clipboard_page, attach_file_page
        self._stack.addWidget(build_clipboard_page(self))
        attach_file_page(self)

        # 复制反馈定时器(复用同一个,避免快速复制时提前隐藏)
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self.copy_feedback_label.hide)

    # ========== 信号路由 ==========

    def _connect_signals(self):
        # 剪贴板监控:新条目到 list_controller
        self.clipboard_monitor.item_added.connect(self.list_controller.on_item_added)

        # 同步服务:其它设备来的新条目
        self.sync_service.new_items_available.connect(self.list_controller.on_new_items)

        # list_controller 单项点击/操作 → item_controller
        self.list_controller.item_clicked.connect(self.item_controller.on_item_clicked)
        self.list_controller.item_delete_requested.connect(self.item_controller.on_item_delete)
        self.list_controller.item_star_requested.connect(self.item_controller.on_item_star)
        self.list_controller.item_save_requested.connect(self.item_controller.on_item_save)
        self.list_controller.cloud_delete_requested.connect(self.item_controller.on_cloud_delete)
        self.list_controller.image_url_copy_requested.connect(self.item_controller.on_image_url_copy)

        # 插件信号
        if self.plugin_manager:
            self.plugin_manager.action_progress.connect(self.plugin_controller.on_plugin_progress)
            self.plugin_manager.action_finished.connect(self.plugin_controller.on_plugin_finished)
            self.plugin_manager.action_error.connect(self.plugin_controller.on_plugin_error)

    # ========== 向后兼容 shims:main.py 等外部调用点继续可用 ==========

    def _on_new_items(self, items: List[ClipboardItem]):
        """向后兼容:main.py 把 cloud_sync_service.new_items_available 直连此处。"""
        self.list_controller.on_new_items(items)

    # ========== 退出 / 最小化 / Pin / 设置 ==========

    def _toggle_pin(self):
        is_pinned = self.toggle_pin()
        if not is_pinned and self._is_floating:
            self._snap_to_nearest_edge()
        self.pin_btn.setText("⇧" if is_pinned else "⇩")
        self.pin_btn.setToolTip(t("unpin_window") if is_pinned else t("pin_window"))

    def _minimize_window(self):
        """最小化窗口(完全隐藏)。"""
        self.hide_window()

    def _request_quit(self):
        """请求退出应用。"""
        self.quit_requested.emit()

    def show_window(self):
        super().show_window()
        try:
            from core import analytics
            analytics.mark_first(analytics.FIRST_WAKE)
        except Exception:
            pass
        if self._onboarding_dialog is not None:
            try:
                self._onboarding_dialog.advance_on_wake()
                self._onboarding_dialog.raise_()
            except Exception:
                pass

    def _show_settings(self, initial_tab: str = ""):
        from .main_window_helpers import show_settings_dialog
        show_settings_dialog(self, initial_tab=initial_tab)

    def _do_migration(self):
        """在工作线程中执行数据库迁移,避免阻塞 UI。"""
        from .main_window_helpers import run_database_migration
        run_database_migration(self)

    # ========== 首启引导 ==========

    def _maybe_show_onboarding(self) -> None:
        """惰性创建首启引导,避免阻塞启动。"""
        if self._onboarding_dialog is not None:
            return
        if getattr(settings, "onboarding_done", False):
            return
        try:
            from .onboarding_dialog import OnboardingDialog
            self._onboarding_dialog = OnboardingDialog(self)
            self._onboarding_dialog.finished_or_skipped.connect(self._on_onboarding_done)
            self._onboarding_dialog.show()
        except Exception as exc:
            logger.debug(f"显示首启引导失败: {exc}")
            self._onboarding_dialog = None

    def _on_onboarding_done(self) -> None:
        self._onboarding_dialog = None

    # ========== 关闭 ==========

    def closeEvent(self, event):
        """系统关闭请求统一走退出按钮逻辑,同时清理 controller 引用避免 Qt 循环。"""
        if IS_MACOS:
            self._request_quit()
            event.accept()
            return
        for ctrl in (
            getattr(self, "list_controller", None),
            getattr(self, "item_controller", None),
            getattr(self, "plugin_controller", None),
            getattr(self, "cloud_controller", None),
        ):
            if ctrl is not None:
                try:
                    ctrl.setParent(None)
                    ctrl.deleteLater()
                except Exception:
                    pass
        super().closeEvent(event)
