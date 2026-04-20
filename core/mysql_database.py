import re
import time
import random
import logging
import threading
from typing import Callable, Any
from contextlib import contextmanager

from .base_database import AbstractDatabaseManager

logger = logging.getLogger(__name__)

try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    logger.warning("pymysql 未安装，MySQL 功能不可用")


class MySQLDatabaseManager(AbstractDatabaseManager):
    """MySQL 数据库管理器"""

    # 方言覆盖
    placeholder = "%s"
    is_mysql = True

    SCHEMA_VERSION = 4

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

    CREATE_FILES_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS cloud_files (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        cloud_id BIGINT UNIQUE,
        name VARCHAR(512) NOT NULL,
        original_path TEXT,
        local_path TEXT,
        size_bytes BIGINT NOT NULL DEFAULT 0,
        mime_type VARCHAR(255),
        content_sha256 CHAR(64) NOT NULL,
        mtime BIGINT NOT NULL,
        device_id VARCHAR(32) NOT NULL,
        device_name VARCHAR(255),
        created_at BIGINT NOT NULL,
        is_deleted TINYINT NOT NULL DEFAULT 0,
        sync_state VARCHAR(32) NOT NULL DEFAULT 'pending',
        last_error TEXT,
        bookmark LONGBLOB,
        INDEX idx_files_sync_state (sync_state),
        INDEX idx_files_cloud_id (cloud_id),
        INDEX idx_files_sha (content_sha256)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    CREATE_FILE_PARTS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS cloud_file_upload_parts (
        file_id BIGINT NOT NULL,
        part_number INT NOT NULL,
        etag VARCHAR(128),
        uploaded_at BIGINT,
        PRIMARY KEY (file_id, part_number)
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
        # Why: 原先共享单个 _conn + 全局 _lock，所有读写被串行化，UI
        # 列表查询会阻塞同步线程的写入。PyMySQL 连接本身非线程安全，
        # 改为每线程一份 connection（对齐 SQLite 做法），并发读写互不干扰。
        # _all_conns 仅用于 close() 统一回收，_conns_lock 保护列表自身，
        # 不再对读写加锁。
        self._tls = threading.local()
        self._all_conns: list = []
        self._conns_lock = threading.Lock()
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
                cursor.execute(self.CREATE_FILES_TABLE_SQL)
                cursor.execute(self.CREATE_FILE_PARTS_TABLE_SQL)
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

            if current_version < 3:
                # v2 → v3: 远古版本创建的库可能缺 image_data / image_thumbnail,
                # 对齐 CREATE TABLE 的完整列集, 补齐缺失字段避免写入 1054。
                expected_columns = [
                    ("image_data", "LONGBLOB"),
                    ("image_thumbnail", "MEDIUMBLOB"),
                ]
                for col_name, col_type in expected_columns:
                    try:
                        cursor.execute(
                            f"ALTER TABLE clipboard_items ADD COLUMN {col_name} {col_type}"
                        )
                    except pymysql.Error as e:
                        # 1060 = Duplicate column name, 已存在跳过
                        if "Duplicate column name" not in str(e):
                            raise

                cursor.execute(
                    "INSERT INTO app_meta (`key`, `value`) VALUES ('schema_version', '3') "
                    "ON DUPLICATE KEY UPDATE `value` = '3'"
                )
                conn.commit()
                logger.info("MySQL Schema 已迁移到 v3（补齐 image_data / image_thumbnail）")

            if current_version < 4:
                try:
                    cursor.execute(self.CREATE_FILES_TABLE_SQL)
                    cursor.execute(self.CREATE_FILE_PARTS_TABLE_SQL)
                except pymysql.Error:
                    logger.warning("MySQL 建 cloud_files 表失败", exc_info=True)
                    raise

                cursor.execute(
                    "INSERT INTO app_meta (`key`, `value`) VALUES ('schema_version', '4') "
                    "ON DUPLICATE KEY UPDATE `value` = '4'"
                )
                conn.commit()
                logger.info("MySQL Schema 已迁移到 v4")

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

    # ping 节流间隔：同一线程距上次 ping <PING_INTERVAL_S 直接复用 conn，
    # 断开的连接会在 execute 时抛 OperationalError(2006/2013)，由 execute_with_retry 回捞。
    _PING_INTERVAL_S = 60.0

    def _discard_thread_conn(self, conn) -> None:
        """关闭并从池中移除一个已失效连接；单独封装让 _get_thread_conn 主路径平直。"""
        try:
            conn.close()
        except Exception:
            pass
        with self._conns_lock:
            try:
                self._all_conns.remove(conn)
            except ValueError:
                pass

    def _get_thread_conn(self) -> "pymysql.connections.Connection":
        """返回当前线程独占的 connection；首次访问或连接失效时创建。
        Why: PyMySQL 连接非线程安全；每次都 ping 会给热路径加一次 roundtrip，
        60s 内复用 conn、跳过 ping，依赖 execute_with_retry 的 2006/2013 重试兜底。
        """
        conn = getattr(self._tls, "conn", None)
        if conn is not None:
            now = time.monotonic()
            last_ping = getattr(self._tls, "last_ping_ts", 0.0)
            if now - last_ping < self._PING_INTERVAL_S:
                return conn
            try:
                conn.ping(reconnect=True)
                self._tls.last_ping_ts = now
                return conn
            except Exception:
                # ping 失败：清理旧连接后 fallthrough 创建新连接
                self._discard_thread_conn(conn)

        new_conn = self._create_connection()
        self._tls.conn = new_conn
        self._tls.last_ping_ts = time.monotonic()
        with self._conns_lock:
            self._all_conns.append(new_conn)
        return new_conn

    @contextmanager
    def get_connection(self):
        """yield 当前线程独占的 connection（无全局锁，允许并发读写）。"""
        yield self._get_thread_conn()

    def close(self):
        """关闭所有线程的 connection，供应用退出时调用。"""
        with self._conns_lock:
            conns = list(self._all_conns)
            self._all_conns.clear()
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        self._tls = threading.local()

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
        """执行只读操作。
        Why: 每线程连接模型下，读不再与写互斥（不同线程用不同 MySQL 会话），
        operation 仍须在返回前把结果实体化（fetchall/list），避免返回
        游离 cursor 后被其他调用复用同一连接的 cursor 打断。

        Why commit: MySQL 默认 REPEATABLE READ 隔离级别下，同一连接上未显式
        结束的只读事务会持续持有一个一致性快照，后续读会看到陈旧数据。
        读完显式 commit 结束事务，下次读取时 MySQL 会开启新快照。
        """
        with self.get_connection() as conn:
            try:
                return operation(conn)
            finally:
                try:
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

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

    # ========== 方言透明的 SQL 执行（PyMySQL 用 %s 占位符，需 cursor 调用） ==========

    @staticmethod
    def _to_mysql(sql: str) -> str:
        # Repository 用 ? 写 SQL，这里批量替换为 %s
        return sql.replace("?", "%s") if "?" in sql else sql

    def execute_write(self, conn, sql: str, params: tuple = ()):
        with conn.cursor() as cursor:
            cursor.execute(self._to_mysql(sql), params)
            return cursor.rowcount, cursor.lastrowid

    def fetch_one(self, conn, sql: str, params: tuple = ()):
        with conn.cursor() as cursor:
            cursor.execute(self._to_mysql(sql), params)
            return cursor.fetchone()

    def fetch_all(self, conn, sql: str, params: tuple = ()) -> list:
        with conn.cursor() as cursor:
            cursor.execute(self._to_mysql(sql), params)
            return cursor.fetchall()

    def execute_many(self, conn, sql: str, data: list):
        with conn.cursor() as cursor:
            cursor.executemany(self._to_mysql(sql), data)

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
                return False, f"MySQL 认证失败：用户名或密码错误（user={user}@{host}:{port}）"
            elif error_code == 2003:
                return False, f"MySQL 无法连接到 {host}:{port}，请检查主机和端口"
            elif error_code == 1049:
                return False, f"MySQL 数据库 '{database}' 不存在（{host}:{port}）"
            elif error_code == 1044:
                return False, f"MySQL 用户 '{user}' 对数据库 '{database}' 没有访问权限"
            else:
                return False, f"MySQL 连接失败: {error_msg}"
        except Exception as e:
            return False, f"MySQL 连接失败: {str(e)}"

    # website/api 公共库独有的标志表。命中任意一张即判定为"这是 api 的公共库"，
    # 客户端个人 MySQL 里不会出现这些表。
    # Why: 历史上客户端和 api 共用过同一个库, `clipboard_items` / `cloud_files` /
    #      `cloud_file_upload_parts` 三张同名表 schema 不一致导致 "Unknown column" 报错。
    API_RESERVED_TABLES = ("subscriptions", "api_keys", "schema_migrations")

    @staticmethod
    def detect_api_reserved_tables(
        host: str, port: int, user: str, password: str, database: str
    ) -> list:
        """
        检测目标库是否包含 website/api 专用的标志表。
        返回: 命中的表名列表（为空代表这是一个干净的个人库）。
        """
        if not PYMYSQL_AVAILABLE or not database:
            return []

        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset='utf8mb4',
                connect_timeout=5,
            )
        except pymysql.Error:
            # 连接不上就别管了, 让上层的 test_connection 给出准确报错。
            return []

        try:
            hits = []
            with conn.cursor() as cursor:
                for tbl in MySQLDatabaseManager.API_RESERVED_TABLES:
                    cursor.execute("SHOW TABLES LIKE %s", (tbl,))
                    if cursor.fetchone():
                        hits.append(tbl)
            return hits
        finally:
            conn.close()
