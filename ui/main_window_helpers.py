"""MainWindow 用到的纯展示/纯工具辅助函数 —— 抽离让 main_window.py 保持壳级别。

- build_file_page_placeholder:文件页未登录占位
- run_database_migration:数据库迁移 worker(原 MainWindow._do_migration)
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QUrl, QThread, Signal as QSignal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)

from config import (
    PRICING_URL,
    settings,
    update_settings,
    flush_settings,
    get_effective_hotkey,
    get_effective_screenshot_hotkey,
    get_effective_database_path,
    get_mysql_config,
    apply_profile,
)
from i18n import t, set_language
from ui.thread_utils import track_thread
from .icons import icon
from .styles import theme_style

logger = logging.getLogger(__name__)


def build_clipboard_page(window) -> QWidget:
    """构建"剪贴板"页 (视图切换 + 列表 + 时间线懒加载 + 复制反馈 + 分页)。

    所有创建出来的子 widget/控件按原约定挂到 window 上,信号绑到 list_controller /
    plugin_controller。
    """
    page = QWidget()
    clip_layout = QVBoxLayout(page)
    clip_layout.setContentsMargins(0, 0, 0, 0)
    clip_layout.setSpacing(10)

    # 视图切换(列表 / 时间线)
    view_row = QHBoxLayout()
    view_row.setSpacing(4)
    section_label = QLabel(t("recent_records"))
    section_label.setObjectName("sectionCaption")
    view_row.addWidget(section_label)
    view_row.addStretch()
    window.view_list_btn = QToolButton()
    window.view_list_btn.setIcon(icon("list"))
    window.view_list_btn.setToolTip(t("list_view"))
    window.view_list_btn.setCheckable(True)
    window.view_list_btn.setChecked(True)
    window.view_timeline_btn = QToolButton()
    window.view_timeline_btn.setIcon(icon("clock"))
    window.view_timeline_btn.setToolTip(t("timeline_view"))
    window.view_timeline_btn.setCheckable(True)
    for btn in (window.view_list_btn, window.view_timeline_btn):
        btn.setObjectName("viewButton")
        btn.setFixedSize(30, 28)
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAccessibleName(btn.toolTip())
    window._view_group = QButtonGroup(window)
    window._view_group.setExclusive(True)
    window._view_group.addButton(window.view_list_btn, 0)
    window._view_group.addButton(window.view_timeline_btn, 1)
    window._view_group.idClicked.connect(window.list_controller.on_view_changed)
    view_row.addWidget(window.view_list_btn)
    view_row.addWidget(window.view_timeline_btn)
    clip_layout.addLayout(view_row)

    # 列表 + 时间线视图的堆叠
    window._view_stack = QStackedWidget()
    clip_layout.addWidget(window._view_stack, 1)

    window.list_widget = QListWidget()
    window.list_widget.setObjectName("historyList")
    window.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    window.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    window.list_widget.setSpacing(1)
    window.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
    window.list_widget.customContextMenuRequested.connect(window.plugin_controller.show_context_menu)
    window._view_stack.addWidget(window.list_widget)

    # A non-interactive overlay stays centered in the real list viewport.
    # It never creates a selectable fake record or changes the view routing.
    window.empty_state = QWidget(window.list_widget.viewport())
    window.empty_state.setAttribute(Qt.WA_TransparentForMouseEvents)
    empty_layout = QVBoxLayout(window.empty_state)
    empty_layout.setSpacing(12)
    empty_layout.addStretch()
    empty_icon = QLabel()
    empty_icon.setObjectName("emptyIcon")
    empty_icon.setFixedSize(64, 64)
    empty_icon.setAlignment(Qt.AlignCenter)
    empty_icon.setPixmap(icon("clipboard", "accent").pixmap(30, 30))
    empty_layout.addWidget(empty_icon, 0, Qt.AlignHCenter)
    window.empty_title = QLabel(t("empty_history_title"))
    window.empty_title.setObjectName("emptyTitle")
    window.empty_title.setAlignment(Qt.AlignCenter)
    window.empty_title.setWordWrap(True)
    empty_layout.addWidget(window.empty_title)
    window.empty_description = QLabel(t("empty_history_description"))
    window.empty_description.setObjectName("emptyDescription")
    window.empty_description.setAlignment(Qt.AlignCenter)
    window.empty_description.setWordWrap(True)
    empty_layout.addWidget(window.empty_description)
    empty_layout.addStretch()
    viewport_layout = QVBoxLayout(window.list_widget.viewport())
    viewport_layout.setContentsMargins(16, 0, 16, 0)
    viewport_layout.addWidget(window.empty_state)
    window.empty_state.hide()

    # 时间线视图懒加载
    window.timeline_view = None
    try:
        from .timeline_view import TimelineView
        window.timeline_view = TimelineView()
        window.timeline_view.item_clicked.connect(window.list_controller.on_timeline_item_clicked)
        window._view_stack.addWidget(window.timeline_view)
    except Exception as exc:
        logger.debug(f"TimelineView 初始化失败: {exc}")

    # 复制反馈标签
    window.copy_feedback_label = QLabel()
    window.copy_feedback_label.setAlignment(Qt.AlignCenter)
    window.copy_feedback_label.hide()
    clip_layout.addWidget(window.copy_feedback_label)

    # 底部:分页
    pagination_layout = QHBoxLayout()
    pagination_layout.setSpacing(8)

    hint = QLabel(t("click_to_copy"))
    hint.setObjectName("sidebarCaption")
    pagination_layout.addWidget(hint, 1)

    window.prev_btn = QPushButton()
    window.prev_btn.setObjectName("pageBtn")
    window.prev_btn.setIcon(icon("chevron-left"))
    window.prev_btn.setToolTip(t("prev_page"))
    window.prev_btn.setAccessibleName(t("prev_page"))
    window.prev_btn.clicked.connect(window.list_controller.prev_page)
    pagination_layout.addWidget(window.prev_btn)

    window.page_label = QLabel("1 / 1")
    window.page_label.setObjectName("pageLabel")
    window.page_label.setAlignment(Qt.AlignCenter)
    pagination_layout.addWidget(window.page_label)

    window.next_btn = QPushButton()
    window.next_btn.setObjectName("pageBtn")
    window.next_btn.setIcon(icon("chevron-right"))
    window.next_btn.setToolTip(t("next_page"))
    window.next_btn.setAccessibleName(t("next_page"))
    window.next_btn.clicked.connect(window.list_controller.next_page)
    pagination_layout.addWidget(window.next_btn)

    clip_layout.addLayout(pagination_layout)
    return page


def attach_file_page(window):
    """把"我的文件"页(真实 FileListWidget 或升级占位)挂到 window._stack。"""
    window.file_list_widget = None
    window._file_page_placeholder = None
    if window.file_sync_service and window.file_repository and window.entitlement_service:
        try:
            from .file_list_widget import FileListWidget
            window.file_list_widget = FileListWidget(
                window.file_repository,
                window.file_sync_service,
                window.entitlement_service,
                window.cloud_api,
            )
            window._stack.addWidget(window.file_list_widget)
        except Exception as e:
            logger.warning(f"初始化文件页失败: {e}", exc_info=True)
    if window.file_list_widget is None:
        placeholder = build_file_page_placeholder()
        window._stack.addWidget(placeholder)
        window._file_page_placeholder = placeholder


def build_file_page_placeholder() -> QWidget:
    """未登录 / 依赖缺失时的「我的文件」升级占位。"""
    placeholder = QWidget()
    pl = QVBoxLayout(placeholder)
    pl.setContentsMargins(24, 24, 24, 24)
    pl.setSpacing(14)
    pl.addStretch()

    illustration = QLabel()
    illustration.setObjectName("emptyIcon")
    illustration.setFixedSize(64, 64)
    illustration.setAlignment(Qt.AlignCenter)
    illustration.setPixmap(icon("file", "accent").pixmap(30, 30))
    pl.addWidget(illustration, 0, Qt.AlignHCenter)

    title = QLabel(t("my_files"))
    title.setObjectName("emptyTitle")
    title.setAlignment(Qt.AlignCenter)
    pl.addWidget(title)

    tip = QLabel("登录云端账户并升级到付费套餐后,在此管理常用文件。")
    tip.setWordWrap(True)
    tip.setAlignment(Qt.AlignCenter)
    tip.setObjectName("emptyDescription")
    pl.addWidget(tip)

    diff = QLabel(
        "<b>剪贴板同步 · 免费</b><br>自动备份文字和图片记录，"
        "图片会压缩为 JPG、长边 ≤ 2K 节省流量。<br><br>"
        "<b>文件云同步 · 付费增强</b><br>保留文档、压缩包、音视频等原始文件，"
        "最大单文件 1 GB，跨设备按需下载。"
    )
    diff.setWordWrap(True)
    diff.setTextFormat(Qt.RichText)
    diff.setAlignment(Qt.AlignLeft)
    diff.setStyleSheet(theme_style(
        "color:$secondary;background:$surface;border:1px solid $border;"
        "border-radius:10px;padding:16px;"
    ))
    pl.addWidget(diff)

    upgrade_btn = QPushButton("升级套餐")
    upgrade_btn.setObjectName("okButton")
    upgrade_btn.setMinimumHeight(34)
    upgrade_btn.setCursor(Qt.PointingHandCursor)
    upgrade_btn.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl(PRICING_URL))
    )
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_row.addWidget(upgrade_btn)
    btn_row.addStretch()
    pl.addLayout(btn_row)

    pl.addStretch()
    return placeholder


def run_database_migration(window):
    """在 QThread 中跑数据库迁移,完成/失败后弹提示。

    window:MainWindow 实例(用于 self.repository / parent 弹窗)。
    """
    from core.migration import DatabaseMigrator
    from core.db_factory import create_database_manager
    from core.repository import ClipboardRepository
    from .styles import MAIN_STYLE

    try:
        target_db = create_database_manager()
        target_repo = ClipboardRepository(target_db)
    except Exception as e:
        QMessageBox.critical(
            window, t("error"), t("migration_failed", error=str(e))
        )
        return

    # 重入保护：旧实现把 worker 挂在 window._migration_worker 单一槽位，
    # 重复触发迁移时新 worker 覆盖旧 worker → 旧线程失去唯一 Python 引用，
    # 仍在 isRunning() 时被 GC 析构 → Qt qFatal abort 整个进程。
    running = getattr(window, "_migration_worker", None)
    if running is not None:
        try:
            still_running = running.isRunning()
        except RuntimeError:
            # finished 回调里 deleteLater 已销毁 C++ 对象，残留的 Python 包装
            # 调 isRunning() 会抛 RuntimeError —— 视为已结束
            still_running = False
        if still_running:
            QMessageBox.information(window, t("migrate_data"), t("migration_in_progress"))
            return

    class MigrationWorker(QThread):
        progress = QSignal(int, int)
        finished_ok = QSignal(int)
        finished_err = QSignal(str)

        def __init__(self, migrator):
            super().__init__()
            self._migrator = migrator

        def run(self):
            try:
                count = self._migrator.migrate(
                    progress_callback=lambda cur, tot: self.progress.emit(cur, tot)
                )
                self.finished_ok.emit(count)
            except Exception as e:
                self.finished_err.emit(str(e))

    migrator = DatabaseMigrator(window.repository, target_repo)

    progress_dlg = QProgressDialog(t("migrating"), None, 0, 100, window)
    progress_dlg.setWindowTitle(t("migrate_data"))
    progress_dlg.setMinimumDuration(0)
    progress_dlg.setStyleSheet(MAIN_STYLE)

    worker = MigrationWorker(migrator)

    def on_progress(current, total):
        if total > 0:
            progress_dlg.setValue(int(current * 100 / total))

    def on_success(count):
        progress_dlg.close()
        QMessageBox.information(
            window, t("success"), t("migration_complete", count=count)
        )

    def on_error(err):
        progress_dlg.close()
        QMessageBox.critical(
            window, t("error"), t("migration_failed", error=err)
        )

    worker.progress.connect(on_progress)
    worker.finished_ok.connect(on_success)
    worker.finished_err.connect(on_error)

    def _clear_ref():
        # Why：槽位留着已 deleteLater 的死包装，下次进来 isRunning() 会抛
        # RuntimeError；结束时清掉，重入守卫走 None 分支即可。
        window._migration_worker = None

    worker.finished_ok.connect(_clear_ref)
    worker.finished_err.connect(_clear_ref)
    # 登记强引用直到 finished（见 ui/thread_utils 的说明），finished 后自动
    # discard + deleteLater，不再依赖 window 上的单个槽位。
    track_thread(worker)
    window._migration_worker = worker
    worker.start()


def show_settings_dialog(window, initial_tab: str = ""):
    """打开设置对话框,并把对话框结果应用回 window/config。"""
    from .settings_dialog import SettingsDialog

    # Why: 这里必须把 ctx 也透传过去。SettingsDialog 在 cloud_api 等显式参数为 None 时
    # 会从 ctx 上兜底拿；TeamTab 也会从 ctx 拿 cloud_api。早期版本只传 cloud_api 不传 ctx,
    # 一旦 window.cloud_api 暂时是 None(还没登录或被外部清掉), 团队 tab 就永久卡在
    # "未登录或云端服务不可用"。
    dialog = SettingsDialog(
        window,
        plugin_manager=window.plugin_manager,
        cloud_api=window.cloud_api,
        space_service=window.space_service,
        entitlement_service=window.entitlement_service,
        initial_tab=initial_tab,
        ctx=getattr(window, "ctx", None),
    )
    result = dialog.exec()
    # 无论确认还是取消,都同步登录状态(用户可能在对话框中登录了云端)
    dialog_cloud_api = dialog.get_cloud_api()
    if dialog_cloud_api and dialog_cloud_api.is_authenticated:
        window.cloud_api = dialog_cloud_api
        if window.plugin_manager:
            window.plugin_manager.set_cloud_client(window.cloud_api)
        window.cloud_controller.bootstrap_cloud_sync_after_login()
        window.cloud_controller.bootstrap_files_stack_after_login()
    elif dialog_cloud_api and not dialog_cloud_api.is_authenticated:
        window.cloud_controller.teardown_cloud_sync_after_logout()
        window.cloud_api = None
        if window.plugin_manager:
            window.plugin_manager.set_cloud_client(None)

    if result != QDialog.Accepted:
        return

    dlg_settings = dialog.get_settings()
    need_restart = False
    current_snapshot = settings()

    # 汇总改动到 batch,一次 update_settings 落盘
    batch: dict = {}

    new_language = dlg_settings["language"]
    if new_language != current_snapshot.language:
        batch["language"] = new_language
        set_language(new_language)
        # 托盘菜单的 QAction 文本在启动时已固化，切语言后必须重建才能生效
        tray_rebuild = getattr(window, "tray_rebuild_callback", None)
        if callable(tray_rebuild):
            try:
                tray_rebuild()
            except Exception as exc:
                logger.warning(f"重建托盘菜单失败: {exc}")
        need_restart = True

    new_edge = dlg_settings["dock_edge"]
    if new_edge != current_snapshot.dock_edge:
        window.set_dock_edge(new_edge)

    new_hotkey = dlg_settings["hotkey"]
    if new_hotkey != get_effective_hotkey():
        batch["hotkey"] = new_hotkey
        need_restart = True

    # 截图热键同样只在注册时读取，改了需要重启才生效
    new_shot_hotkey = dlg_settings.get("screenshot_hotkey", "")
    if new_shot_hotkey != get_effective_screenshot_hotkey():
        batch["screenshot_hotkey"] = new_shot_hotkey
        need_restart = True

    new_poll_interval = dlg_settings["poll_interval_ms"]
    poll_changed = new_poll_interval != current_snapshot.poll_interval_ms

    for key in ("save_text", "save_images", "max_text_length",
                "max_image_size_kb", "max_items", "retention_days",
                "poll_interval_ms"):
        batch[key] = dlg_settings[key]

    if batch:
        update_settings(**batch)

    if poll_changed:
        window.clipboard_monitor.update_poll_interval(new_poll_interval)

    # Profile / 数据库变更检测
    new_profile = dlg_settings.get("active_profile", "")
    new_db_type = dlg_settings["db_type"]
    db_changed = False

    if new_profile != current_snapshot.active_profile:
        db_changed = True
    elif new_db_type != current_snapshot.db_type:
        db_changed = True
    elif new_db_type == "sqlite":
        new_path = dlg_settings["database_path"] or get_effective_database_path()
        if new_path != get_effective_database_path():
            db_changed = True
    elif new_db_type == "mysql":
        mysql_config = get_mysql_config()
        pw_changed = bool(dlg_settings["mysql_password"]) and dlg_settings["mysql_password"] != mysql_config["password"]
        if (dlg_settings["mysql_host"] != mysql_config["host"] or
            dlg_settings["mysql_port"] != mysql_config["port"] or
            dlg_settings["mysql_user"] != mysql_config["user"] or
            pw_changed or
            dlg_settings["mysql_database"] != mysql_config["database"]):
            db_changed = True

    if db_changed:
        migrate = QMessageBox.question(
            window,
            t("migrate_data"),
            t("migrate_data_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

        apply_profile(new_profile)

        if migrate:
            window._do_migration()

        need_restart = True

    # Why:update_settings 默认延迟 2s 落盘,若用户立即关闭/被 kill 会丢字段
    flush_settings()

    if need_restart:
        QMessageBox.information(
            window,
            t("need_restart"),
            t("restart_msg"),
        )
