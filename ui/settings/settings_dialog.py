"""SettingsDialog 壳：QTabWidget 容器 + OK / Cancel 路由。

业务在 ui/settings/<*>_tab.py，壳只负责：
- 装配 7 个 Tab（通用 / 数据库 / 过滤 / 插件 / 云端 / 团队 / 关于）
- OK 时按顺序：DatabaseTab 校验并写入 MySQL → 各 Tab.apply()
- get_settings() / get_cloud_api() 供 ui/main_window.py 在 exec() 后调用

向后兼容：`SettingsDialog(parent, plugin_manager=..., cloud_api=..., space_service=...,
entitlement_service=..., initial_tab="")` 的原签名继续可用；新代码可以传 ctx=AppContext。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QVBoxLayout

from i18n import t
from ui.settings.about_tab import AboutTab
from ui.settings.cloud_tab import CloudTab
from ui.settings.database_tab import DatabaseTab
from ui.settings.filter_tab import FilterTab
from ui.settings.general_tab import GeneralTab
from ui.settings.plugins_tab import PluginsTab
from ui.settings.team_tab import TeamTab
from ui.styles import MAIN_STYLE


class SettingsDialog(QDialog):
    """7 个 Tab 的容器（顺序与旧实现一致）。"""

    def __init__(
        self,
        parent=None,
        plugin_manager=None,
        cloud_api=None,
        space_service=None,
        entitlement_service=None,
        initial_tab: str = "",
        ctx=None,
        auto_load_store: bool = True,
    ):
        super().__init__(parent)
        # ctx 优先；任何显式 kwarg 为 None 时尝试从 ctx 兜底
        self.ctx = ctx
        if ctx is not None:
            if plugin_manager is None:
                plugin_manager = getattr(ctx, "plugin_manager", None)
            if cloud_api is None:
                cloud_api = getattr(ctx, "cloud_api", None)
            if space_service is None:
                space_service = getattr(ctx, "space_service", None)
            if entitlement_service is None:
                entitlement_service = getattr(ctx, "entitlement_service", None)

        self._plugin_manager = plugin_manager
        self._cloud_api = cloud_api
        self._space_service = space_service
        self._entitlement_service = entitlement_service
        self._initial_tab = initial_tab or ""
        self._auto_load_store = auto_load_store

        self.setWindowTitle(t("settings"))
        self.setFixedSize(580, 560)
        self.setStyleSheet(MAIN_STYLE)
        # Why: 父 MainWindow 带 WindowStaysOnTopHint + Tool, 子 dialog 不继承
        # 这两个标志时会被父窗口永久盖住, 表现为"点击设置没反应"。
        # 给 dialog 也加 StayOnTop 让它始终浮在父窗口之上。
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self._tab_name_to_index: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # 装配 7 个 Tab。顺序与旧实现一致。
        self.general_tab = GeneralTab(ctx=self.ctx, parent=self)
        self._tab_name_to_index["general"] = tab_widget.addTab(self.general_tab, t("general"))

        self.database_tab = DatabaseTab(ctx=self.ctx, parent=self)
        self._tab_name_to_index["database"] = tab_widget.addTab(self.database_tab, t("database"))

        self.filter_tab = FilterTab(ctx=self.ctx, parent=self)
        self._tab_name_to_index["filter"] = tab_widget.addTab(self.filter_tab, t("filter_storage"))

        self.plugins_tab = PluginsTab(
            ctx=self.ctx,
            parent=self,
            plugin_manager=self._plugin_manager,
            auto_load_store=self._auto_load_store,
        )
        self._tab_name_to_index["plugins"] = tab_widget.addTab(self.plugins_tab, t("plugins"))

        self.cloud_tab = CloudTab(
            ctx=self.ctx, parent=self,
            cloud_api=self._cloud_api, plugin_manager=self._plugin_manager,
        )
        self.cloud_tab.cloud_api_changed.connect(self._on_cloud_api_changed)
        self._tab_name_to_index["cloud"] = tab_widget.addTab(self.cloud_tab, "云端同步")

        self.team_tab = TeamTab(
            ctx=self.ctx, parent=self,
            space_service=self._space_service,
            entitlement_service=self._entitlement_service,
        )
        self._tab_name_to_index["team"] = tab_widget.addTab(self.team_tab, "团队")

        self.about_tab = AboutTab(ctx=self.ctx, parent=self)
        self._tab_name_to_index["about"] = tab_widget.addTab(self.about_tab, t("about"))

        if self._initial_tab and self._initial_tab in self._tab_name_to_index:
            tab_widget.setCurrentIndex(self._tab_name_to_index[self._initial_tab])

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = button_box.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setObjectName("okButton")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # ---- Tab 间信号 ----

    def _on_cloud_api_changed(self, cloud_api):
        """CloudTab 登录成功后通知 shell；主窗口在 exec() 后通过 get_cloud_api() 读取。"""
        self._cloud_api = cloud_api

    # ---- OK / Cancel ----

    def _on_accept(self):
        # 1) DatabaseTab 校验 MySQL（连通性 + api 公共库探测）+ 写入 keyring
        if not self.database_tab.validate_and_persist_on_accept():
            return
        # 2) 各 Tab apply（仅做"本 Tab 独有"的持久化）
        for tab in (self.general_tab, self.cloud_tab):
            if hasattr(tab, "apply"):
                tab.apply()
        self.accept()

    # ---- 对外接口（main_window 依赖） ----

    def get_cloud_api(self):
        # CloudTab 登录后回写到 self._cloud_api；否则保持构造时的值
        return self._cloud_api or self.cloud_tab.cloud_api

    def get_settings(self) -> dict:
        """返回纯 dict（含明文 mysql_password 字段）。

        Why: 旧实现把 keyring 写入藏在这里，违反"读"的语义；现在 keyring 写入
        已挪到 OK 流程（DatabaseTab.validate_and_persist_on_accept）。
        """
        result: dict = {}
        result.update(self.general_tab.collect())
        result.update(self.filter_tab.collect())
        result.update(self.database_tab.collect())
        return result
