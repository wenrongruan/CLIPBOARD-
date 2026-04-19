"""DatabaseManager 测试 — 使用内存数据库"""

import sys
import os
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    """创建临时数据库"""
    db_path = str(tmp_path / "test.db")
    manager = DatabaseManager(db_path)
    yield manager
    manager.close()


class TestDatabaseManager:
    def test_init_creates_tables(self, db):
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='clipboard_items'"
            )
            assert cursor.fetchone() is not None

    def test_init_creates_app_meta(self, db):
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='app_meta'"
            )
            assert cursor.fetchone() is not None

    def test_schema_version(self, db):
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT value FROM app_meta WHERE key = 'schema_version'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert int(row[0]) == DatabaseManager.SCHEMA_VERSION

    def test_connection_reuse(self, db):
        """持久连接应复用同一个对象"""
        with db.get_connection() as conn1:
            id1 = id(conn1)
        with db.get_connection() as conn2:
            id2 = id(conn2)
        assert id1 == id2

    def test_check_connection(self, db):
        assert db.check_connection() is True

    def test_close_and_reconnect(self, db):
        db.close()
        # 关闭后重新获取连接应自动重建
        assert db.check_connection() is True

    def test_execute_with_retry(self, db):
        def op(conn):
            conn.execute(
                "INSERT INTO clipboard_items "
                "(content_type, text_content, content_hash, preview, device_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("text", "hello", "hash1", "hello", "dev1", 1000),
            )
            cursor = conn.execute("SELECT COUNT(*) FROM clipboard_items")
            return cursor.fetchone()[0]

        count = db.execute_with_retry(op)
        assert count == 1

    def test_execute_read(self, db):
        def read_op(conn):
            cursor = conn.execute("SELECT COUNT(*) FROM clipboard_items")
            return cursor.fetchone()[0]

        count = db.execute_read(read_op)
        assert count == 0

    def test_wal_mode(self, db):
        with db.get_connection() as conn:
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == "wal"

    def test_thread_safety(self, db):
        """多线程并发写入不应死锁"""
        errors = []

        def writer(i):
            try:
                def op(conn):
                    conn.execute(
                        "INSERT INTO clipboard_items "
                        "(content_type, text_content, content_hash, preview, device_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        ("text", f"item_{i}", f"hash_{i}", f"item_{i}", "dev1", 1000 + i),
                    )
                db.execute_with_retry(op)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        with db.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM clipboard_items")
            assert cursor.fetchone()[0] == 10
