"""数据库工厂 - 根据配置创建合适的数据库管理器"""

import logging
from config import Config

logger = logging.getLogger(__name__)


def create_database_manager():
    """
    根据配置创建数据库管理器
    返回 DatabaseManager 或 MySQLDatabaseManager 实例
    """
    db_type = Config.get_db_type()

    if db_type == "mysql":
        from .mysql_database import MySQLDatabaseManager

        mysql_config = Config.get_mysql_config()
        logger.info(f"使用 MySQL 数据库: {mysql_config['host']}:{mysql_config['port']}/{mysql_config['database']}")

        return MySQLDatabaseManager(
            host=mysql_config["host"],
            port=mysql_config["port"],
            user=mysql_config["user"],
            password=mysql_config["password"],
            database=mysql_config["database"],
        )
    else:
        from .database import DatabaseManager

        db_path = Config.get_database_path()
        logger.info(f"使用 SQLite 数据库: {db_path}")

        return DatabaseManager(db_path)
