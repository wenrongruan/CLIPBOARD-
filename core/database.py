import sqlite3
import time
import random
import logging
import threading
import weakref
from pathlib import Path
from typing import Optional, Callable, Any
from contextlib import contextmanager

from .base_database import AbstractDatabaseManager

logger = logging.getLogger(__name__)


class DatabaseManager(AbstractDatabaseManager):
    SCHEMA_VERSION = 4

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS clipboard_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content_type TEXT NOT NULL CHECK(content_type IN ('text', 'image')),
        text_content TEXT,
        image_data BLOB,
        image_thumbnail BLOB,
        content_hash TEXT NOT NULL UNIQUE,
        preview TEXT,
        device_id TEXT NOT NULL,
        device_name TEXT,
        created_at INTEGER NOT NULL,
        is_starred INTEGER DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_created_at ON clipboard_items(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_content_type ON clipboard_items(content_type);
    CREATE INDEX IF NOT EXISTS idx_device_id ON clipboard_items(device_id);
    CREATE INDEX IF NOT EXISTS idx_content_hash ON clipboard_items(content_hash);

    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS cloud_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cloud_id INTEGER UNIQUE,
        name TEXT NOT NULL,
        original_path TEXT,
        local_path TEXT,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        mime_type TEXT,
        content_sha256 TEXT NOT NULL,
        mtime INTEGER NOT NULL,
        device_id TEXT NOT NULL,
        device_name TEXT,
        created_at INTEGER NOT NULL,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        sync_state TEXT NOT NULL DEFAULT 'pending',
        last_error TEXT,
        bookmark BLOB
    );

    CREATE INDEX IF NOT EXISTS idx_files_sync_state ON cloud_files(sync_state);
    CREATE INDEX IF NOT EXISTS idx_files_cloud_id ON cloud_files(cloud_id);
    CREATE UNIQUE INDEX IF NOT EXISTS uq_files_sha_not_deleted
        ON cloud_files(content_sha256) WHERE is_deleted = 0;

    CREATE TABLE IF NOT EXISTS cloud_file_upload_parts (
        file_id INTEGER NOT NULL,
        part_number INTEGER NOT NULL,
        etag TEXT,
        uploaded_at INTEGER,
        PRIMARY KEY (file_id, part_number),
        FOREIGN KEY (file_id) REFERENCES cloud_files(id) ON DELETE CASCADE
    );
    """

    CREATE_FTS_SQL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS clipboard_fts USING fts5(
        text_content,
        preview,
        content='clipboard_items',
        content_rowid='id'
    );

    CREATE TRIGGER IF NOT EXISTS clipboard_ai AFTER INSERT ON clipboard_items BEGIN
        INSERT INTO clipboard_fts(rowid, text_content, preview)
        VALUES (new.id, new.text_content, new.preview);
    END;

    CREATE TRIGGER IF NOT EXISTS clipboard_ad AFTER DELETE ON clipboard_items BEGIN
        INSERT INTO clipboard_fts(clipboard_fts, rowid, text_content, preview)
        VALUES ('delete', old.id, old.text_content, old.preview);
    END;

    CREATE TRIGGER IF NOT EXISTS clipboard_au AFTER UPDATE ON clipboard_items BEGIN
        INSERT INTO clipboard_fts(clipboard_fts, rowid, text_content, preview)
        VALUES ('delete', old.id, old.text_content, old.preview);
        INSERT INTO clipboard_fts(rowid, text_content, preview)
        VALUES (new.id, new.text_content, new.preview);
    END;
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        # Why: SQLite WAL 模式允许「多读 + 单写」并发，但前提是每个 reader
        # 用自己的 connection。原先全局共享一条 connection + 全局锁，把
        # 所有读写串行化掉了，UI 线程读列表会被同步线程的写入挡住。
        # 改为每线程一份 connection；写操作在 SQLite 引擎层仍是串行
        # （busy_timeout=30s + execute_with_retry 处理 BUSY）。
        self._tls = threading.local()
        self._all_conns: list[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        self._ensure_db_directory()
        self._init_database()

    def _ensure_db_directory(self):
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _init_database(self):
        with self.get_connection() as conn:
            # 创建主表和索引
            conn.executescript(self.CREATE_TABLE_SQL)

            # 添加复合索引用于同步查询优化
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_id_device ON clipboard_items(id, device_id)"
            )

            # Schema 迁移: v1 → v2，新增 cloud_id 字段
            self._migrate_schema(conn)

            # 检查是否需要创建FTS表
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='clipboard_fts'"
            )
            if cursor.fetchone() is None:
                try:
                    conn.executescript(self.CREATE_FTS_SQL)
                except sqlite3.OperationalError as e:
                    # FTS5可能不可用，记录警告但继续
                    logger.warning(f"FTS5不可用，搜索功能将使用LIKE: {e}")

            conn.commit()

    def _migrate_schema(self, conn):
        """执行 Schema 迁移"""
        # 检查当前版本
        cursor = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'schema_version'"
        )
        row = cursor.fetchone()
        current_version = int(row[0]) if row else 1

        if current_version < 2:
            # v1 → v2: 新增 cloud_id 字段
            try:
                conn.execute(
                    "ALTER TABLE clipboard_items ADD COLUMN cloud_id INTEGER DEFAULT NULL"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cloud_id ON clipboard_items(cloud_id)"
                )
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise

            conn.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('schema_version', '2')"
            )
            conn.commit()
            logger.info("数据库 Schema 已迁移到 v2（新增 cloud_id）")

        if current_version < 4:
            # CREATE_TABLE_SQL 在 _init_database 已用 IF NOT EXISTS 建表，此处
            # 兜底一次是为了 MySQL 兼容层的迁移路径能复用同一份 DDL。
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cloud_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cloud_id INTEGER UNIQUE,
                    name TEXT NOT NULL,
                    original_path TEXT,
                    local_path TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    mime_type TEXT,
                    content_sha256 TEXT NOT NULL,
                    mtime INTEGER NOT NULL,
                    device_id TEXT NOT NULL,
                    device_name TEXT,
                    created_at INTEGER NOT NULL,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    sync_state TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT,
                    bookmark BLOB
                );
                CREATE INDEX IF NOT EXISTS idx_files_sync_state ON cloud_files(sync_state);
                CREATE INDEX IF NOT EXISTS idx_files_cloud_id ON cloud_files(cloud_id);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_files_sha_not_deleted
                    ON cloud_files(content_sha256) WHERE is_deleted = 0;
                CREATE TABLE IF NOT EXISTS cloud_file_upload_parts (
                    file_id INTEGER NOT NULL,
                    part_number INTEGER NOT NULL,
                    etag TEXT,
                    uploaded_at INTEGER,
                    PRIMARY KEY (file_id, part_number),
                    FOREIGN KEY (file_id) REFERENCES cloud_files(id) ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('schema_version', '4')"
            )
            conn.commit()
            logger.info("数据库 Schema 已迁移到 v4")

    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接并配置 PRAGMA"""
        # Why: UI 线程的 busy_timeout 必须短。C 层 sqlite3_step 拿不到写锁时会
        # 原地阻塞整整 busy_timeout 毫秒，期间整个事件循环冻结；Python 层的
        # execute_with_retry 只能在返回 BUSY 之后才接管。后台同步/写入线程可以
        # 保留长超时，用 30s 吃掉偶发拥塞。
        is_ui = self._is_ui_thread()
        busy_ms = 500 if is_ui else 10000
        py_timeout = max(busy_ms / 1000.0, 5.0)

        conn = sqlite3.connect(
            self.db_path,
            timeout=py_timeout,
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={busy_ms}")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB缓存
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    @staticmethod
    def _is_ui_thread() -> bool:
        """当前是否为 Qt 主线程。无 Qt 环境（如单测）返回 False。"""
        try:
            from PySide6.QtCore import QCoreApplication, QThread
            app = QCoreApplication.instance()
            if app is None:
                return False
            return QThread.currentThread() is app.thread()
        except Exception:
            return False

    def _get_thread_conn(self) -> sqlite3.Connection:
        """返回当前线程的 connection；首次访问时创建。
        SQLite 是本地文件，连接稳定后不会被动断开，故省去每次取用前的 SELECT 1
        健康检查；操作失败由 execute_with_retry 处理 BUSY，连接级异常向上传播。"""
        conn = getattr(self._tls, "conn", None)
        if conn is not None:
            return conn
        new_conn = self._create_connection()
        self._tls.conn = new_conn
        with self._conns_lock:
            self._all_conns.append(new_conn)
        # 线程结束时自动回收：避免短生命周期工作线程泄漏 sqlite 连接/TLS 文件句柄
        weakref.finalize(
            threading.current_thread(), self._finalize_thread_conn, new_conn
        )
        return new_conn

    def _finalize_thread_conn(self, conn: sqlite3.Connection) -> None:
        """线程终止时回收该线程 connection 并从全局列表摘除。"""
        with self._conns_lock:
            try:
                self._all_conns.remove(conn)
            except ValueError:
                pass
        try:
            conn.close()
        except Exception:
            # 线程终结阶段关闭连接失败无关紧要，记 debug 便于排查
            logger.debug("close conn failed", exc_info=True)

    @contextmanager
    def get_connection(self) -> sqlite3.Connection:
        """yield 当前线程独占的 connection（无全局锁，允许并发读）。"""
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
        operation: Callable[[sqlite3.Connection], Any],
        max_retries: int = 5,
    ) -> Any:
        last_error = None
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    result = operation(conn)
                    conn.commit()
                    return result
            except sqlite3.OperationalError as e:
                last_error = e
                error_msg = str(e).lower()
                if "database is locked" in error_msg or "busy" in error_msg:
                    wait_time = (2**attempt) * 0.1 + random.uniform(0, 0.1)
                    logger.warning(
                        f"数据库锁定，重试 {attempt + 1}/{max_retries}，等待 {wait_time:.2f}s"
                    )
                    time.sleep(wait_time)
                else:
                    raise

        raise Exception(f"数据库操作失败，已重试{max_retries}次: {last_error}")

    def execute_read(
        self, operation: Callable[[sqlite3.Connection], Any]
    ) -> Any:
        with self.get_connection() as conn:
            return operation(conn)

    def check_connection(self) -> bool:
        try:
            with self.get_connection() as conn:
                conn.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"数据库连接检查失败: {e}")
            return False

    # ========== 方言透明的 SQL 执行（sqlite3.Connection 原生支持 ?） ==========

    def execute_write(self, conn, sql: str, params: tuple = ()):
        cursor = conn.execute(sql, params)
        return cursor.rowcount, cursor.lastrowid

    def fetch_one(self, conn, sql: str, params: tuple = ()):
        return conn.execute(sql, params).fetchone()

    def fetch_all(self, conn, sql: str, params: tuple = ()) -> list:
        return conn.execute(sql, params).fetchall()

    def execute_many(self, conn, sql: str, data: list):
        conn.executemany(sql, data)
