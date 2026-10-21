"""MySQLDatabaseManager schema 集成测试。

需要一个真实 MySQL：设置下列环境变量后才运行，否则整体 skip。
    TEST_MYSQL_HOST / TEST_MYSQL_USER / TEST_MYSQL_PASSWORD
    TEST_MYSQL_DATABASE  指向一个可供测试写入的数据库
    TEST_MYSQL_PORT      可选，默认 3306

测试只做幂等建表校验（依赖 CREATE TABLE IF NOT EXISTS），不删除任何数据。
"""

import os

import pytest

_HOST = os.environ.get("TEST_MYSQL_HOST")
_USER = os.environ.get("TEST_MYSQL_USER")
_PASSWORD = os.environ.get("TEST_MYSQL_PASSWORD")
_DATABASE = os.environ.get("TEST_MYSQL_DATABASE")
_PORT = int(os.environ.get("TEST_MYSQL_PORT", "3306"))

pytestmark = pytest.mark.skipif(
    not (_HOST and _USER and _PASSWORD and _DATABASE),
    reason="需要 TEST_MYSQL_HOST/USER/PASSWORD/DATABASE 指向真实 MySQL",
)


def test_mysql_init_creates_v34_team_tables():
    """复现 user-reported bug：MySQL 模式下团队功能建表缺失，
    create_space 报 (1146, "Table '<db>.spaces' doesn't exist")。

    MySQLDatabaseManager 初始化后，v3.4 的团队 / 标签 / 分享本地表都应存在。
    """
    import pymysql
    from core.mysql_database import MySQLDatabaseManager

    db = MySQLDatabaseManager(_HOST, _PORT, _USER, _PASSWORD, _DATABASE)
    try:
        conn = pymysql.connect(
            host=_HOST, port=_PORT, user=_USER, password=_PASSWORD,
            database=_DATABASE, charset="utf8mb4", connect_timeout=10,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                tables = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()
    finally:
        db.close()

    for required in (
        "spaces", "space_members", "tag_definitions",
        "clipboard_tags", "share_links",
    ):
        assert required in tables, f"缺少表 {required}；实际表：{sorted(tables)}"
