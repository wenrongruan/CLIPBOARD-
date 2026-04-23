"""数据库迁移框架（客户端本地 SQLite / 可选本地 MySQL）。

用法：
    from core.db_migrations import run_migrations
    run_migrations(conn, Path("sql/migrations"), dialect="sqlite", db_path=db_path)

约定：
- 迁移文件放在 ``sql/migrations/*.sql``，按文件名字典序执行。
- 每个迁移必须幂等（CREATE TABLE IF NOT EXISTS、防御式 ALTER 等）。
- 不支持 down migration。
- MySQL 方言要求：每条语句以 ``;`` 结尾且不跨行分号（简单 split，不处理嵌入分号字符串）。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DIALECT_SQLITE = "sqlite"
_DIALECT_MYSQL = "mysql"


class DatabaseMigrator:
    """按字典序执行 migrations_dir 下的 *.sql 文件，并记录到 schema_migrations。"""

    def __init__(
        self,
        conn,
        migrations_dir: Path,
        sql_dialect: str,
        db_path: Optional[Path] = None,
    ) -> None:
        if sql_dialect not in (_DIALECT_SQLITE, _DIALECT_MYSQL):
            raise ValueError(f"不支持的 sql_dialect: {sql_dialect}")
        self.conn = conn
        self.migrations_dir = Path(migrations_dir)
        self.dialect = sql_dialect
        self.db_path = Path(db_path) if db_path else None

    # ------------------------------------------------------------------ helpers

    def ensure_schema_migrations_table(self) -> None:
        """幂等建表。SQLite / MySQL 语法兼容子集。"""
        if self.dialect == _DIALECT_SQLITE:
            ddl = (
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " version TEXT NOT NULL UNIQUE,"
                " applied_at INTEGER NOT NULL"
                ")"
            )
        else:
            ddl = (
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,"
                " version VARCHAR(255) NOT NULL UNIQUE,"
                " applied_at BIGINT NOT NULL"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            )
        cur = self.conn.cursor()
        cur.execute(ddl)
        self.conn.commit()

    def get_applied_versions(self) -> set:
        cur = self.conn.cursor()
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}

    def discover_pending(self) -> list:
        if not self.migrations_dir.exists():
            logger.debug("迁移目录不存在: %s", self.migrations_dir)
            return []
        applied = self.get_applied_versions()
        files = sorted(self.migrations_dir.glob("*.sql"), key=lambda p: p.name)
        return [p for p in files if p.stem not in applied]

    # -------------------------------------------------------------- execution

    def _backup_sqlite(self) -> None:
        if self.dialect != _DIALECT_SQLITE or not self.db_path:
            return
        if not self.db_path.exists():
            return
        bak = self.db_path.with_suffix(self.db_path.suffix + ".bak")
        try:
            shutil.copy2(self.db_path, bak)
            logger.info("迁移前已备份 SQLite 库到 %s", bak)
        except OSError as exc:
            logger.warning("备份 SQLite 库失败: %s", exc)

    def _apply_sqlite(self, sql_text: str) -> None:
        """SQLite 用 executescript，但为了容忍 duplicate column name 错误，
        需要逐条 execute。简单按分号 split。"""
        import sqlite3

        cur = self.conn.cursor()
        for stmt in _split_statements(sql_text):
            try:
                cur.execute(stmt)
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if "duplicate column name" in msg:
                    logger.info("跳过重复列（幂等）：%s", stmt[:80])
                    continue
                raise

    def _apply_mysql(self, sql_text: str) -> None:
        cur = self.conn.cursor()
        for stmt in _split_statements(sql_text):
            try:
                cur.execute(stmt)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if "duplicate column" in msg or "1060" in msg:
                    logger.info("跳过重复列（幂等）：%s", stmt[:80])
                    continue
                raise

    def apply_all(self) -> list:
        """返回本次实际执行的 version 列表。"""
        self.ensure_schema_migrations_table()
        pending = self.discover_pending()
        if not pending:
            return []

        self._backup_sqlite()
        import time

        executed = []
        for path in pending:
            version = path.stem
            sql_text = path.read_text(encoding="utf-8")
            logger.info("应用迁移 %s", version)
            try:
                if self.dialect == _DIALECT_SQLITE:
                    self._apply_sqlite(sql_text)
                else:
                    self._apply_mysql(sql_text)
                cur = self.conn.cursor()
                cur.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)"
                    if self.dialect == _DIALECT_SQLITE
                    else "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
                    (version, int(time.time() * 1000)),
                )
                self.conn.commit()
                executed.append(version)
            except Exception:
                self.conn.rollback()
                logger.exception("迁移 %s 失败，已回滚", version)
                raise
        return executed


# ---------------------------------------------------------------------- utils


def _split_statements(sql_text: str) -> list:
    """按分号 split 并剥离纯注释/空行；不处理嵌入分号字符串（约定不用）。"""
    out = []
    buf = []
    for raw_line in sql_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def run_migrations(
    conn,
    migrations_dir: Path,
    dialect: str,
    db_path: Optional[Path] = None,
) -> list:
    """模块级入口，返回实际执行的 version 列表。"""
    migrator = DatabaseMigrator(conn, migrations_dir, dialect, db_path=db_path)
    return migrator.apply_all()
