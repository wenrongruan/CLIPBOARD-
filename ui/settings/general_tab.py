"""通用设置 Tab：语言 / 停靠位置 / 全局热键 / 窗口标题捕获开关。"""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QWidget,
)

from config import get_effective_hotkey, settings, update_settings
from i18n import get_languages, t


class GeneralTab(QWidget):
    """对应旧 SettingsDialog._build_general_tab。"""

    def __init__(self, ctx=None, parent=None, **_legacy_kwargs):
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(12)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # 语言
        self.language_combo = QComboBox()
        languages = get_languages()
        self._language_codes = list(languages.keys())
        self.language_combo.addItems(list(languages.values()))
        current_lang = settings().language
        if current_lang in self._language_codes:
            self.language_combo.setCurrentIndex(self._language_codes.index(current_lang))
        layout.addRow(t("language"), self.language_combo)

        # 停靠位置
        self.dock_combo = QComboBox()
        self.dock_combo.addItems([t("dock_right"), t("dock_left"), t("dock_top"), t("dock_bottom")])
        edge_map = {"right": 0, "left": 1, "top": 2, "bottom": 3}
        current_edge = settings().dock_edge
        self.dock_combo.setCurrentIndex(edge_map.get(current_edge, 0))
        layout.addRow(t("dock_position"), self.dock_combo)

        # 全局热键
        hotkey_layout = QHBoxLayout()
        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setText(get_effective_hotkey())
        self.hotkey_edit.setPlaceholderText(t("hotkey_placeholder"))
        hotkey_layout.addWidget(self.hotkey_edit)

        hotkey_help = QLabel("?")
        hotkey_help.setToolTip(t("hotkey_help"))
        hotkey_help.setStyleSheet("color: #888; font-weight: bold;")
        hotkey_layout.addWidget(hotkey_help)
        layout.addRow(t("global_hotkey"), hotkey_layout)

        # 隐私：捕获窗口标题
        self.capture_source_title_check = QCheckBox("捕获窗口标题（存入来源记录）")
        self.capture_source_title_check.setToolTip(
            "仅在需要后续搜索或审计窗口标题时开启。默认关闭以保护隐私。"
        )
        self.capture_source_title_check.setChecked(
            bool(getattr(settings(), "capture_source_title", False))
        )
        layout.addRow("隐私", self.capture_source_title_check)

    # ---- 对外接口（由 SettingsDialog 在 OK 时调用） ----

    def selected_language(self) -> str:
        return self._language_codes[self.language_combo.currentIndex()]

    def selected_dock_edge(self) -> str:
        return ["right", "left", "top", "bottom"][self.dock_combo.currentIndex()]

    def selected_hotkey(self) -> str:
        return self.hotkey_edit.text()

    def apply(self) -> None:
        """OK 时持久化 capture_source_title（其余字段通过 collect() 由主窗口批量落盘）。"""
        import logging
        logger = logging.getLogger(__name__)
        try:
            update_settings(
                capture_source_title=self.capture_source_title_check.isChecked(),
            )
        except Exception as e:
            logger.warning(f"保存 capture_source_title 失败: {e}")

    def collect(self) -> dict:
        """返回主窗口在 OK 后需要的字段。"""
        return {
            "language": self.selected_language(),
            "dock_edge": self.selected_dock_edge(),
            "hotkey": self.selected_hotkey(),
        }
