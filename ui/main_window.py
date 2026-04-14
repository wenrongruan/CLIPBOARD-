import os
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QMenu,
    QDialog,
    QMessageBox,
    QFileDialog,
    QProgressDialog,
)

from core.models import ClipboardItem
from core.repository import ClipboardRepository
from core.clipboard_monitor import ClipboardMonitor
from core.sync_service import SyncService
from core.plugin_api import PluginResult, PluginResultAction
from config import Config
from i18n import t, set_language, get_language
from .edge_window import EdgeHiddenWindow
from .clipboard_item import ClipboardItemWidget
from .styles import MAIN_STYLE
from .settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


def _restore_cloud_api_from_config():
    """返回全局 CloudAPIClient（仅在已登录时返回非 None，用于向后兼容旧调用点）。"""
    if not Config.get_cloud_access_token():
        return None
    try:
        from core.cloud_api import get_cloud_client
        return get_cloud_client()
    except Exception:
        logger.warning("恢复 CloudAPIClient 失败", exc_info=True)
        return None


class MainWindow(EdgeHiddenWindow):
    quit_requested = Signal()  # 退出信号
    # 内部信号：worker 线程加载完整图片后回到主线程执行剪贴板写入
    _image_load_done = Signal(object)

    def __init__(
        self,
        repository: ClipboardRepository,
        clipboard_monitor: ClipboardMonitor,
        sync_service: SyncService,
        plugin_manager=None,
        cloud_api=None,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.clipboard_monitor = clipboard_monitor
        self.sync_service = sync_service
        self.plugin_manager = plugin_manager
        self.cloud_api = cloud_api

        # 如果没有传入 cloud_api，但有已保存的 token，则创建客户端
        if not self.cloud_api:
            self.cloud_api = _restore_cloud_api_from_config()

        # 将 cloud_api 注入到 PluginManager，使插件可以复用登录态
        if self.plugin_manager and self.cloud_api:
            self.plugin_manager.set_cloud_client(self.cloud_api)

        self._current_page = 0
        self._total_pages = 1
        self._page_size = Config.PAGE_SIZE
        self._search_query = ""
        self._starred_only = False
        self._items: List[ClipboardItem] = []
        self._copy_executor = ThreadPoolExecutor(max_workers=1)
        self._cloud_executor = ThreadPoolExecutor(max_workers=1)

        self.setStyleSheet(MAIN_STYLE)
        self._setup_ui()
        self._connect_signals()
        self._load_items()

    def _setup_ui(self):
        # 直接在窗口上设置布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 顶部：搜索和设置
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("search_placeholder"))
        self.search_input.textChanged.connect(self._on_search_changed)
        header_layout.addWidget(self.search_input, 1)

        self.star_filter_btn = QPushButton("☆")
        self.star_filter_btn.setToolTip(t("show_starred_only"))
        self.star_filter_btn.setFixedSize(28, 28)
        self.star_filter_btn.clicked.connect(self._toggle_starred_filter)
        header_layout.addWidget(self.star_filter_btn)

        self.pin_btn = QPushButton("📌")
        self.pin_btn.setToolTip(t("pin_window"))
        self.pin_btn.setFixedSize(28, 28)
        self.pin_btn.clicked.connect(self._toggle_pin)
        header_layout.addWidget(self.pin_btn)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setToolTip(t("settings"))
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.clicked.connect(self._show_settings)
        header_layout.addWidget(self.settings_btn)

        self.minimize_btn = QPushButton("—")
        self.minimize_btn.setToolTip(t("minimize"))
        self.minimize_btn.setFixedSize(28, 28)
        self.minimize_btn.clicked.connect(self._minimize_window)
        header_layout.addWidget(self.minimize_btn)

        self.quit_btn = QPushButton("✕")
        self.quit_btn.setToolTip(t("quit_app"))
        self.quit_btn.setFixedSize(28, 28)
        self.quit_btn.clicked.connect(self._request_quit)
        header_layout.addWidget(self.quit_btn)

        layout.addLayout(header_layout)

        # 中间：列表
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(1)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget, 1)

        # 复制反馈标签
        self.copy_feedback_label = QLabel()
        self.copy_feedback_label.setAlignment(Qt.AlignCenter)
        self.copy_feedback_label.hide()
        layout.addWidget(self.copy_feedback_label)

        # 底部：分页
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(8)

        self.prev_btn = QPushButton(t("prev_page"))
        self.prev_btn.clicked.connect(self._prev_page)
        pagination_layout.addWidget(self.prev_btn)

        self.page_label = QLabel("1 / 1")
        self.page_label.setObjectName("pageLabel")
        self.page_label.setAlignment(Qt.AlignCenter)
        pagination_layout.addWidget(self.page_label, 1)

        self.next_btn = QPushButton(t("next_page"))
        self.next_btn.clicked.connect(self._next_page)
        pagination_layout.addWidget(self.next_btn)

        layout.addLayout(pagination_layout)

        # 搜索防抖定时器
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)

        # 复制反馈定时器（复用同一个避免快速复制时提前隐藏）
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self.copy_feedback_label.hide)

    def _connect_signals(self):
        # 跨线程：图片加载完成 → 主线程写入剪贴板
        self._image_load_done.connect(self._handle_image_loaded)

        # 剪贴板监控信号
        self.clipboard_monitor.item_added.connect(self._on_item_added)

        # 同步服务信号
        self.sync_service.new_items_available.connect(self._on_new_items)

        # 插件信号
        if self.plugin_manager:
            self.plugin_manager.action_progress.connect(self._on_plugin_progress)
            self.plugin_manager.action_finished.connect(self._on_plugin_finished)
            self.plugin_manager.action_error.connect(self._on_plugin_error)

    def _toggle_starred_filter(self):
        self._starred_only = not self._starred_only
        self.star_filter_btn.setText("★" if self._starred_only else "☆")
        self._current_page = 0
        self._load_items()

    def _load_items(self):
        try:
            if self._search_query:
                items, total = self.repository.search(
                    self._search_query, self._current_page, self._page_size,
                    starred_only=self._starred_only
                )
            else:
                items, total = self.repository.get_items(
                    self._current_page, self._page_size,
                    starred_only=self._starred_only
                )

            self._items = items
            self._total_pages = max(1, (total + self._page_size - 1) // self._page_size)
            self._update_list()
            self._update_pagination()
        except Exception as e:
            logger.error(f"加载剪贴板条目失败: {e}")

    def _make_list_item(self, item: ClipboardItem):
        """创建 ClipboardItemWidget 和对应的 QListWidgetItem，连接信号"""
        widget = ClipboardItemWidget(item)
        widget.clicked.connect(self._on_item_clicked)
        widget.delete_clicked.connect(self._on_item_delete)
        widget.star_clicked.connect(self._on_item_star)
        widget.save_clicked.connect(self._on_item_save)
        widget.cloud_delete_clicked.connect(self._on_cloud_delete)

        list_item = QListWidgetItem()
        hint = widget.sizeHint()
        min_h = 92 if item.is_image else 76
        list_item.setSizeHint(QSize(hint.width(), max(hint.height(), min_h)))
        return list_item, widget

    def _update_list(self):
        self.list_widget.clear()

        for item in self._items:
            list_item, widget = self._make_list_item(item)
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, widget)

    def _update_pagination(self):
        self.page_label.setText(f"{self._current_page + 1} / {self._total_pages}")
        self.prev_btn.setEnabled(self._current_page > 0)
        self.next_btn.setEnabled(self._current_page < self._total_pages - 1)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._load_items()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._load_items()

    def _on_search_changed(self, text: str):
        self._search_timer.stop()
        self._search_timer.start(300)  # 300ms 防抖

    def _do_search(self):
        self._search_query = self.search_input.text().strip()
        self._current_page = 0
        self._load_items()

    def _show_copy_feedback(self, success: bool):
        """显示复制结果反馈"""
        if success:
            self.copy_feedback_label.setText(t("copied_to_clipboard"))
            self.copy_feedback_label.setObjectName("copyFeedbackSuccess")
        else:
            self.copy_feedback_label.setText(t("copy_failed"))
            self.copy_feedback_label.setObjectName("copyFeedbackError")
        self.copy_feedback_label.style().polish(self.copy_feedback_label)
        self.copy_feedback_label.show()
        self._feedback_timer.start(2000)

    def _on_item_clicked(self, item: ClipboardItem):
        # 图片需要从数据库获取完整数据 — 异步加载避免阻塞主线程
        if item.is_image:
            self.copy_feedback_label.setText("正在加载图片...")
            self.copy_feedback_label.setObjectName("copyFeedbackSuccess")
            self.copy_feedback_label.style().polish(self.copy_feedback_label)
            self.copy_feedback_label.show()

            item_id = item.id
            repo = self.repository
            signal = self._image_load_done

            def _load():
                # worker 线程没有 Qt 事件循环，必须用信号切回主线程
                try:
                    full = repo.get_item_by_id(item_id)
                except Exception as e:
                    logger.error(f"加载图片失败: {e}")
                    full = None
                signal.emit(full)

            self._copy_executor.submit(_load)
            return

        success = self.clipboard_monitor.copy_to_clipboard(item)
        self._show_copy_feedback(success)

    def _handle_image_loaded(self, full_item):
        """主线程槽：图片加载完成后写入剪贴板"""
        success = False
        if full_item and getattr(full_item, "image_data", None):
            try:
                success = self.clipboard_monitor.copy_to_clipboard(full_item)
            except Exception as e:
                logger.error(f"写入剪贴板失败: {e}")
        elif full_item:
            logger.warning(f"图片 id={full_item.id} 无完整数据，可能云端尚未下载")
        self._show_copy_feedback(success)

    def _on_item_delete(self, item: ClipboardItem):
        reply = QMessageBox.question(
            self,
            t("confirm_delete"),
            t("delete_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.repository.delete_item(item.id)
            self._load_items()

    def _on_cloud_delete(self, item: ClipboardItem):
        """删除条目的云端副本"""
        if not item.cloud_id or not self.cloud_api:
            return
        reply = QMessageBox.question(
            self,
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

        future = self._cloud_executor.submit(api.delete_item, cloud_id)

        def _on_done(f):
            try:
                f.result()
                self.repository.clear_cloud_id(item_id)
                item.cloud_id = None
                self._load_items()
            except Exception as e:
                logger.warning(f"删除云端副本失败: {e}")

        future.add_done_callback(lambda f: QTimer.singleShot(0, lambda: _on_done(f)))

    def _on_item_star(self, item: ClipboardItem):
        self.repository.toggle_star(item.id)
        self._load_items()

    def _on_item_save(self, item: ClipboardItem):
        """保存图片到本地文件"""
        full_item = self.repository.get_item_by_id(item.id)
        if not full_item or not full_item.image_data:
            QMessageBox.warning(self, t("error"), t("image_load_failed"))
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            t("save_image"),
            "",
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
        )
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(full_item.image_data)
            except Exception as e:
                QMessageBox.critical(self, t("error"), t("save_failed", error=str(e)))

    def _prepend_item(self, item: ClipboardItem):
        """在列表顶部插入单个新条目，避免全量重建"""
        list_item, widget = self._make_list_item(item)

        self.list_widget.insertItem(0, list_item)
        self.list_widget.setItemWidget(list_item, widget)
        self._items.insert(0, item)

        # 超出每页大小时移除末尾
        if self.list_widget.count() > self._page_size:
            self.list_widget.takeItem(self.list_widget.count() - 1)
            if len(self._items) > self._page_size:
                self._items.pop()

    def _on_item_added(self, item: ClipboardItem):
        if self._current_page == 0 and not self._search_query and not self._starred_only:
            self._prepend_item(item)
        elif self._current_page == 0 and not self._search_query:
            self._load_items()

    def _on_new_items(self, items: List[ClipboardItem]):
        # 来自其他设备的新记录
        if self._current_page == 0 and not self._search_query:
            self._load_items()

    def _toggle_pin(self):
        is_pinned = self.toggle_pin()
        # 取消固定时若处于悬浮模式，吸附回最近边缘
        if not is_pinned and self._is_floating:
            self._snap_to_nearest_edge()
        self.pin_btn.setText("📍" if is_pinned else "📌")
        self.pin_btn.setToolTip(t("unpin_window") if is_pinned else t("pin_window"))

    def _minimize_window(self):
        """最小化窗口（完全隐藏）"""
        self.hide_window()

    def _show_settings(self):
        dialog = SettingsDialog(self, plugin_manager=self.plugin_manager, cloud_api=self.cloud_api)
        result = dialog.exec()
        # 无论确认还是取消，都同步登录状态（用户可能在对话框中登录了云端）
        dialog_cloud_api = dialog.get_cloud_api()
        if dialog_cloud_api and dialog_cloud_api.is_authenticated:
            self.cloud_api = dialog_cloud_api
            if self.plugin_manager:
                self.plugin_manager.set_cloud_client(self.cloud_api)
        if result == QDialog.Accepted:
            settings = dialog.get_settings()
            need_restart = False

            # 语言变更
            new_language = settings["language"]
            if new_language != Config.get_language():
                Config.set_language(new_language)
                set_language(new_language)
                need_restart = True

            # 应用停靠边缘
            new_edge = settings["dock_edge"]
            if new_edge != Config.get_dock_edge():
                self.set_dock_edge(new_edge)

            # 热键变更
            new_hotkey = settings["hotkey"]
            if new_hotkey != Config.get_hotkey():
                Config.set_hotkey(new_hotkey)
                need_restart = True

            # 过滤与存储设置（批量更新，只写一次磁盘）
            new_poll_interval = settings["poll_interval_ms"]
            poll_changed = new_poll_interval != Config.get_poll_interval_ms()

            current_settings = Config.load_settings()
            for key in ("save_text", "save_images", "max_text_length",
                        "max_image_size_kb", "max_items", "retention_days",
                        "poll_interval_ms"):
                current_settings[key] = settings[key]
            Config.save_settings(current_settings)

            if poll_changed:
                self.clipboard_monitor.update_poll_interval(new_poll_interval)

            # Profile / 数据库变更检测
            new_profile = settings.get("active_profile", "")
            new_db_type = settings["db_type"]
            db_changed = False

            if new_profile != Config.get_active_profile():
                db_changed = True
            elif new_db_type != Config.get_db_type():
                db_changed = True
            elif new_db_type == "sqlite":
                # 空字符串表示使用默认路径，归一化后再比较
                new_path = settings["database_path"] or Config.get_database_path()
                if new_path != Config.get_database_path():
                    db_changed = True
            elif new_db_type == "mysql":
                mysql_config = Config.get_mysql_config()
                # 密码空表示"未在本次会话修改"（_current_db_settings 不回传密码），
                # 仅当用户实际填入了新密码且与 keyring 中不同才算变更
                pw_changed = bool(settings["mysql_password"]) and settings["mysql_password"] != mysql_config["password"]
                if (settings["mysql_host"] != mysql_config["host"] or
                    settings["mysql_port"] != mysql_config["port"] or
                    settings["mysql_user"] != mysql_config["user"] or
                    pw_changed or
                    settings["mysql_database"] != mysql_config["database"]):
                    db_changed = True

            if db_changed:
                # 询问是否迁移数据
                migrate = QMessageBox.question(
                    self,
                    t("migrate_data"),
                    t("migrate_data_confirm"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                ) == QMessageBox.Yes

                # 应用 profile 并保存配置
                Config.apply_profile(new_profile)

                if migrate:
                    self._do_migration()

                need_restart = True

            if need_restart:
                QMessageBox.information(
                    self,
                    t("need_restart"),
                    t("restart_msg"),
                )

    def _do_migration(self):
        """在工作线程中执行数据库迁移，避免阻塞 UI"""
        from core.migration import DatabaseMigrator
        from core.database import DatabaseManager
        from core.repository import ClipboardRepository
        from PySide6.QtCore import QThread, Signal as QSignal

        # 创建目标库连接
        try:
            db_type = Config.get_db_type()
            if db_type == "sqlite":
                target_db = DatabaseManager(Config.get_database_path())
                target_repo = ClipboardRepository(target_db)
            else:
                from core.mysql_database import MySQLDatabaseManager
                mysql_config = Config.get_mysql_config()
                target_db = MySQLDatabaseManager(
                    mysql_config["host"], mysql_config["port"],
                    mysql_config["user"], mysql_config["password"],
                    mysql_config["database"],
                )
                target_repo = ClipboardRepository(target_db)
        except Exception as e:
            QMessageBox.critical(
                self, t("error"), t("migration_failed", error=str(e))
            )
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

        migrator = DatabaseMigrator(self.repository, target_repo)

        progress_dlg = QProgressDialog(t("migrating"), None, 0, 100, self)
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
                self, t("success"), t("migration_complete", count=count)
            )

        def on_error(err):
            progress_dlg.close()
            QMessageBox.critical(
                self, t("error"), t("migration_failed", error=err)
            )

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_success)
        worker.finished_err.connect(on_error)
        # 防止 worker 被 GC 回收
        self._migration_worker = worker
        worker.start()

    # ========== 右键菜单 ==========

    def _show_context_menu(self, pos):
        """显示右键上下文菜单"""
        list_item = self.list_widget.itemAt(pos)
        if not list_item:
            return
        row = self.list_widget.row(list_item)
        if row < 0 or row >= len(self._items):
            return

        item = self._items[row]
        menu = QMenu(self)

        # 内置操作
        copy_action = menu.addAction(f"📋 {t('ctx_copy')}")
        copy_action.triggered.connect(lambda: self._on_item_clicked(item))

        if item.is_starred:
            star_action = menu.addAction(f"★ {t('ctx_unstar')}")
        else:
            star_action = menu.addAction(f"☆ {t('ctx_star')}")
        star_action.triggered.connect(lambda: self._on_item_star(item))

        delete_action = menu.addAction(f"🗑 {t('ctx_delete')}")
        delete_action.triggered.connect(lambda: self._on_item_delete(item))

        # 插件操作
        if self.plugin_manager:
            groups = self.plugin_manager.get_plugin_actions_grouped(item)
            if groups:
                menu.addSeparator()
                for group in groups:
                    actions = group["actions"]
                    if len(actions) == 1:
                        # 单动作插件直接作为菜单项
                        a = actions[0]
                        act = menu.addAction(f"{a.icon} {a.label}")
                        act.triggered.connect(
                            lambda checked=False, pid=group["plugin_id"], aid=a.action_id:
                                self._run_plugin_action(pid, aid, item)
                        )
                    else:
                        # 多动作插件使用子菜单
                        sub = menu.addMenu(f"{actions[0].icon} {group['plugin_name']}")
                        for a in actions:
                            act = sub.addAction(a.label)
                            act.triggered.connect(
                                lambda checked=False, pid=group["plugin_id"], aid=a.action_id:
                                    self._run_plugin_action(pid, aid, item)
                            )

        menu.exec(self.list_widget.mapToGlobal(pos))

    # ========== 插件执行 ==========

    def _run_plugin_action(self, plugin_id: str, action_id: str, item: ClipboardItem):
        """执行插件动作"""
        # 获取完整数据（图片需要从数据库加载）
        if item.is_image:
            full_item = self.repository.get_item_by_id(item.id)
            if full_item and full_item.image_data:
                item = full_item
            else:
                self._show_plugin_feedback("❌ " + t("plugin_error"), "copyFeedbackError")
                return

        if not self.plugin_manager.run_action(plugin_id, action_id, item):
            return  # 被拒绝（已有任务在执行）

        # 显示进度
        plugin_name = self.plugin_manager.get_plugin_name(plugin_id)
        self._show_plugin_feedback(
            t("plugin_executing", name=plugin_name, percent=0),
            "pluginProgress",
            show_cancel=True,
        )

    def _on_plugin_progress(self, percent: int, message: str):
        text = message if message else f"{percent}%"
        self._show_plugin_feedback(text, "pluginProgress", show_cancel=True)

    def _on_plugin_finished(self, result: PluginResult, original_item: ClipboardItem):
        if not result.success:
            if result.cancelled:
                self.copy_feedback_label.hide()
                return
            self._show_plugin_feedback(
                f"❌ {result.error_message or t('plugin_exec_failed')}", "copyFeedbackError"
            )
            return

        # 根据 action 处理结果
        if result.action == PluginResultAction.NONE:
            self.copy_feedback_label.hide()
            return

        if result.action == PluginResultAction.COPY:
            # 复制到剪贴板
            temp_item = ClipboardItem(
                content_type=result.content_type,
                text_content=result.text_content,
                image_data=result.image_data,
            )
            self.clipboard_monitor.copy_to_clipboard(temp_item)
            self._show_plugin_feedback(t("copied_to_clipboard"), "copyFeedbackSuccess")

        elif result.action == PluginResultAction.SAVE:
            # 保存为新条目
            from utils.hash_utils import compute_content_hash
            hash_content = result.text_content or result.image_data
            if not hash_content:
                self._show_plugin_feedback("❌ 插件返回空内容", "copyFeedbackError")
                return
            new_item = ClipboardItem(
                content_type=result.content_type,
                text_content=result.text_content,
                image_data=result.image_data,
                content_hash=compute_content_hash(hash_content),
                preview=(result.text_content or "")[:100],
                device_id=Config.get_device_id(),
                device_name=Config.get_device_name(),
            )
            self.repository.add_item(new_item)
            self._load_items()
            self._show_plugin_feedback(t("plugin_saved_entry"), "copyFeedbackSuccess")

        elif result.action == PluginResultAction.REPLACE:
            # 替换原条目
            if original_item and original_item.id:
                success = self.repository.update_item_content(
                    original_item.id,
                    text_content=result.text_content,
                    image_data=result.image_data,
                    content_type=result.content_type.value if result.content_type else None,
                )
                if success:
                    self._load_items()
                    self._show_plugin_feedback(t("plugin_replaced_entry"), "copyFeedbackSuccess")
                else:
                    self._show_plugin_feedback("❌ " + t("plugin_error"), "copyFeedbackError")

    def _on_plugin_error(self, message: str):
        self._show_plugin_feedback(f"❌ {message}", "copyFeedbackError")

    def _show_plugin_feedback(self, text: str, object_name: str, show_cancel: bool = False):
        """显示插件反馈信息"""
        if show_cancel:
            self.copy_feedback_label.setText(f"{text}  [✕]")
            self.copy_feedback_label.mousePressEvent = lambda e: self._cancel_plugin()
        else:
            self.copy_feedback_label.setText(text)
            self.copy_feedback_label.mousePressEvent = lambda e: None
            self._feedback_timer.start(3000)
        self.copy_feedback_label.setObjectName(object_name)
        self.copy_feedback_label.style().polish(self.copy_feedback_label)
        self.copy_feedback_label.show()

    def _cancel_plugin(self):
        if self.plugin_manager:
            self.plugin_manager.cancel_action()
        self.copy_feedback_label.hide()

    def _request_quit(self):
        """请求退出应用"""
        self.quit_requested.emit()
