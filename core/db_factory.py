"""数据库工厂 - 根据配置创建合适的数据库管理器"""

import logging
from config import settings, get_mysql_config, get_effective_database_path

logger = logging.getLogger(__name__)


def create_database_manager():
    """
    根据配置创建数据库管理器
    返回 DatabaseManager 或 MySQLDatabaseManager 实例

    云端模式 (cloud) 仍返回本地 SQLite DatabaseManager 作为本地缓存，
    云端同步由 CloudSyncService 单独负责。
    """
    s = settings()
    db_type = s.db_type
    sync_mode = s.sync_mode

    if db_type == "mysql" and sync_mode != "cloud":
        from .mysql_database import MySQLDatabaseManager

        mysql_config = get_mysql_config()
        logger.info(f"使用 MySQL 数据库: {mysql_config['host']}:{mysql_config['port']}/{mysql_config['database']} (user={mysql_config['user']})")

        return MySQLDatabaseManager(
            host=mysql_config["host"],
            port=mysql_config["port"],
            user=mysql_config["user"],
            password=mysql_config["password"],
            database=mysql_config["database"],
        )
    else:
        from .database import DatabaseManager

        db_path = get_effective_database_path()
        if sync_mode == "cloud":
            logger.info(f"云端模式 — 使用本地 SQLite 作为缓存: {db_path}")
        else:
            logger.info(f"使用 SQLite 数据库: {db_path}")

        return DatabaseManager(db_path)
