"""来源 App 捕获：抽象基类与数据类。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceApp:
    """前台应用标识。所有字段都可能为空字符串。"""

    app_name: str = ""       # 人类可读名 (e.g. "Google Chrome")
    bundle_id: str = ""      # Mac bundle id / Win exe basename / Linux WM_CLASS
    exe_path: str = ""       # 进程可执行路径 (best effort)
    window_title: str = ""   # 当前窗口标题（隐私：调用方决定用不用）

    @property
    def is_empty(self) -> bool:
        return not (self.app_name or self.bundle_id or self.exe_path)


class SourceAppProvider(ABC):
    """平台特定 provider 抽象。"""

    @abstractmethod
    def get_current(self) -> SourceApp:
        """返回当前前台应用，失败返回空 SourceApp()。"""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """本平台/会话下 provider 是否可用。"""
        ...
