import sqlite3
import time
import random
import logging
from pathlib import Path
from typing import Optional, Callable, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    SCHEMA_VERSION = 1

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
        self._ensure_db_directory()
        self._init_database()

    def _ensure_db_directory(self):
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _init_database(self):
        with self.get_connection() as conn:
            # 创建主表和索引
            conn.executescript(self.CREATE_TABLE_SQL)

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

    @contextmanager
    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        try:
            # 配置WAL模式和其他优化
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB缓存
            conn.execute("PRAGMA temp_store=MEMORY")
            yield conn
        finally:
            conn.close()

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
                    # 指数退避 + 随机抖动
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
