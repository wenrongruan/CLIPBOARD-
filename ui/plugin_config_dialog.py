"""插件配置对话框 — 根据 plugin manifest 的 config_schema 自动生成表单"""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from i18n import t
from .styles import MAIN_STYLE


# P3.8: 把 manifest.permissions 里的字符串翻译成普通用户能看懂的解释
_PERMISSION_LABELS = {
    "network": ("网络访问", "插件可以访问互联网（HTTP 请求等）"),
    "cloud": ("云端 API", "插件可以调用本应用的云端账号 API（同步、订阅等）"),
    "cloud.subscription": ("云端：套餐/用量", "可读取你当前的套餐与用量"),
    "cloud.credits": ("云端：积分扣费", "插件可消耗你账户的云端积分（按使用计费）"),
    "cloud.files": ("云端：文件读写", "可读取/上传你绑定到云端的文件"),
    "clipboard.write": ("写剪贴板", "插件可以把内容写回剪贴板"),
    "clipboard.read": ("读剪贴板历史", "插件可以读取本地剪贴板历史"),
    "filesystem": ("本地文件读写", "插件可以读写本地文件"),
}


def _format_permission(perm: str) -> tuple:
    """返回 (label, description)；未知 perm 直接显示原始字符串。"""
    if perm in _PERMISSION_LABELS:
        return _PERMISSION_LABELS[perm]
    return perm, "插件未在内置说明中——使用前请确认其用途"


class PluginConfigDialog(QDialog):
    """根据 config_schema 自动生成的插件配置对话框"""

    def __init__(
        self,
        plugin_name: str,
        schema: dict,
        current_config: dict,
        parent=None,
        permissions=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(t("plugin_config_title", name=plugin_name))
        self.setFixedWidth(420)
        self.setStyleSheet(MAIN_STYLE)
        self._schema = schema
        self._permissions = list(permissions or [])
        self._widgets = {}
        self._setup_ui(current_config)

    def _setup_ui(self, current_config: dict):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 权限清单（在表单上方；无声明时不渲染该区块）
        if self._permissions:
            perm_box = QFrame()
            perm_box.setStyleSheet(
                "QFrame{background:rgba(88,166,255,0.08);"
                "border:1px solid rgba(88,166,255,0.4);border-radius:6px;padding:8px;}"
            )
            perm_layout = QVBoxLayout(perm_box)
            perm_layout.setSpacing(4)
            title = QLabel("此插件声明使用的权限")
            title.setStyleSheet(
                "color:#58a6ff;font-weight:600;background:transparent;border:none;"
            )
            perm_layout.addWidget(title)
            for p in self._permissions:
                label, desc = _format_permission(p)
                row = QLabel(f"· <b>{label}</b> — {desc}")
                row.setTextFormat(1)  # Qt.RichText
                row.setStyleSheet("color:#ddd;background:transparent;border:none;font-size:11px;")
                row.setWordWrap(True)
                perm_layout.addWidget(row)
            layout.addWidget(perm_box)

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
