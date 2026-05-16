"""向后兼容 shim。新代码用 `from ui.settings import SettingsDialog`。

实际实现在 ui/settings/ 包内（每个 Tab 一个文件）。
"""

from ui.settings.settings_dialog import SettingsDialog  # noqa: F401

__all__ = ["SettingsDialog"]
