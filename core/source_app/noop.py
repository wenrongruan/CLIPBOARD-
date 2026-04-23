"""空实现 provider，所有平台失败时的兜底。"""
from .base import SourceApp, SourceAppProvider


class NoopSourceAppProvider(SourceAppProvider):
    """永远返回空 SourceApp 的兜底 provider。"""

    def get_current(self) -> SourceApp:
        return SourceApp()

    @property
    def is_available(self) -> bool:
        return True
