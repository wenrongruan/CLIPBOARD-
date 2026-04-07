import re
import time
import random
import logging
import threading
from typing import Optional, Callable, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    logger.warning("pymysql 未安装，MySQL 功能不可用")


class MySQLDatabaseManager:
    """MySQL 数据库管理器"""

    SCHEMA_VERSION = 2

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS clipboard_items (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        content_type VARCHAR(10) NOT NULL,
        text_content LONGTEXT,
        image_data LONGBLOB,
        image_thumbnail MEDIUMBLOB,
        content_hash VARCHAR(64) NOT NULL UNIQUE,
        preview TEXT,
        device_id VARCHAR(32) NOT NULL,
        device_name VARCHAR(255),
        created_at BIGINT NOT NULL,
        is_starred TINYINT DEFAULT 0,
        INDEX idx_created_at (created_at DESC),
        INDEX idx_content_type (content_type),
        INDEX idx_device_id (device_id),
        INDEX idx_content_hash (content_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    CREATE_META_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS app_meta (
        `key` VARCHAR(255) PRIMARY KEY,
        `value` TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # 数据库名白名单：仅允许字母、数字、下划线
    _SAFE_DB_NAME = re.compile(r'^[a-zA-Z0-9_]+$')

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        if not PYMYSQL_AVAILABLE:
            raise ImportError("pymysql 未安装，请运行: pip install pymysql")

        # 校验数据库名，防止 SQL 注入
        if not self._SAFE_DB_NAME.match(database):
            raise ValueError(f"不安全的数据库名（仅允许字母、数字、下划线）: {database}")

        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self._conn: Optional[pymysql.connections.Connection] = None
        self._lock = threading.Lock()
        self._init_database()

    def _init_database(self):
        """初始化数据库和表"""
        # 先连接到 MySQL 服务器（不指定数据库）创建数据库
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                charset='utf8mb4',
                connect_timeout=10,
            )
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                conn.commit()
            finally:
                conn.close()
        except pymysql.Error as e:
            logger.error(f"创建数据库失败: {e}")
            raise

        # 连接到指定数据库并创建表
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(self.CREATE_TABLE_SQL)
                cursor.execute(self.CREATE_META_TABLE_SQL)
            conn.commit()

            # Schema 迁移
            self._migrate_schema(conn)

    def _migrate_schema(self, conn):
        """执行 Schema 迁移"""
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT `value` FROM app_meta WHERE `key` = 'schema_version'"
            )
            row = cursor.fetchone()
            current_version = int(row['value']) if row else 1

            if current_version < 2:
                # v1 → v2: 新增 cloud_id 字段
                try:
                    cursor.execute(
                        "ALTER TABLE clipboard_items ADD COLUMN cloud_id BIGINT DEFAULT NULL"
                    )
                    cursor.execute(
                        "CREATE INDEX idx_cloud_id ON clipboard_items(cloud_id)"
                    )
                except pymysql.Error as e:
                    if "Duplicate column name" not in str(e):
                        raise

                cursor.execute(
                    "INSERT INTO app_meta (`key`, `value`) VALUES ('schema_version', '2') "
                    "ON DUPLICATE KEY UPDATE `value` = '2'"
                )
                conn.commit()
                logger.info("MySQL Schema 已迁移到 v2（新增 cloud_id）")

    def _create_connection(self) -> "pymysql.connections.Connection":
        """创建新的 MySQL 连接"""
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )

    @contextmanager
    def get_connection(self):
        """复用持久连接，仅在出错时重建。使用锁保证线程安全。"""
        with self._lock:
            if self._conn is None:
                self._conn = self._create_connection()
            else:
                try:
                    self._conn.ping(reconnect=True)
                except Exception:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = self._create_connection()
            yield self._conn

    def close(self):
        """关闭持久连接，供应用退出时调用"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def execute_with_retry(
        self,
        operation: Callable,
        max_retries: int = 5,
    ) -> Any:
        """带重试的数据库操作"""
        last_error = None
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    result = operation(conn)
                    conn.commit()
                    return result
            except pymysql.OperationalError as e:
                last_error = e
                error_code = e.args[0] if e.args else 0
                # 1205: Lock wait timeout, 1213: Deadlock
                if error_code in (1205, 1213, 2006, 2013):
                    wait_time = (2**attempt) * 0.1 + random.uniform(0, 0.1)
                    logger.warning(
                        f"数据库操作失败，重试 {attempt + 1}/{max_retries}，等待 {wait_time:.2f}s"
                    )
                    time.sleep(wait_time)
                else:
                    raise

        raise Exception(f"数据库操作失败，已重试{max_retries}次: {last_error}")

    def execute_read(self, operation: Callable) -> Any:
        """执行只读操作"""
        with self.get_connection() as conn:
            return operation(conn)

    def check_connection(self) -> bool:
        """检查数据库连接"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"数据库连接检查失败: {e}")
            return False

    @staticmethod
    def test_connection(host: str, port: int, user: str, password: str, database: str = None) -> tuple[bool, str]:
        """
        测试 MySQL 连接
        返回: (成功标志, 消息)
        """
        if not PYMYSQL_AVAILABLE:
            return False, "pymysql 未安装，请运行: pip install pymysql"

        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                charset='utf8mb4',
                connect_timeout=5,
            )
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT VERSION()")
                    version = cursor.fetchone()[0]

                    # 如果指定了数据库，检查是否存在
                    if database:
                        cursor.execute("SHOW DATABASES")
                        databases = [row[0] for row in cursor.fetchall()]
                        db_exists = database in databases
                        if db_exists:
                            return True, f"连接成功！MySQL {version}，数据库 '{database}' 已存在"
                        else:
                            return True, f"连接成功！MySQL {version}，数据库 '{database}' 将被创建"

                    return True, f"连接成功！MySQL {version}"
            finally:
                conn.close()
        except pymysql.Error as e:
            error_code = e.args[0] if e.args else 0
            error_msg = e.args[1] if len(e.args) > 1 else str(e)

            if error_code == 1045:
                return False, "认证失败：用户名或密码错误"
            elif error_code == 2003:
                return False, f"无法连接到 {host}:{port}，请检查主机和端口"
            elif error_code == 1049:
                return False, f"数据库 '{database}' 不存在"
            else:
                return False, f"连接失败: {error_msg}"
        except Exception as e:
            return False, f"连接失败: {str(e)}"
