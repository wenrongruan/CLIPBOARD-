"""数据库管理器抽象基类 — DatabaseManager 和 MySQLDatabaseManager 的统一接口"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Callable, Optional, Tuple


class AbstractDatabaseManager(ABC):
    """所有数据库管理器必须实现的接口"""

    # 占位符：SQLite 为 "?"，MySQL 为 "%s"。Repository 使用 "?" 写 SQL，由执行器自动替换。
    placeholder: str = "?"
    # 方言标识，供 Repository 在需要走分支的极少数 SQL（如 DELETE ORDER BY LIMIT）使用
    is_mysql: bool = False

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

    # ========== SQL 执行统一接口（由子类实现） ==========

    @abstractmethod
    def execute_write(self, conn, sql: str, params: tuple = ()) -> Tuple[int, Optional[int]]:
        """执行写 SQL，返回 (rowcount, lastrowid)。自动处理占位符方言差异。"""
        ...

    @abstractmethod
    def fetch_one(self, conn, sql: str, params: tuple = ()):
        """读单行，返回方言原生 row 对象（sqlite3.Row 或 dict）。"""
        ...

    @abstractmethod
    def fetch_all(self, conn, sql: str, params: tuple = ()) -> list:
        """读所有行。"""
        ...

    def fetch_scalar(self, conn, sql: str, params: tuple = (), default=0):
        """读单一标量值（默认取第一列）。"""
        row = self.fetch_one(conn, sql, params)
        if row is None:
            return default
        if isinstance(row, dict):
            return next(iter(row.values()))
        return row[0]

    def execute_many(self, conn, sql: str, data: list):
        """批量执行（方言透明）。默认实现由子类覆盖。"""
        raise NotImplementedError
