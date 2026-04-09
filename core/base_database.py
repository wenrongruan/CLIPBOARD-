"""数据库管理器抽象基类 — DatabaseManager 和 MySQLDatabaseManager 的统一接口"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Callable


class AbstractDatabaseManager(ABC):
    """所有数据库管理器必须实现的接口"""

    @abstractmethod
    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器）"""
        ...

    @abstractmethod
    def close(self):
        """关闭连接"""
        ...

    @abstractmethod
    def execute_with_retry(
        self, operation: Callable, max_retries: int = 5
    ) -> Any:
        """带重试的写操作"""
        ...

    @abstractmethod
    def execute_read(self, operation: Callable) -> Any:
        """只读操作"""
        ...

    @abstractmethod
    def check_connection(self) -> bool:
        """检查连接是否可用"""
        ...
