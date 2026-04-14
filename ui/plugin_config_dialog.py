"""插件配置对话框 — 根据 plugin manifest 的 config_schema 自动生成表单"""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from i18n import t
from .styles import MAIN_STYLE


class PluginConfigDialog(QDialog):
    """根据 config_schema 自动生成的插件配置对话框"""

    def __init__(self, plugin_name: str, schema: dict, current_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("plugin_config_title", name=plugin_name))
        self.setFixedWidth(420)
        self.setStyleSheet(MAIN_STYLE)
        self._schema = schema
        self._widgets = {}
        self._setup_ui(current_config)

    def _setup_ui(self, current_config: dict):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(10)

        for key, spec in self._schema.items():
            field_type = spec.get("type", "string")
            label_text = spec.get("label", key)
            if spec.get("required"):
                label_text += " *"
            description = spec.get("description", "")
            default = spec.get("default", "")
            value = current_config.get(key, default)

            if field_type == "string":
                widget = QLineEdit()
                widget.setText(str(value) if value is not None else "")
                widget.setPlaceholderText(description)
                if spec.get("secret"):
                    widget.setEchoMode(QLineEdit.Password)
                self._widgets[key] = widget
                form.addRow(label_text, widget)

            elif field_type == "number":
                widget = QSpinBox()
                widget.setRange(spec.get("min", 0), spec.get("max", 999999))
                widget.setSingleStep(spec.get("step", 1))
                widget.setValue(int(value) if value is not None else 0)
                self._widgets[key] = widget
                form.addRow(label_text, widget)

            elif field_type == "boolean":
                widget = QCheckBox()
                widget.setChecked(bool(value))
                self._widgets[key] = widget
                form.addRow(label_text, widget)

            elif field_type == "select":
                widget = QComboBox()
                options = spec.get("options", [])
                widget.addItems([str(o) for o in options])
                if value in options:
                    widget.setCurrentText(str(value))
                self._widgets[key] = widget
                form.addRow(label_text, widget)

        layout.addLayout(form)
        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton(t("plugin_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QPushButton(t("plugin_save"))
        save_btn.setObjectName("okButton")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _on_save(self):
        for key, spec in self._schema.items():
            if spec.get("required"):
                widget = self._widgets.get(key)
                if widget is None:
                    continue
                empty = False
                if isinstance(widget, QLineEdit):
                    empty = not widget.text().strip()
                elif isinstance(widget, QComboBox):
                    empty = not widget.currentText()
                if empty:
                    QMessageBox.warning(self, "", t("plugin_config_required"))
                    return
        self.accept()

    def get_config(self) -> dict:
        config = {}
        for key, spec in self._schema.items():
            widget = self._widgets.get(key)
            if widget is None:
                continue
            field_type = spec.get("type", "string")
            if field_type == "string":
                config[key] = widget.text()
            elif field_type == "number":
                config[key] = widget.value()
            elif field_type == "boolean":
                config[key] = widget.isChecked()
            elif field_type == "select":
                config[key] = widget.currentText()
        return config
