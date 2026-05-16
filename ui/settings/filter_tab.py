"""过滤与存储 Tab：保留文本/图片开关、上限、清理策略、轮询间隔。"""

from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGroupBox, QSpinBox, QVBoxLayout, QWidget,
)

from config import settings
from i18n import t


class FilterTab(QWidget):
    """对应旧 SettingsDialog._build_filter_tab。"""

    def __init__(self, ctx=None, parent=None, **_legacy_kwargs):
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- 内容过滤 ----
        filter_group = QGroupBox(t("content_filter"))
        filter_group_layout = QFormLayout(filter_group)
        filter_group_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        filter_group_layout.setSpacing(8)

        self.save_text_check = QCheckBox(t("save_text"))
        self.save_text_check.setChecked(settings().save_text)
        filter_group_layout.addRow(self.save_text_check)

        self.save_images_check = QCheckBox(t("save_images"))
        self.save_images_check.setChecked(settings().save_images)
        filter_group_layout.addRow(self.save_images_check)

        self.max_text_length_spin = QSpinBox()
        self.max_text_length_spin.setRange(0, 10000000)
        self.max_text_length_spin.setValue(settings().max_text_length)
        self.max_text_length_spin.setSpecialValueText(t("unlimited"))
        self.max_text_length_spin.setSuffix(f" {t('characters')}")
        filter_group_layout.addRow(t("max_text_length"), self.max_text_length_spin)

        self.max_image_size_spin = QSpinBox()
        self.max_image_size_spin.setRange(0, 102400)
        self.max_image_size_spin.setValue(settings().max_image_size_kb)
        self.max_image_size_spin.setSpecialValueText(t("unlimited"))
        self.max_image_size_spin.setSuffix(" KB")
        filter_group_layout.addRow(t("max_image_size"), self.max_image_size_spin)

        layout.addWidget(filter_group)

        # ---- 存储管理 ----
        storage_group = QGroupBox(t("storage_management"))
        storage_group_layout = QFormLayout(storage_group)
        storage_group_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        storage_group_layout.setSpacing(8)

        self.max_items_spin = QSpinBox()
        self.max_items_spin.setRange(100, 100000)
        self.max_items_spin.setValue(settings().max_items)
        storage_group_layout.addRow(t("max_items"), self.max_items_spin)

        self.retention_days_spin = QSpinBox()
        self.retention_days_spin.setRange(0, 3650)
        self.retention_days_spin.setValue(settings().retention_days)
        self.retention_days_spin.setSpecialValueText(t("never_cleanup"))
        self.retention_days_spin.setSuffix(f" {t('days')}")
        storage_group_layout.addRow(t("retention_days"), self.retention_days_spin)

        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(100, 5000)
        self.poll_interval_spin.setSingleStep(100)
        self.poll_interval_spin.setValue(settings().poll_interval_ms)
        self.poll_interval_spin.setSuffix(" ms")
        storage_group_layout.addRow(t("poll_interval"), self.poll_interval_spin)

        layout.addWidget(storage_group)
        layout.addStretch()

    def collect(self) -> dict:
        return {
            "save_text": self.save_text_check.isChecked(),
            "save_images": self.save_images_check.isChecked(),
            "max_text_length": self.max_text_length_spin.value(),
            "max_image_size_kb": self.max_image_size_spin.value(),
            "max_items": self.max_items_spin.value(),
            "retention_days": self.retention_days_spin.value(),
            "poll_interval_ms": self.poll_interval_spin.value(),
        }
