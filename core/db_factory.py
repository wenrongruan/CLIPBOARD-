"""数据库工厂 - 根据配置创建合适的数据库管理器"""

import logging
from config import settings, get_mysql_config, get_effective_database_path

logger = logging.getLogger(__name__)

# Why: MySQL 初始化失败时降级到本地 SQLite，启动不再被阻断。
# main.py 读取这个变量判断是否要弹托盘气泡提示用户修正配置。
# 值为 None 表示无降级；非 None 为错误摘要（不含密码等敏感信息）。
_mysql_fallback_reason: str | None = None


def get_mysql_fallback_reason() -> str | None:
    """返回最近一次 MySQL 降级的错误摘要，若无降级则返回 None。"""
    return _mysql_fallback_reason


def create_database_manager():
    """
    根据配置创建数据库管理器
    返回 DatabaseManager 或 MySQLDatabaseManager 实例

    云端模式 (cloud) 仍返回本地 SQLite DatabaseManager 作为本地缓存，
    云端同步由 CloudSyncService 单独负责。

    MySQL 模式若连接/权限失败，会降级到本地 SQLite 以确保应用可启动，
    降级原因通过 `get_mysql_fallback_reason()` 暴露供 UI 提示。
    """
    global _mysql_fallback_reason

    s = settings()
    db_type = s.db_type
    sync_mode = s.sync_mode

    if db_type == "mysql" and sync_mode != "cloud":
        from .mysql_database import MySQLDatabaseManager

        mysql_config = get_mysql_config()
        logger.debug(f"使用 MySQL 数据库: {mysql_config['host']}:{mysql_config['port']}/{mysql_config['database']} (user={mysql_config['user']})")

        try:
            return MySQLDatabaseManager(
                host=mysql_config["host"],
                port=mysql_config["port"],
                user=mysql_config["user"],
                password=mysql_config["password"],
                database=mysql_config["database"],
            )
        except Exception as e:
            _mysql_fallback_reason = str(e)[:200]
            logger.error(f"MySQL 连接/初始化失败，降级到本地 SQLite: {e}")
            # 继续走下面的 SQLite 分支

    from .database import DatabaseManager

    db_path = get_effective_database_path()
    if _mysql_fallback_reason:
        logger.warning(f"MySQL 降级模式 — 使用本地 SQLite: {db_path}")
    elif sync_mode == "cloud":
        logger.info(f"云端模式 — 使用本地 SQLite 作为缓存: {db_path}")
    else:
        logger.info(f"使用 SQLite 数据库: {db_path}")

    return DatabaseManager(db_path)
