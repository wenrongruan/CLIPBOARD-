"""云端同步 Tab：登录/已登录视图 + 文件云同步开关。"""

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGroupBox, QLabel, QMessageBox, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from config import get_cloud_access_token, settings, update_settings
from i18n import t  # noqa: F401  (保留，与其他 Tab 一致；部分子部件可能也会用)

logger = logging.getLogger(__name__)


def _restore_cloud_api_from_config():
    """返回全局 CloudAPIClient（仅在已登录时返回非 None）。"""
    if not get_cloud_access_token():
        return None
    try:
        from core.cloud_api import get_cloud_client
        return get_cloud_client()
    except Exception:
        logger.warning("恢复 CloudAPIClient 失败", exc_info=True)
        return None


class CloudTab(QWidget):
    """对应旧 SettingsDialog._setup_cloud_tab。

    暴露 cloud_api 属性供 SettingsDialog.get_cloud_api() 透传给主窗口。
    """

    cloud_api_changed = Signal(object)  # 登录/登出后通知 shell 更新 plugin_manager

    def __init__(
        self,
        ctx=None,
        parent=None,
        cloud_api=None,
        plugin_manager=None,
        **_legacy_kwargs,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self._cloud_api = cloud_api
        self._plugin_manager = plugin_manager
        if ctx is not None:
            if self._cloud_api is None:
                self._cloud_api = getattr(ctx, "cloud_api", None)
            if self._plugin_manager is None:
                self._plugin_manager = getattr(ctx, "plugin_manager", None)
        self._build_ui()

    # ---- UI ----

    def _build_ui(self):
        # Why: 对话框 setFixedSize(580, 560)，而登录后的 SubscriptionWidget 包含
        # 账户信息 + 用量 + 多个按钮，比登录表单高得多；不套 QScrollArea 的话，
        # 首次登录后切到已登录视图，下半部分（用量/退出登录按钮）会被裁掉。
        cloud_outer = QVBoxLayout(self)
        cloud_outer.setContentsMargins(0, 0, 0, 0)
        cloud_outer.setSpacing(0)

        cloud_scroll = QScrollArea(self)
        cloud_scroll.setWidgetResizable(True)
        cloud_scroll.setFrameShape(QScrollArea.NoFrame)
        cloud_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        cloud_content = QWidget()
        cloud_layout = QVBoxLayout(cloud_content)
        cloud_layout.setSpacing(12)
        cloud_layout.setContentsMargins(20, 20, 20, 20)

        desc = QLabel(
            "云端同步是可选增强：未登录时所有核心功能（历史、搜索、收藏、热键）依然可用。\n"
            "登录后，你的剪贴板记录会备份到云端（收藏 + 最新记录），方便多设备间访问。\n"
            "「文件云同步」与「剪贴板同步」是两件事：\n"
            "  · 剪贴板同步：传文本和图片，免费档位即可使用。\n"
            "  · 文件云同步：付费增强，按容量上传原始文件字节，可单独开关。"
        )
        desc.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        desc.setWordWrap(True)
        cloud_layout.addWidget(desc)

        # 文件云同步开关组（付费功能；这里只是 UX 开关，会员闸由 EntitlementService 控）
        files_group = QGroupBox("文件云同步（付费功能）")
        files_form = QFormLayout(files_group)
        files_form.setSpacing(8)

        self.files_sync_enabled_check = QCheckBox("启用文件云同步")
        self.files_sync_enabled_check.setChecked(settings().files_sync_enabled)
        files_form.addRow(self.files_sync_enabled_check)

        self.files_auto_download_check = QCheckBox("新设备登录后自动下载云端文件")
        self.files_auto_download_check.setChecked(settings().files_auto_download)
        files_form.addRow(self.files_auto_download_check)

        self.files_auto_download_limit = QSpinBox()
        self.files_auto_download_limit.setRange(0, 10240)
        self.files_auto_download_limit.setSingleStep(50)
        self.files_auto_download_limit.setValue(settings().files_max_autodownload_mb)
        self.files_auto_download_limit.setSpecialValueText("不限制")
        self.files_auto_download_limit.setSuffix(" MB")
        files_form.addRow("自动下载单文件上限", self.files_auto_download_limit)

        cloud_layout.addWidget(files_group)

        self._cloud_content_container = QWidget()
        self._cloud_content_layout = QVBoxLayout(self._cloud_content_container)
        self._cloud_content_layout.setContentsMargins(0, 0, 0, 0)
        cloud_layout.addWidget(self._cloud_content_container, 1)

        if not self._cloud_api:
            self._cloud_api = _restore_cloud_api_from_config()

        if self._cloud_api and self._cloud_api.is_authenticated:
            if self._plugin_manager:
                self._plugin_manager.set_cloud_client(self._cloud_api)
            self._show_cloud_logged_in()
        else:
            self._show_cloud_login_form()

        cloud_scroll.setWidget(cloud_content)
        cloud_outer.addWidget(cloud_scroll)

    # ---- 内部视图切换 ----

    def _clear_cloud_content(self):
        """移除 _cloud_content_layout 里的全部 widget/spacer，避免登录态切换后残留旧 UI。"""
        layout = self._cloud_content_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _show_cloud_login_form(self):
        from core.cloud_api import get_cloud_client
        from ui.cloud_login_widget import CloudLoginWidget

        self._clear_cloud_content()
        layout = self._cloud_content_layout

        form_group = QGroupBox("登录云端账户")
        group_layout = QVBoxLayout(form_group)

        if not self._cloud_api:
            self._cloud_api = get_cloud_client()

        self._cloud_login_widget = CloudLoginWidget(self._cloud_api)
        self._cloud_login_widget.login_succeeded.connect(self._on_cloud_login_success)
        group_layout.addWidget(self._cloud_login_widget)

        layout.addWidget(form_group)
        layout.addStretch()

    def _show_cloud_logged_in(self):
        from ui.subscription_widget import SubscriptionWidget
        self._clear_cloud_content()
        widget = SubscriptionWidget(self._cloud_api)
        try:
            widget.logout_completed.connect(self._show_cloud_login_form)
        except Exception:
            pass
        self._cloud_content_layout.addWidget(widget)

    def _on_cloud_login_success(self, result: dict):
        # Why: 旧实现只更新一条"重启后生效"的文字，用户永远看不到套餐/用量。
        # 登录成功后直接切换到已登录视图，用量/套餐/登出按钮立即可见；
        # 云端同步服务本身仍需重启应用才会挂载。
        if self._plugin_manager and self._cloud_api:
            self._plugin_manager.set_cloud_client(self._cloud_api)
        self.cloud_api_changed.emit(self._cloud_api)
        self._show_cloud_logged_in()
        # 首次登录后用一次性弹窗解释同步范围；后续不再重复打扰
        try:
            from config import flush_settings, settings as _cfg
            if not getattr(_cfg(), "cloud_scope_explainer_shown", False):
                QMessageBox.information(
                    self,
                    "云端同步范围说明",
                    "登录已完成。请知悉：\n\n"
                    "· 默认同步：收藏条目 + 最新剪贴板记录（文本与图片缩略数据）。\n"
                    "· 不同步：本机历史中未收藏的旧条目、未启用文件同步时的原始文件。\n"
                    "· 设备：每个登录设备独立同步队列，可在「云端同步」页查看用量。\n"
                    "· 隐私：可在 settings.json 的 excluded_source_apps 中加入密码"
                    "管理器、银行客户端等敏感来源关键字以排除。\n\n"
                    "随时可在「云端同步」页登出，登出后本地数据保留。",
                )
                update_settings(cloud_scope_explainer_shown=True)
                flush_settings()
        except Exception:
            pass

    # ---- 对外接口 ----

    @property
    def cloud_api(self):
        return self._cloud_api

    def apply(self) -> None:
        """OK 时持久化文件同步开关组的字段。"""
        try:
            update_settings(
                files_sync_enabled=self.files_sync_enabled_check.isChecked(),
                files_auto_download=self.files_auto_download_check.isChecked(),
                files_max_autodownload_mb=int(self.files_auto_download_limit.value()),
            )
        except Exception as e:
            logger.warning(f"保存文件同步配置失败: {e}")
