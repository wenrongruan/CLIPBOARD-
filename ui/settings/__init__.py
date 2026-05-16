"""设置对话框包：QTabWidget 壳 + 每个 Tab 一个文件。

新代码统一从这里导入 SettingsDialog；ui/settings_dialog.py 仅作为
向后兼容 shim。
"""

from ui.settings.settings_dialog import SettingsDialog  # noqa: F401

__all__ = ["SettingsDialog"]
