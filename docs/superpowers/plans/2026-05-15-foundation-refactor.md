# 公共底盘重构 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变任何用户可见行为、不破坏任何外部 import 路径、不动持久化产物的前提下，把 6 个热点文件（main_window 1541 行 / i18n 1482 行 / settings_dialog 1414 行 / cloud_api 990 行 / repository 983 行 / plugin_manager 654 行）切分到清晰的边界后面，为插件 / 云同步 / 团队空间 / AI 四个未来方向铺路。

**Architecture:** 7 个支柱按顺序在本地分支 `refactor/foundation` 上推进：(1) `core/app_context.py` ServiceRegistry，(2) `core/db/` 三层 DAO/Query/SyncState + Repository facade，(3) `core/cloud/` 四个 domain client + CloudAPIClient facade，(4) `i18n_strings/` 字符串迁出 + i18n.py shim，(5) `ui/settings/` 按 Tab 拆分 + settings_dialog shim，(6) `ui/controllers/` 抽 4 个 controller + MainWindow 退化为壳，(7) `core/plugin_extension_points.py` 抽 ExtensionPointRegistry。最终一次性 squash 到 main。

**Tech Stack:** PySide6 6.x、Python 3.10+、pytest、SQLite (pysqlite3 + FTS5)、pymysql（可选）。

**Spec 参考:** `docs/superpowers/specs/2026-05-15-foundation-refactor-design.md`

---

## File Structure

每个文件的职责（与 spec §3.1 一致）：

```
新建：
  core/app_context.py                  ServiceRegistry：bootstrap / current / shutdown
  core/db/__init__.py                  空 package marker
  core/db/clipboard_dao.py             CRUD + tags + meta + cleanup
  core/db/clipboard_query.py           filter clauses / regex / search / timeline
  core/db/sync_state_dao.py            cloud_id 状态、unsynced 查询
  core/cloud/__init__.py               空 package marker
  core/cloud/http.py                   HttpClient（base_url / token / _request）
  core/cloud/auth_client.py            login / register / verify / refresh / logout
  core/cloud/sync_client.py            item 上传 / 拉取 / 星标
  core/cloud/files_client.py           文件上传 / 多段 / 下载 / 去重
  core/cloud/spaces_client.py          团队空间相关
  core/plugin_extension_points.py      ExtensionPointRegistry
  i18n_strings/__init__.py             load_all() -> dict
  i18n_strings/main.py                 主界面字符串
  i18n_strings/settings.py             设置弹窗字符串
  i18n_strings/cloud.py                登录/同步字符串
  i18n_strings/plugins.py              插件菜单/错误字符串
  i18n_strings/misc.py                 onboarding/share/通用字符串
  ui/controllers/__init__.py           空 package marker
  ui/controllers/clipboard_list_controller.py
  ui/controllers/item_action_controller.py
  ui/controllers/plugin_action_controller.py
  ui/controllers/cloud_lifecycle_controller.py
  ui/settings/__init__.py              re-export SettingsDialog
  ui/settings/settings_dialog.py       QTabWidget 壳
  ui/settings/general_tab.py
  ui/settings/sync_tab.py
  ui/settings/cloud_tab.py
  ui/settings/plugins_tab.py
  ui/settings/advanced_tab.py
  tests/test_app_context.py
  tests/test_clipboard_dao.py
  tests/test_clipboard_query.py
  tests/test_sync_state_dao.py
  tests/test_cloud_api_facade.py
  tests/test_cloud_api_facade_completeness.py
  tests/test_extension_points.py
  tests/test_i18n_completeness.py
  tests/test_controllers_list.py
  tests/test_controllers_item_action.py
  tests/test_controllers_plugin.py
  tests/test_controllers_cloud_lifecycle.py
  tests/test_settings_tabs_smoke.py

改造：
  core/repository.py                   退化为 Facade（≤200 行）
  core/cloud_api.py                    退化为 Facade（≤200 行）
  core/plugin_manager.py               精简，注入 ExtensionPointRegistry
  i18n.py                              退化为 shim（≤100 行）
  ui/main_window.py                    退化为壳 + 信号路由（≤350 行）
  ui/settings_dialog.py                退化为 re-export shim（≤30 行）
  main.py                              改为通过 AppContext 装配
```

**不变量（每个 phase 结束前必须仍然满足）：**
1. `from i18n import t, set_language, get_language` 可用
2. `from core.repository import ClipboardRepository` 可用，全部 public 方法签名不变
3. `from core.cloud_api import CloudAPIClient, get_cloud_client` 可用，全部 public 方法签名不变
4. `from core.plugin_manager import PluginManager` 可用
5. `from ui.settings_dialog import SettingsDialog` 可用
6. 现有 13 个测试文件**零修改**全绿

---

## Pre-Flight

- [ ] **Step 0.1: 创建工作分支**

```bash
cd "E:/python/共享剪贴板/CLIPBOARD-"
git checkout -b refactor/foundation
```

- [ ] **Step 0.2: 跑一次完整测试，确认起点全绿**

```bash
pytest -q
```

Expected: 13 个测试文件全绿。如果有失败，**STOP**，先排查后再开工。

- [ ] **Step 0.3: 记录起点行数与启动时间基线**

```bash
wc -l ui/main_window.py i18n.py ui/settings_dialog.py core/cloud_api.py core/repository.py core/plugin_manager.py
python -c "import time; t=time.time(); import main; print('import-time:', time.time()-t)" 2>/dev/null || true
```

把数字记到本地笔记，最后对比。

---

## Phase 1: AppContext（ServiceRegistry）

**目标：** 引入 `core/app_context.py` 作为唯一的 service 装配点。本阶段**不要求**所有调用方迁过来，只要 `main.py` 和 `MainWindow` 走 ctx 即可；其他模块继续可以通过老路径取（向后兼容）。

### Task 1.1: 写 AppContext 单测

**Files:**
- Create: `tests/test_app_context.py`

- [ ] **Step 1.1.1: 写测试**

```python
# tests/test_app_context.py
import pytest
from core.app_context import AppContext


def test_bootstrap_returns_context_with_all_services(tmp_path, monkeypatch):
    """bootstrap 后所有声明的 service 字段都不为 None。"""
    # 把配置/数据目录指向 tmp，避免污染真实用户数据
    monkeypatch.setenv("SHARED_CLIPBOARD_CONFIG_DIR", str(tmp_path))
    ctx = AppContext.bootstrap()
    try:
        assert ctx.db is not None
        assert ctx.repository is not None
        assert ctx.clipboard_monitor is not None
        assert ctx.sync_service is not None
        assert ctx.cloud_api is not None
        assert ctx.cloud_sync_service is not None
        assert ctx.file_sync_service is not None
        assert ctx.entitlement_service is not None
        assert ctx.space_service is not None
        assert ctx.tag_service is not None
        assert ctx.share_service is not None
        assert ctx.plugin_manager is not None
    finally:
        ctx.shutdown()


def test_current_returns_bootstrapped_context(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_CLIPBOARD_CONFIG_DIR", str(tmp_path))
    ctx = AppContext.bootstrap()
    try:
        assert AppContext.current() is ctx
    finally:
        ctx.shutdown()


def test_current_raises_before_bootstrap():
    AppContext._instance = None  # 强制清空
    with pytest.raises(RuntimeError):
        AppContext.current()


def test_shutdown_clears_current(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_CLIPBOARD_CONFIG_DIR", str(tmp_path))
    ctx = AppContext.bootstrap()
    ctx.shutdown()
    AppContext._instance = None  # 防止后续测试串扰
```

- [ ] **Step 1.1.2: 跑测试，确认失败**

Run: `pytest tests/test_app_context.py -v`
Expected: ImportError 或 AttributeError（AppContext 还不存在）。

### Task 1.2: 实现 AppContext

**Files:**
- Create: `core/app_context.py`

- [ ] **Step 1.2.1: 写 AppContext 实现**

```python
# core/app_context.py
"""应用装配层（ServiceRegistry）。

bootstrap() 在 main 线程一次性装配所有 service；构造完即视为 immutable。
所有 UI / controller / 旧的全局取值入口（如 get_cloud_client）都从这里取。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class AppContext:
    # 类级单例引用（非实例字段，重置时显式赋值）
    _instance: "Optional[AppContext]" = None

    def __init__(self):
        # 实例字段，bootstrap 中填值
        self.db = None
        self.repository = None
        self.clipboard_monitor = None
        self.sync_service = None
        self.cloud_api = None
        self.cloud_sync_service = None
        self.file_sync_service = None
        self.entitlement_service = None
        self.space_service = None
        self.tag_service = None
        self.share_service = None
        self.plugin_manager = None
        self.extension_points = None  # 在 Phase 7 才填
        self._lock = threading.Lock()

    @classmethod
    def bootstrap(cls) -> "AppContext":
        """一次性装配所有 service。重复调用直接返回已有实例。"""
        if cls._instance is not None:
            return cls._instance

        from core.db_factory import create_database_manager
        from core.repository import ClipboardRepository
        from core.clipboard_monitor import ClipboardMonitor
        from core.sync_service import SyncService
        from core.cloud_api import CloudAPIClient
        from core.cloud_sync_service import CloudSyncService
        from core.file_sync_service import FileSyncService
        from core.entitlement_service import EntitlementService
        from core.space_service import SpaceService
        from core.tag_service import TagService
        from core.share_service import ShareService
        from core.plugin_manager import PluginManager

        ctx = cls()
        ctx.db = create_database_manager()
        ctx.repository = ClipboardRepository(ctx.db)
        ctx.clipboard_monitor = ClipboardMonitor(ctx.repository)
        ctx.sync_service = SyncService(ctx.repository)
        ctx.cloud_api = CloudAPIClient()
        ctx.cloud_sync_service = CloudSyncService(ctx.repository, ctx.cloud_api)
        ctx.file_sync_service = FileSyncService(ctx.repository, ctx.cloud_api)
        ctx.entitlement_service = EntitlementService(ctx.cloud_api)
        ctx.space_service = SpaceService(ctx.db)
        ctx.tag_service = TagService(ctx.db)
        ctx.share_service = ShareService(ctx.repository, ctx.cloud_api)
        ctx.plugin_manager = PluginManager()

        cls._instance = ctx
        logger.info("AppContext bootstrapped")
        return ctx

    @classmethod
    def current(cls) -> "AppContext":
        if cls._instance is None:
            raise RuntimeError("AppContext.bootstrap() has not been called")
        return cls._instance

    def shutdown(self) -> None:
        with self._lock:
            try:
                if self.clipboard_monitor:
                    try:
                        self.clipboard_monitor.stop()
                    except Exception:
                        logger.exception("clipboard_monitor.stop() 异常")
                if self.plugin_manager:
                    try:
                        self.plugin_manager.shutdown()
                    except Exception:
                        logger.exception("plugin_manager.shutdown() 异常")
                if self.db:
                    try:
                        self.db.close()
                    except Exception:
                        logger.exception("db.close() 异常")
            finally:
                AppContext._instance = None
                logger.info("AppContext shutdown")
```

**注意：** 每个 service 的构造签名要核对实际代码：
- 打开 `core/clipboard_monitor.py / core/sync_service.py / core/cloud_sync_service.py / core/file_sync_service.py / core/entitlement_service.py / core/space_service.py / core/tag_service.py / core/share_service.py / core/plugin_manager.py` 的 `__init__` 行
- 如果某个 service 当前构造签名不匹配（例如 SpaceService 现在不接受 db_manager），按现有签名调整 AppContext 里的传参，**不要改 service 本身**
- 如果某个 service 之前是单例（如 `get_cloud_client()`），AppContext.bootstrap 要确保 cloud_api 实例是同一个，避免双实例

- [ ] **Step 1.2.2: 跑 AppContext 测试，全绿**

Run: `pytest tests/test_app_context.py -v`
Expected: 4 个测试全 PASS。

如果某个 service 启动失败（例如缺数据库 schema），用 `monkeypatch` 在测试里 patch `create_database_manager` 返回内存 SQLite，或在 conftest 里准备 fixture。

### Task 1.3: 让 cloud_api 全局入口走 AppContext

**Files:**
- Modify: `core/cloud_api.py`（只改 `get_cloud_client` 函数，不动 Class）

- [ ] **Step 1.3.1: 修改 get_cloud_client**

打开 `core/cloud_api.py`，找到 `def get_cloud_client()`（用 Grep 定位）。改为：

```python
def get_cloud_client():
    """向后兼容入口。优先走 AppContext，否则按旧逻辑构造一次。"""
    try:
        from core.app_context import AppContext
        return AppContext.current().cloud_api
    except RuntimeError:
        # AppContext 还没 bootstrap（测试或工具脚本场景），退回旧行为
        global _GLOBAL_CLIENT
        if _GLOBAL_CLIENT is None:
            _GLOBAL_CLIENT = CloudAPIClient()
        return _GLOBAL_CLIENT
```

**注意：** 如果 `core/cloud_api.py` 里没有 `_GLOBAL_CLIENT` 全局变量，按现有的"是否已构造过"逻辑改造，关键点是优先走 AppContext。

- [ ] **Step 1.3.2: 跑 cloud_sync_service 测试，确保没破坏**

Run: `pytest tests/test_cloud_sync_service.py -v`
Expected: 全绿。

### Task 1.4: 改 main.py 用 AppContext

**Files:**
- Modify: `main.py`

- [ ] **Step 1.4.1: 改造 main.py 装配段**

`main.py` 当前在顶层 import 后手动构造各 service，再传给 `MainWindow`。改为：

```python
# 在 main.py 中原本构造 service 的位置（约第 40-80 行附近）改为：
from core.app_context import AppContext

ctx = AppContext.bootstrap()

# 现在所有 service 都通过 ctx 取，例如：
# 旧：window = MainWindow(repository, clipboard_monitor, sync_service, ...)
# 新：window = MainWindow(ctx)

window = MainWindow(ctx)

# atexit / aboutToQuit 注册 shutdown
app.aboutToQuit.connect(ctx.shutdown)
```

**注意：** `MainWindow.__init__` 当前接收多个参数，本阶段先把它们都从 `ctx` 取，但**不要拆 MainWindow**（那是 Phase 6）。

修改方法：在 `MainWindow.__init__` 开头加：

```python
def __init__(self, ctx, parent=None):  # 新签名
    super().__init__(parent)
    self.ctx = ctx
    # 把旧参数还原到 self 上，下面的代码一行不改
    self.repository = ctx.repository
    self.clipboard_monitor = ctx.clipboard_monitor
    self.sync_service = ctx.sync_service
    self.cloud_api = ctx.cloud_api
    # ... 其余 service 全部按现有 attribute 名挂上 self
    # 原有 _setup_ui() / _connect_signals() 调用保留
```

- [ ] **Step 1.4.2: 冷启动冒烟**

启动应用：

```bash
python main.py
```

主窗口应正常出现，所有功能（列表、搜索、收藏、设置）行为不变。手动跑 spec §7 冒烟 checklist 的前 10 项。

如果启动失败，最常见原因：(a) `AppContext.bootstrap` 里某个 service 构造签名与实际不符；(b) MainWindow 里某个 attribute 没正确挂上 self。

### Task 1.5: 跑全量测试 + 打 Phase 1 tag

- [ ] **Step 1.5.1: 全量 pytest**

Run: `pytest -q`
Expected: 13 个原测试 + 1 个新测试（test_app_context）全绿。

- [ ] **Step 1.5.2: 打本地 tag + 中间提交**

```bash
git add core/app_context.py core/cloud_api.py main.py ui/main_window.py tests/test_app_context.py
git commit -m "refactor(p1): 引入 AppContext ServiceRegistry"
git tag pillar-1-appcontext
```

---

## Phase 2: `core/db/` 三层拆分

**目标：** 把 `core/repository.py` 切成 DAO + Query + SyncStateDAO 三个文件，`repository.py` 退化为 Facade。所有现有 `ClipboardRepository.xxx` 调用零修改可用。

### Task 2.1: 准备 `core/db/` 包

**Files:**
- Create: `core/db/__init__.py`

- [ ] **Step 2.1.1: 建空 package**

```python
# core/db/__init__.py
"""数据访问层。

外部仍通过 core.repository.ClipboardRepository 使用，本包内的 DAO/Query/SyncState
是内部实现，可能在未来变更。
"""
```

### Task 2.2: 提取 `ClipboardDAO`

**Files:**
- Read: `core/repository.py`
- Create: `core/db/clipboard_dao.py`
- Test: `tests/test_clipboard_dao.py`

- [ ] **Step 2.2.1: 写 DAO 测试**

```python
# tests/test_clipboard_dao.py
import pytest
from core.db_factory import create_database_manager
from core.db.clipboard_dao import ClipboardDAO
from core.models import ClipboardItem, TextClipboardItem, ContentType


@pytest.fixture
def dao(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_CLIPBOARD_CONFIG_DIR", str(tmp_path))
    db = create_database_manager()
    return ClipboardDAO(db)


def test_add_item_returns_id(dao):
    item = TextClipboardItem(text_content="hello", content_hash="h1", preview="hello", created_at=0)
    item_id = dao.add_item(item)
    assert item_id > 0


def test_get_by_hash(dao):
    item = TextClipboardItem(text_content="hello", content_hash="h2", preview="hello", created_at=0)
    dao.add_item(item)
    fetched = dao.get_by_hash("h2")
    assert fetched is not None
    assert fetched.text_content == "hello"


def test_delete_item(dao):
    item = TextClipboardItem(text_content="x", content_hash="h3", preview="x", created_at=0)
    iid = dao.add_item(item)
    assert dao.delete_item(iid) is True
    assert dao.get_item_by_id(iid) is None


def test_toggle_star(dao):
    item = TextClipboardItem(text_content="x", content_hash="h4", preview="x", created_at=0)
    iid = dao.add_item(item)
    new_state = dao.toggle_star(iid)
    assert new_state is True
    again = dao.toggle_star(iid)
    assert again is False


def test_meta_get_set(dao):
    dao.set_meta("k1", "v1")
    assert dao.get_meta("k1") == "v1"
    assert dao.get_meta("missing", default="d") == "d"


def test_tags_attach_detach(dao):
    item = TextClipboardItem(text_content="x", content_hash="h5", preview="x", created_at=0)
    iid = dao.add_item(item)
    dao.add_tags_to_item(iid, ["t1", "t2"])
    assert set(dao.get_tags_for_item(iid)) == {"t1", "t2"}
    dao.remove_tags_from_item(iid, ["t1"])
    assert dao.get_tags_for_item(iid) == ["t2"]
```

**注意：** TextClipboardItem 的构造签名以 `core/models.py` 为准。如果字段名不同（例如 `created_at` 是必填还是可选），按实际改测试。

- [ ] **Step 2.2.2: 跑测试，确认失败（ImportError）**

Run: `pytest tests/test_clipboard_dao.py -v`
Expected: FAIL，ImportError on `core.db.clipboard_dao`。

- [ ] **Step 2.2.3: 提取 ClipboardDAO 实现**

打开 `core/repository.py`，按 spec §4.2 的方法清单，把以下方法**原样**搬到 `core/db/clipboard_dao.py`：

```
__init__(db_manager) → 改名为 ClipboardDAO，构造逻辑保留（包括 _detect_fts 等内部）
_execute_write / _fetchone / _fetchall / _scalar
add_item / get_by_hash / get_existing_hashes
get_item_by_id
delete_item / toggle_star
get_new_items_since / get_latest_id
cleanup_old_items / cleanup_expired_items
update_item_content / touch_item
add_tags_to_item / remove_tags_from_item / get_tags_for_item
get_meta / set_meta
```

`core/db/clipboard_dao.py` 文件头：

```python
"""ClipboardDAO：纯 CRUD + tags + meta + cleanup。

不负责查询编译（filter clause / regex post-filter），那个在 ClipboardQuery。
不负责云同步状态（cloud_id / unsynced），那个在 SyncStateDAO。
"""

import logging
import re
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from core.base_database import AbstractDatabaseManager
from core.models import ClipboardItem

logger = logging.getLogger(__name__)

try:
    import pymysql  # type: ignore
    _PyMySQLIntegrityError = pymysql.err.IntegrityError  # type: ignore[attr-defined]
except ImportError:
    class _PyMySQLIntegrityError(Exception):
        pass

_INTEGRITY_ERRORS: tuple = (sqlite3.IntegrityError, _PyMySQLIntegrityError)


class ClipboardDAO:
    _SELECT_FIELDS = (
        "id, content_type, text_content, image_data, image_thumbnail, "
        "content_hash, preview, device_id, device_name, "
        "created_at, is_starred, cloud_id, "
        "space_id, source_app, source_title"
    )
    _SELECT_FIELDS_NO_IMAGE = (
        "id, content_type, text_content, NULL as image_data, image_thumbnail, "
        "content_hash, preview, device_id, device_name, "
        "created_at, is_starred, cloud_id, "
        "space_id, source_app, source_title"
    )

    def __init__(self, db_manager: AbstractDatabaseManager):
        self.db = db_manager
        self._is_mysql = db_manager.is_mysql
        self._has_fts = self._detect_fts()

    # 然后把上面列的方法**原封不动**粘到这里。
```

**注意：** 因为 `ClipboardQuery`（下个 Task）和 `SyncStateDAO`（再下个 Task）会用到 `_SELECT_FIELDS`、`_fetchone`、`_fetchall`，DAO 要**保留**这些 helper 并将它们对其他 db/ 模块可见。具体方式：把它们设计为公开属性（去掉下划线 → `select_fields` / `fetchone` / `fetchall`），或者 Query/SyncState 通过 DAO 实例间接调用。**推荐用 DAO 实例方式**，三者共享一个 db_manager，但 Query/SyncState 不要直接读 DAO 的 `_xxx`，而是各自重复一次薄 helper（5 行代码，复用 db_manager 即可）。

- [ ] **Step 2.2.4: 跑 DAO 测试，全绿**

Run: `pytest tests/test_clipboard_dao.py -v`
Expected: 6 个测试 PASS。

### Task 2.3: 提取 `ClipboardQuery`

**Files:**
- Create: `core/db/clipboard_query.py`
- Test: `tests/test_clipboard_query.py`

- [ ] **Step 2.3.1: 写 Query 测试**

```python
# tests/test_clipboard_query.py
import pytest
from core.db_factory import create_database_manager
from core.db.clipboard_dao import ClipboardDAO
from core.db.clipboard_query import ClipboardQuery
from core.models import TextClipboardItem


@pytest.fixture
def dao_and_query(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_CLIPBOARD_CONFIG_DIR", str(tmp_path))
    db = create_database_manager()
    dao = ClipboardDAO(db)
    q = ClipboardQuery(db, dao)
    return dao, q


def test_get_items_pagination(dao_and_query):
    dao, q = dao_and_query
    for i in range(5):
        dao.add_item(TextClipboardItem(
            text_content=f"item{i}", content_hash=f"h{i}", preview=f"item{i}", created_at=i
        ))
    page1 = q.get_items(limit=2, offset=0)
    page2 = q.get_items(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0].text_content != page2[0].text_content


def test_search_by_keyword(dao_and_query):
    dao, q = dao_and_query
    dao.add_item(TextClipboardItem(text_content="hello world", content_hash="hw1", preview="hello world", created_at=0))
    dao.add_item(TextClipboardItem(text_content="foo bar", content_hash="hw2", preview="foo bar", created_at=1))
    results = q.search_by_keyword("hello")
    assert len(results) == 1
    assert "hello" in results[0].text_content


def test_search_query_spec(dao_and_query):
    """search() 走 query_parser，验证 starred:true 这类语法。"""
    dao, q = dao_and_query
    dao.add_item(TextClipboardItem(text_content="a", content_hash="qa", preview="a", created_at=0, is_starred=True))
    dao.add_item(TextClipboardItem(text_content="b", content_hash="qb", preview="b", created_at=1))
    results = q.search("starred:true")
    assert all(item.is_starred for item in results)


def test_get_timeline_groups_by_day(dao_and_query):
    dao, q = dao_and_query
    # 两个不同日历日的 item
    dao.add_item(TextClipboardItem(text_content="a", content_hash="t1", preview="a", created_at=0))
    dao.add_item(TextClipboardItem(text_content="b", content_hash="t2", preview="b", created_at=86400))
    timeline = q.get_timeline(limit=10)
    assert len(timeline) >= 2
```

- [ ] **Step 2.3.2: 跑测试，确认失败**

Run: `pytest tests/test_clipboard_query.py -v`
Expected: ImportError。

- [ ] **Step 2.3.3: 提取 ClipboardQuery 实现**

按 spec §4.2 把以下方法搬到 `core/db/clipboard_query.py`：

```
_build_filter_clauses
_run_query
_do_select
_apply_regex_filter
_count_spec
_fill_tag_ids
get_items
get_items_full
search
search_by_keyword
get_timeline
get_items_by_tag
```

`core/db/clipboard_query.py` 文件头：

```python
"""ClipboardQuery：查询编译 + filter + regex post-filter + 高层 search/timeline。

只读职责。所有 SELECT 字段定义、ContentItem 构造逻辑沿用 DAO 的常量。
"""

import logging
import re
import time
from typing import List, Optional

from core.base_database import AbstractDatabaseManager
from core.db.clipboard_dao import ClipboardDAO
from core.models import ClipboardItem
from core.query_parser import Filter, Op, QuerySpec, parse as parse_query

logger = logging.getLogger(__name__)


class ClipboardQuery:
    def __init__(self, db_manager: AbstractDatabaseManager, dao: ClipboardDAO):
        self.db = db_manager
        self._dao = dao
        self._is_mysql = db_manager.is_mysql
        self._has_fts = dao._has_fts  # 共享 FTS 检测结果
        # 把 _SELECT_FIELDS 暴露过来，避免重复
        self._SELECT_FIELDS = ClipboardDAO._SELECT_FIELDS
        self._SELECT_FIELDS_NO_IMAGE = ClipboardDAO._SELECT_FIELDS_NO_IMAGE

    # 把上面列的方法搬过来。
    # 内部对 _fetchone / _fetchall 的调用改为 `self._dao._fetchone(...)`，
    # 或更优雅地：把那些 helper 作为 DAO 的公开方法（fetchone/fetchall/scalar），
    # Query 通过 self._dao.fetchone(...) 调用。
```

- [ ] **Step 2.3.4: 跑 Query 测试，全绿**

Run: `pytest tests/test_clipboard_query.py -v`
Expected: 4 个测试 PASS。

### Task 2.4: 提取 `SyncStateDAO`

**Files:**
- Create: `core/db/sync_state_dao.py`
- Test: `tests/test_sync_state_dao.py`

- [ ] **Step 2.4.1: 写测试**

```python
# tests/test_sync_state_dao.py
import pytest
from core.db_factory import create_database_manager
from core.db.clipboard_dao import ClipboardDAO
from core.db.sync_state_dao import SyncStateDAO
from core.models import TextClipboardItem


@pytest.fixture
def daos(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_CLIPBOARD_CONFIG_DIR", str(tmp_path))
    db = create_database_manager()
    return ClipboardDAO(db), SyncStateDAO(db)


def test_set_cloud_id_and_lookup(daos):
    dao, sync = daos
    iid = dao.add_item(TextClipboardItem(text_content="a", content_hash="c1", preview="a", created_at=0))
    sync.set_cloud_id(iid, 12345)
    found = sync.get_by_cloud_id(12345)
    assert found is not None
    assert found.id == iid


def test_clear_cloud_id(daos):
    dao, sync = daos
    iid = dao.add_item(TextClipboardItem(text_content="a", content_hash="c2", preview="a", created_at=0))
    sync.set_cloud_id(iid, 999)
    sync.clear_cloud_id(iid)
    assert sync.get_by_cloud_id(999) is None


def test_get_unsynced_items(daos):
    dao, sync = daos
    iid1 = dao.add_item(TextClipboardItem(text_content="a", content_hash="u1", preview="a", created_at=0))
    iid2 = dao.add_item(TextClipboardItem(text_content="b", content_hash="u2", preview="b", created_at=1))
    sync.set_cloud_id(iid1, 1)
    unsynced = sync.get_unsynced_items(limit=10)
    ids = {i.id for i in unsynced}
    assert iid2 in ids
    assert iid1 not in ids


def test_get_starred_unsynced(daos):
    dao, sync = daos
    iid = dao.add_item(TextClipboardItem(text_content="a", content_hash="s1", preview="a", created_at=0, is_starred=True))
    starred = sync.get_starred_unsynced(limit=10)
    assert any(i.id == iid for i in starred)
```

- [ ] **Step 2.4.2: 实现 SyncStateDAO**

按 spec §4.2 把以下方法搬到 `core/db/sync_state_dao.py`：

```
set_cloud_id
set_cloud_ids_bulk
clear_cloud_id
get_by_cloud_id
get_starred_unsynced
get_unsynced_items
get_unstarred_with_cloud_id
update_cloud_sync_metadata
```

文件头：

```python
"""SyncStateDAO：云同步相关的 cloud_id 状态与 unsynced 查询。"""

import logging
import time
from typing import List, Optional

from core.base_database import AbstractDatabaseManager
from core.db.clipboard_dao import ClipboardDAO
from core.models import ClipboardItem

logger = logging.getLogger(__name__)


class SyncStateDAO:
    def __init__(self, db_manager: AbstractDatabaseManager):
        self.db = db_manager
        self._is_mysql = db_manager.is_mysql
        self._SELECT_FIELDS = ClipboardDAO._SELECT_FIELDS
```

- [ ] **Step 2.4.3: 跑测试，全绿**

Run: `pytest tests/test_sync_state_dao.py -v`
Expected: 4 个 PASS。

### Task 2.5: 把 repository.py 转为 Facade

**Files:**
- Modify: `core/repository.py`

- [ ] **Step 2.5.1: 重写 repository.py 为 Facade**

```python
# core/repository.py
"""ClipboardRepository facade。

对外保持 v3.x 时期的所有 public 方法签名；内部 delegate 到 DAO / Query / SyncStateDAO。
"""

from core.base_database import AbstractDatabaseManager
from core.db.clipboard_dao import ClipboardDAO
from core.db.clipboard_query import ClipboardQuery
from core.db.sync_state_dao import SyncStateDAO


class ClipboardRepository:
    def __init__(self, db_manager: AbstractDatabaseManager):
        self._dao = ClipboardDAO(db_manager)
        self._query = ClipboardQuery(db_manager, self._dao)
        self._sync = SyncStateDAO(db_manager)
        # 兼容字段（部分老代码可能直接读）
        self.db = db_manager

    # ---- DAO delegate ----
    def add_item(self, item):              return self._dao.add_item(item)
    def get_by_hash(self, h):              return self._dao.get_by_hash(h)
    def get_existing_hashes(self, hs):     return self._dao.get_existing_hashes(hs)
    def get_item_by_id(self, iid):         return self._dao.get_item_by_id(iid)
    def delete_item(self, iid):            return self._dao.delete_item(iid)
    def toggle_star(self, iid):            return self._dao.toggle_star(iid)
    def update_item_content(self, *a, **kw): return self._dao.update_item_content(*a, **kw)
    def touch_item(self, iid, ts):         return self._dao.touch_item(iid, ts)
    def get_new_items_since(self, *a, **kw): return self._dao.get_new_items_since(*a, **kw)
    def get_latest_id(self):               return self._dao.get_latest_id()
    def cleanup_old_items(self, n=10000):  return self._dao.cleanup_old_items(n)
    def cleanup_expired_items(self, days): return self._dao.cleanup_expired_items(days)
    def add_tags_to_item(self, iid, tids): return self._dao.add_tags_to_item(iid, tids)
    def remove_tags_from_item(self, iid, tids): return self._dao.remove_tags_from_item(iid, tids)
    def get_tags_for_item(self, iid):      return self._dao.get_tags_for_item(iid)
    def get_meta(self, k, default=None):   return self._dao.get_meta(k, default)
    def set_meta(self, k, v):              return self._dao.set_meta(k, v)

    # ---- Query delegate ----
    def get_items(self, *a, **kw):         return self._query.get_items(*a, **kw)
    def get_items_full(self, *a, **kw):    return self._query.get_items_full(*a, **kw)
    def search(self, *a, **kw):            return self._query.search(*a, **kw)
    def search_by_keyword(self, *a, **kw): return self._query.search_by_keyword(*a, **kw)
    def get_timeline(self, *a, **kw):      return self._query.get_timeline(*a, **kw)
    def get_items_by_tag(self, *a, **kw):  return self._query.get_items_by_tag(*a, **kw)

    # ---- SyncStateDAO delegate ----
    def set_cloud_id(self, iid, cid):                 return self._sync.set_cloud_id(iid, cid)
    def set_cloud_ids_bulk(self, pairs):              return self._sync.set_cloud_ids_bulk(pairs)
    def clear_cloud_id(self, iid):                    return self._sync.clear_cloud_id(iid)
    def get_by_cloud_id(self, cid):                   return self._sync.get_by_cloud_id(cid)
    def get_starred_unsynced(self, limit=100):        return self._sync.get_starred_unsynced(limit)
    def get_unsynced_items(self, limit=20):           return self._sync.get_unsynced_items(limit)
    def get_unstarred_with_cloud_id(self, limit=200): return self._sync.get_unstarred_with_cloud_id(limit)
    def update_cloud_sync_metadata(self, *a, **kw):   return self._sync.update_cloud_sync_metadata(*a, **kw)
```

**注意：** 在写完 facade 后，必须用 Grep 校对：原 `ClipboardRepository` 的每个公开方法（grep `^\s{4}def [^_]` in old repository.py）都要在 facade 出现。漏一个，外部调用就会 AttributeError。

- [ ] **Step 2.5.2: 跑现有 repository 测试，全绿不动**

Run: `pytest tests/test_repository.py -v`
Expected: 全部 PASS，**不修改一行测试代码**。

如果有 AttributeError，说明 facade 漏方法，回去补齐。

### Task 2.6: 跑全量测试 + 打 Phase 2 tag

- [ ] **Step 2.6.1: 全量 pytest**

Run: `pytest -q`
Expected: 现有 13 + Phase 1 一个 + Phase 2 三个 = 17 个测试文件全绿。

- [ ] **Step 2.6.2: 启动应用冒烟（列表加载 + 搜索 + 收藏）**

```bash
python main.py
```

- [ ] **Step 2.6.3: 打 tag + 中间提交**

```bash
git add core/db/ core/repository.py tests/test_clipboard_dao.py tests/test_clipboard_query.py tests/test_sync_state_dao.py
git commit -m "refactor(p2): core/db 三层拆分,repository 退化为 Facade"
git tag pillar-2-db
```

---

## Phase 3: `core/cloud/` 拆分

**目标：** 把 `core/cloud_api.py`（990 行）按 domain 切成 5 个文件，CloudAPIClient 退化为 Facade。

### Task 3.1: 准备 `core/cloud/` 包 + HttpClient

**Files:**
- Create: `core/cloud/__init__.py`
- Create: `core/cloud/http.py`

- [ ] **Step 3.1.1: 建包 + 提取 HttpClient**

`core/cloud/__init__.py`:

```python
"""云端 API 客户端。

外部仍通过 core.cloud_api.CloudAPIClient 使用，本包内的 *_client.py
是内部实现，可能在未来变更。
"""
```

`core/cloud/http.py`:

把 `core/cloud_api.py` 里所有与"网络层"相关的内容搬过来：
- base_url 字段
- token 管理（access_token、refresh_token、设置/读取）
- `_request(method, path, ...)` 通用方法
- 错误码 → 异常类映射
- 超时、重试、JSON 解析逻辑

```python
# core/cloud/http.py
"""HttpClient：所有 domain client 共享的网络底盘。"""

import logging
import requests  # 或 httpx，按现有代码
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CloudAPIError(Exception):  # 如果已存在则移过来
    pass


class HttpClient:
    def __init__(self, base_url: str, ...):
        self.base_url = base_url
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        # 其它现有字段

    def set_tokens(self, access, refresh):
        ...

    def _request(self, method: str, path: str, **kwargs) -> Any:
        ...  # 现有逻辑
```

**注意：** 读 `core/cloud_api.py` 现有的 `CloudAPIClient.__init__` 和 `_request` 实现，把网络相关的全部搬过来。如果有 token 刷新拦截器，也搬。

### Task 3.2: 提取 4 个 domain client

**Files:**
- Create: `core/cloud/auth_client.py`
- Create: `core/cloud/sync_client.py`
- Create: `core/cloud/files_client.py`
- Create: `core/cloud/spaces_client.py`

- [ ] **Step 3.2.1: 按 domain 分类 CloudAPIClient 的方法**

打开 `core/cloud_api.py`，用 Grep 列出所有公开方法（`grep '^\s{4}def [^_]'`），按以下规则归类：

| domain | 关键词 |
|---|---|
| `auth` | `login / register / verify / refresh / logout / send_code / change_password` |
| `sync` | `upload_item / pull_items / get_items / star / unstar` |
| `files` | `upload_file_* / get_file_* / get_download_url / dedup / multipart` |
| `spaces` | `space / spaces / member / invite / team` |

把列表写到一个临时 markdown 文件（如 `cloud_api_dispatch.md`），逐个标注归属。如果某方法横跨两个领域（少见），就近原则归一个，另一个领域里加 delegate。

- [ ] **Step 3.2.2: 创建 4 个 domain client 文件，把方法搬过去**

每个 domain client 形如：

```python
# core/cloud/auth_client.py
import logging
from core.cloud.http import HttpClient

logger = logging.getLogger(__name__)


class AuthClient:
    def __init__(self, http: HttpClient):
        self._http = http

    def login(self, email, password):
        # 把 CloudAPIClient.login 的实现搬过来，把 self._request(...) 改成 self._http._request(...)
        ...

    def register(self, email, password, code):
        ...

    # 其余 auth domain 方法
```

`sync_client.py` / `files_client.py` / `spaces_client.py` 同样模式。

### Task 3.3: 把 cloud_api.py 转为 Facade

**Files:**
- Modify: `core/cloud_api.py`
- Test: `tests/test_cloud_api_facade.py`
- Test: `tests/test_cloud_api_facade_completeness.py`

- [ ] **Step 3.3.1: 写 completeness 测试（先抓基线）**

在 facade 化**之前**，跑一段脚本抓出当前 `CloudAPIClient` 的所有公开方法名：

```python
# scripts/capture_cloud_api_baseline.py（一次性脚本，不提交）
import inspect
from core.cloud_api import CloudAPIClient
public = sorted(n for n, _ in inspect.getmembers(CloudAPIClient, predicate=inspect.isfunction) if not n.startswith("_"))
print("\n".join(public))
```

把输出保存为 `tests/_cloud_api_public_methods.txt`（提交到仓库）。

然后写测试：

```python
# tests/test_cloud_api_facade_completeness.py
import inspect
from pathlib import Path
from core.cloud_api import CloudAPIClient


def test_no_public_method_dropped():
    expected = Path(__file__).parent.joinpath("_cloud_api_public_methods.txt").read_text().splitlines()
    expected = {m.strip() for m in expected if m.strip()}
    actual = {n for n, _ in inspect.getmembers(CloudAPIClient, predicate=inspect.isfunction) if not n.startswith("_")}
    missing = expected - actual
    assert not missing, f"CloudAPIClient facade 漏方法: {sorted(missing)}"
```

- [ ] **Step 3.3.2: 写 facade 行为测试**

```python
# tests/test_cloud_api_facade.py
from unittest.mock import MagicMock, patch
from core.cloud_api import CloudAPIClient


def test_login_delegates_to_auth_client():
    client = CloudAPIClient()
    with patch.object(client.auth, "login", return_value={"ok": True}) as m:
        result = client.login("a@b", "pw")
        m.assert_called_once_with("a@b", "pw")
        assert result == {"ok": True}


def test_upload_item_delegates_to_sync_client():
    client = CloudAPIClient()
    with patch.object(client.sync, "upload_item", return_value={"id": 1}) as m:
        client.upload_item({"text": "x"})
        m.assert_called_once()


def test_upload_file_init_delegates_to_files_client():
    client = CloudAPIClient()
    with patch.object(client.files, "upload_file_init", return_value={"upload_id": "u1"}) as m:
        client.upload_file_init("hash", 1024)
        m.assert_called_once()
```

- [ ] **Step 3.3.3: 改写 cloud_api.py 为 Facade**

```python
# core/cloud_api.py
"""CloudAPIClient facade。

对外保持现有所有 public 方法签名；内部 delegate 到 auth/sync/files/spaces。
"""

from core.cloud.http import HttpClient, CloudAPIError  # noqa: F401（外部 import）
from core.cloud.auth_client import AuthClient
from core.cloud.sync_client import SyncClient
from core.cloud.files_client import FilesClient
from core.cloud.spaces_client import SpacesClient


class CloudAPIClient:
    def __init__(self, ...):  # 保留原签名
        self._http = HttpClient(...)
        self.auth = AuthClient(self._http)
        self.sync = SyncClient(self._http)
        self.files = FilesClient(self._http)
        self.spaces = SpacesClient(self._http)

    # delegate 所有原 public 方法。
    # 按 Step 3.2.1 中归类的清单逐个写：
    def login(self, *a, **kw):       return self.auth.login(*a, **kw)
    def register(self, *a, **kw):    return self.auth.register(*a, **kw)
    def logout(self, *a, **kw):      return self.auth.logout(*a, **kw)
    def upload_item(self, *a, **kw): return self.sync.upload_item(*a, **kw)
    # ... 所有 ~80 个公开方法

    # 兼容性属性（如果原 CloudAPIClient 有暴露 access_token 等字段）
    @property
    def access_token(self):
        return self._http.access_token


def get_cloud_client():  # Phase 1 已改过；保持
    try:
        from core.app_context import AppContext
        return AppContext.current().cloud_api
    except RuntimeError:
        global _GLOBAL_CLIENT
        if _GLOBAL_CLIENT is None:
            _GLOBAL_CLIENT = CloudAPIClient()
        return _GLOBAL_CLIENT


_GLOBAL_CLIENT = None
```

- [ ] **Step 3.3.4: 跑 facade + completeness 测试**

```bash
pytest tests/test_cloud_api_facade.py tests/test_cloud_api_facade_completeness.py -v
```

Expected: 全绿。如果 completeness 失败，按报错补 delegate。

- [ ] **Step 3.3.5: 跑 cloud_sync_service 测试，确保链路依旧**

```bash
pytest tests/test_cloud_sync_service.py tests/test_file_sync.py tests/test_file_upload_flow.py -v
```

Expected: 全绿。

### Task 3.4: 全量测试 + Phase 3 tag

- [ ] **Step 3.4.1: 全量 pytest**

Run: `pytest -q`
Expected: 20 个测试文件全绿。

- [ ] **Step 3.4.2: 打 tag + 提交**

```bash
git add core/cloud/ core/cloud_api.py tests/_cloud_api_public_methods.txt tests/test_cloud_api_facade.py tests/test_cloud_api_facade_completeness.py
git commit -m "refactor(p3): core/cloud 按 domain 拆分,cloud_api 退化为 Facade"
git tag pillar-3-cloud
```

---

## Phase 4: `i18n_strings/` 拆分 + `i18n.py` shim

**目标：** 把 `i18n.py`（1482 行的大 dict）拆成 5 个领域文件，`i18n.py` 留为 ≤100 行 shim。

### Task 4.1: 规划 key 分组

- [ ] **Step 4.1.1: 读 i18n.py，按前缀/语义把 keys 分到 5 组**

打开 `i18n.py`，看 `_strings = {...}` 字典。每个 key 形如 `"main.title"` / `"settings.general.hotkey_label"` / `"cloud.login.email_placeholder"`。

按 key 前缀分：
- `main.*` / `sidebar.*` / `list.*` / `search.*` → `i18n_strings/main.py`
- `settings.*` → `i18n_strings/settings.py`
- `cloud.*` / `login.*` / `sync.*` / `subscription.*` → `i18n_strings/cloud.py`
- `plugin.*` / `plugins.*` → `i18n_strings/plugins.py`
- 其它（`onboarding.*` / `share.*` / `common.*`）→ `i18n_strings/misc.py`

如果 key 没有前缀或前缀不明，归到 `misc.py`。

### Task 4.2: 写 completeness 测试

**Files:**
- Test: `tests/test_i18n_completeness.py`

- [ ] **Step 4.2.1: 先抓重构前 baseline**

```python
# scripts/capture_i18n_baseline.py（一次性脚本）
import json
import i18n
out = {lang: sorted(d.keys()) for lang, d in i18n._strings.items()}
import pathlib
pathlib.Path("tests/_i18n_keys_baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
```

```bash
python scripts/capture_i18n_baseline.py
git add tests/_i18n_keys_baseline.json
```

- [ ] **Step 4.2.2: 写测试**

```python
# tests/test_i18n_completeness.py
import json
from pathlib import Path
import i18n


def test_all_languages_have_same_keys():
    baseline = json.loads(Path("tests/_i18n_keys_baseline.json").read_text())
    for lang, expected_keys in baseline.items():
        actual = sorted(i18n._strings[lang].keys())
        missing = set(expected_keys) - set(actual)
        added = set(actual) - set(expected_keys)
        assert not missing, f"{lang} 缺失 keys: {sorted(missing)}"
        assert not added, f"{lang} 多余 keys: {sorted(added)}"


def test_t_returns_value_for_each_key():
    """t() 对每个 key 返回字符串（不返回 key 本身或 None）。"""
    for lang in i18n._strings:
        i18n.set_language(lang)
        for key in i18n._strings[lang]:
            value = i18n.t(key)
            assert isinstance(value, str)
            assert value != ""
```

### Task 4.3: 拆出 i18n_strings 子文件

**Files:**
- Create: `i18n_strings/__init__.py`
- Create: `i18n_strings/main.py`
- Create: `i18n_strings/settings.py`
- Create: `i18n_strings/cloud.py`
- Create: `i18n_strings/plugins.py`
- Create: `i18n_strings/misc.py`

- [ ] **Step 4.3.1: 写 `__init__.py`**

```python
# i18n_strings/__init__.py
"""i18n 字符串包。

每个子文件导出一个 STRINGS 字典：dict[lang_code, dict[key, value]]。
load_all() 合并所有子文件，返回最终的语言 → keys → 值 三层 dict。
"""

from i18n_strings import main, settings, cloud, plugins, misc


def load_all() -> dict:
    merged: dict = {}
    for module in (main, settings, cloud, plugins, misc):
        for lang, kv in module.STRINGS.items():
            merged.setdefault(lang, {}).update(kv)
    return merged
```

- [ ] **Step 4.3.2: 把 keys 搬到对应子文件**

每个子文件形如：

```python
# i18n_strings/main.py
STRINGS = {
    "zh": {
        "main.title": "共享剪贴板",
        "main.search_placeholder": "搜索...",
        # ... 其它 main.* 的 zh 翻译
    },
    "en": {
        "main.title": "Shared Clipboard",
        # ...
    },
}
```

**操作建议：**
- 一次只搬一组（先 main.*，再 settings.* …），每搬完一组就跑 completeness 测试，确保不丢 key
- 用编辑器的多光标 / 正则替换批量操作
- 注意保留 zh / en 之外的语言（看 `_strings` 顶层 keys）

### Task 4.4: 把 i18n.py 改成 shim

**Files:**
- Modify: `i18n.py`

- [ ] **Step 4.4.1: 重写 i18n.py（≤100 行）**

```python
# i18n.py
"""i18n shim。

字符串数据在 i18n_strings/ 包里按领域拆文件。运行时由 load_all() 合并。
对外保持现有的 t / set_language / get_language / available_languages 接口。
"""

import logging
from typing import Optional

from i18n_strings import load_all

logger = logging.getLogger(__name__)

_strings: dict = load_all()
_current_lang: str = "zh"


def t(key: str, **kwargs) -> str:
    """按当前语言查字符串。"""
    lang_dict = _strings.get(_current_lang) or _strings.get("zh") or {}
    value = lang_dict.get(key, key)
    if kwargs:
        try:
            value = value.format(**kwargs)
        except Exception:
            logger.debug("i18n format 失败: key=%s kwargs=%s", key, kwargs)
    return value


def set_language(lang: str) -> None:
    global _current_lang
    if lang in _strings:
        _current_lang = lang
    else:
        logger.warning("不支持的语言: %s", lang)


def get_language() -> str:
    return _current_lang


def available_languages() -> list:
    return sorted(_strings.keys())
```

**注意：**
- 如果原 `i18n.py` 有额外辅助函数（如 plural 处理、占位替换扩展），保留它们
- 如果有"按语言加载字体"之类副作用，也保留
- 关键是 `t()` / `set_language()` / `get_language()` / `available_languages()` 行为完全一致

- [ ] **Step 4.4.2: 跑 completeness + 全量测试**

```bash
pytest tests/test_i18n_completeness.py -v
pytest -q
```

Expected: 全绿。如果 completeness 失败，说明 key 拆漏，回 Step 4.3.2 补。

### Task 4.5: 启动冒烟 + tag

- [ ] **Step 4.5.1: 启动应用切语言**

```bash
python main.py
```

打开设置 → 切换语言 zh ↔ en → 关闭再打开，关键文案要全部生效。

- [ ] **Step 4.5.2: 提交 + tag**

```bash
git add i18n.py i18n_strings/ tests/test_i18n_completeness.py tests/_i18n_keys_baseline.json
git commit -m "refactor(p4): i18n.py 退化为 shim,字符串按领域拆 i18n_strings/"
git tag pillar-4-i18n
```

---

## Phase 5: `ui/settings/` 按 Tab 拆分

**目标：** `ui/settings_dialog.py`（1414 行）拆为 `ui/settings/` 包，每个 Tab 一个文件；`ui/settings_dialog.py` 退化为 30 行 shim。

### Task 5.1: 准备包结构 + 写 smoke 测试

**Files:**
- Create: `ui/settings/__init__.py`
- Test: `tests/test_settings_tabs_smoke.py`

- [ ] **Step 5.1.1: 写 smoke 测试**

```python
# tests/test_settings_tabs_smoke.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.app_context import AppContext


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_CLIPBOARD_CONFIG_DIR", str(tmp_path))
    c = AppContext.bootstrap()
    yield c
    c.shutdown()


def test_settings_dialog_constructs(qapp, ctx):
    from ui.settings import SettingsDialog
    dlg = SettingsDialog(ctx=ctx)
    assert dlg is not None
    dlg.close()


def test_each_tab_constructs(qapp, ctx):
    from ui.settings.general_tab import GeneralTab
    from ui.settings.sync_tab import SyncTab
    from ui.settings.cloud_tab import CloudTab
    from ui.settings.plugins_tab import PluginsTab
    from ui.settings.advanced_tab import AdvancedTab
    for cls in (GeneralTab, SyncTab, CloudTab, PluginsTab, AdvancedTab):
        w = cls(ctx=ctx)
        assert w is not None
        w.close()
```

- [ ] **Step 5.1.2: 建 `__init__.py`**

```python
# ui/settings/__init__.py
from ui.settings.settings_dialog import SettingsDialog  # noqa: F401

__all__ = ["SettingsDialog"]
```

### Task 5.2-5.6: 按 Tab 拆分

针对每个 Tab 重复以下流程。Tab 列表：`general / sync / cloud / plugins / advanced`。

**通用步骤（以 GeneralTab 为例）：**

- [ ] **Step 5.2.1: 读旧 settings_dialog.py，定位 GeneralTab 范围**

`ui/settings_dialog.py` 内部按 QTabWidget 组织。用 Grep 找 tab 添加位置（`addTab(...)`），逐个 tab 找到其 UI 构造段（一般是 `_build_general_tab()` 或 inline）。

- [ ] **Step 5.2.2: 新建 `ui/settings/general_tab.py`**

```python
# ui/settings/general_tab.py
"""General Tab：语言、热键、启动、热缓存、最大条目。"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, ...
from PySide6.QtCore import Signal

from i18n import t


class GeneralTab(QWidget):
    settings_changed = Signal()  # 任何选项改动时发，让外部 SettingsDialog 决定是否立即生效

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()
        self._load_current_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        # 从旧 settings_dialog.py 把 general 相关的 widget 构造段搬过来
        ...

    def _load_current_values(self):
        # 从 config.settings 读取当前值并填入 UI
        ...

    def apply(self) -> None:
        """把 UI 上的值写回 settings。由 SettingsDialog 在 OK 时统一调用。"""
        ...
```

- [ ] **Step 5.2.3: 其它 Tab 同样模式**

`sync_tab.py`：局域网同步、设备名、自动同步。
`cloud_tab.py`：账户、订阅、云同步开关、登录/登出。
`plugins_tab.py`：插件列表 + 进入插件配置。
`advanced_tab.py`：日志位置、数据迁移、设备 ID、清空数据。

每个 Tab 都暴露：
- `__init__(self, ctx, parent=None)`
- `apply(self) -> None`（在确定保存时调用）
- 可选：`settings_changed` Signal（如果有"实时生效"的开关）

### Task 5.7: 写 SettingsDialog 壳

**Files:**
- Create: `ui/settings/settings_dialog.py`

- [ ] **Step 5.7.1: 写壳**

```python
# ui/settings/settings_dialog.py
"""SettingsDialog 壳：QTabWidget 容器，加载各 Tab。

业务在各 Tab 内部，壳只负责 OK/Cancel/Apply 路由。
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QDialogButtonBox

from i18n import t
from ui.settings.general_tab import GeneralTab
from ui.settings.sync_tab import SyncTab
from ui.settings.cloud_tab import CloudTab
from ui.settings.plugins_tab import PluginsTab
from ui.settings.advanced_tab import AdvancedTab


class SettingsDialog(QDialog):
    TAB_GENERAL = "general"
    TAB_SYNC = "sync"
    TAB_CLOUD = "cloud"
    TAB_PLUGINS = "plugins"
    TAB_ADVANCED = "advanced"

    def __init__(self, ctx, parent=None, initial_tab: str = ""):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(t("settings.title"))
        self._build_ui()
        if initial_tab:
            self._select_tab(initial_tab)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self._tab_map = {}
        for tid, cls, key in (
            (self.TAB_GENERAL, GeneralTab, "settings.tab.general"),
            (self.TAB_SYNC, SyncTab, "settings.tab.sync"),
            (self.TAB_CLOUD, CloudTab, "settings.tab.cloud"),
            (self.TAB_PLUGINS, PluginsTab, "settings.tab.plugins"),
            (self.TAB_ADVANCED, AdvancedTab, "settings.tab.advanced"),
        ):
            tab = cls(ctx=self.ctx)
            self.tabs.addTab(tab, t(key))
            self._tab_map[tid] = tab
        layout.addWidget(self.tabs)

        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

    def _on_accept(self):
        for tab in self._tab_map.values():
            if hasattr(tab, "apply"):
                tab.apply()
        self.accept()

    def _select_tab(self, tid: str):
        widget = self._tab_map.get(tid)
        if widget:
            self.tabs.setCurrentWidget(widget)
```

### Task 5.8: 把 `ui/settings_dialog.py` 改成 shim

**Files:**
- Modify: `ui/settings_dialog.py`

- [ ] **Step 5.8.1: 退化为 shim**

```python
# ui/settings_dialog.py
"""向后兼容 shim。新代码用 from ui.settings import SettingsDialog。"""

from ui.settings.settings_dialog import SettingsDialog  # noqa: F401

__all__ = ["SettingsDialog"]
```

### Task 5.9: 验证 + tag

- [ ] **Step 5.9.1: 跑 smoke 测试**

```bash
pytest tests/test_settings_tabs_smoke.py -v
```

Expected: 2 个测试 PASS。

- [ ] **Step 5.9.2: 启动应用打开设置弹窗**

```bash
python main.py
```

逐个 Tab 切，主要选项可改、可保存、重启后保留。

- [ ] **Step 5.9.3: 全量测试 + tag**

```bash
pytest -q
git add ui/settings/ ui/settings_dialog.py tests/test_settings_tabs_smoke.py
git commit -m "refactor(p5): settings_dialog 按 Tab 拆分到 ui/settings/"
git tag pillar-5-settings
```

---

## Phase 6: `ui/controllers/` 拆 MainWindow

**目标：** 抽出 4 个 controller，MainWindow 退化为壳 + 信号路由。

### Task 6.1: 准备包 + 4 个 controller 测试

**Files:**
- Create: `ui/controllers/__init__.py`
- Test: `tests/test_controllers_list.py`
- Test: `tests/test_controllers_item_action.py`
- Test: `tests/test_controllers_plugin.py`
- Test: `tests/test_controllers_cloud_lifecycle.py`

- [ ] **Step 6.1.1: 写 4 个 controller 的最小 smoke 测试**

```python
# tests/test_controllers_list.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication, QWidget

from ui.controllers.clipboard_list_controller import ClipboardListController


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_controller_constructs(qapp):
    parent = QWidget()
    ctx = MagicMock()
    ctx.repository.get_items.return_value = []
    c = ClipboardListController(parent, ctx)
    assert c is not None
    parent.close()


def test_load_items_calls_repository(qapp):
    parent = QWidget()
    parent.list_widget = MagicMock()
    ctx = MagicMock()
    ctx.repository.get_items.return_value = []
    c = ClipboardListController(parent, ctx)
    c.load_items()
    ctx.repository.get_items.assert_called()
    parent.close()
```

（其它三个 controller 同样模式，写最小构造 + 一次关键调用。）

### Task 6.2: 抽 ClipboardListController

**Files:**
- Create: `ui/controllers/clipboard_list_controller.py`
- Modify: `ui/main_window.py`

- [ ] **Step 6.2.1: 创建 controller 文件**

```python
# ui/controllers/clipboard_list_controller.py
"""列表加载/分页/搜索/sidebar 路由。"""

import logging
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class ClipboardListController(QObject):
    items_loaded = Signal(list)
    search_help_requested = Signal()

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self._parent = parent  # MainWindow
        self.ctx = ctx
        self._current_page = 0
        self._page_size = 100  # 与现有 PAGE_SIZE 保持一致，从 config 读
        # 其它需要的 state（搜索关键词、当前 space_id、starred 过滤）
```

- [ ] **Step 6.2.2: 把 MainWindow 中的列表方法搬过来**

从 `ui/main_window.py` 把 spec §4.5 列表的方法搬到 controller：

```
_load_items / _update_list / _make_list_item
_on_search_changed / _do_search / _show_search_help
_prev_page / _next_page / _update_pagination
_toggle_starred_filter
_on_view_changed / _on_timeline_item_clicked
_on_sidebar_space_changed / _on_sidebar_tag_changed
_on_sidebar_create_space / _on_sidebar_manage_team / _on_sidebar_upgrade
_on_tab_changed
_prepend_item / _on_new_items / _on_item_added
```

方法内引用的 `self.list_widget / self.search_edit / self.sidebar / self.tabs / self.repository` 全部改为 `self._parent.list_widget / ... / self.ctx.repository`。

去掉私有前缀 `_`，改名为公开方法（`load_items`、`on_search_changed`、…），方便从 MainWindow 信号路由调用。

- [ ] **Step 6.2.3: 改 MainWindow，删掉搬走的方法，转 controller**

在 `ui/main_window.py` 的 `__init__` 末尾添加：

```python
from ui.controllers.clipboard_list_controller import ClipboardListController
self.list_controller = ClipboardListController(self, self.ctx)
```

`_connect_signals` 把列表相关的连接改成连到 controller：

```python
def _connect_signals(self):
    self.search_edit.textChanged.connect(self.list_controller.on_search_changed)
    self.prev_btn.clicked.connect(self.list_controller.prev_page)
    self.next_btn.clicked.connect(self.list_controller.next_page)
    # ... 其它列表信号
```

删掉 MainWindow 中已经搬走的方法。

- [ ] **Step 6.2.4: 跑测试 + 冒烟**

```bash
pytest tests/test_controllers_list.py -v
python main.py  # 冒烟：列表能加载、搜索、翻页
```

### Task 6.3: 抽 ItemActionController（同 6.2 流程）

**Files:**
- Create: `ui/controllers/item_action_controller.py`

接管的方法：`_on_item_clicked / _handle_image_loaded / _on_item_delete / _on_cloud_delete / _handle_cloud_delete_done / _on_item_star / _on_item_save / _handle_save_image_done / _on_image_url_copy / _handle_image_url_done / _on_share_items / _on_add_tags / _show_copy_feedback`。

- [ ] **Step 6.3.1: 创建 controller**
- [ ] **Step 6.3.2: 搬方法 + 连信号**
- [ ] **Step 6.3.3: 跑 `tests/test_controllers_item_action.py` + 启动冒烟（删/收藏/保存）**

### Task 6.4: 抽 PluginActionController

**Files:**
- Create: `ui/controllers/plugin_action_controller.py`

接管的方法：`_show_context_menu / _run_plugin_action / _handle_plugin_item_loaded / _dispatch_plugin_action / _on_plugin_progress / _on_plugin_finished / _on_plugin_error / _show_plugin_feedback / _cancel_plugin`。

- [ ] **Step 6.4.1: 创建 + 搬方法**
- [ ] **Step 6.4.2: 跑 `tests/test_controllers_plugin.py` + 跑 smart_text 冒烟**

### Task 6.5: 抽 CloudLifecycleController

**Files:**
- Create: `ui/controllers/cloud_lifecycle_controller.py`

接管的方法：`_bootstrap_files_stack_after_login / _bootstrap_cloud_sync_after_login / _teardown_cloud_sync_after_logout / _advance_sync_after_cloud`。

- [ ] **Step 6.5.1: 创建 + 搬方法**
- [ ] **Step 6.5.2: 跑 `tests/test_controllers_cloud_lifecycle.py` + 登录/登出冒烟**

### Task 6.6: MainWindow 收尾

**Files:**
- Modify: `ui/main_window.py`

- [ ] **Step 6.6.1: 确认 MainWindow ≤350 行**

```bash
wc -l ui/main_window.py
```

如果还超，再看是否有可搬未搬的方法。

保留方法：
- `__init__ / _setup_ui / _connect_signals`
- `closeEvent / show_window / _minimize_window / _toggle_pin / _request_quit`
- `_show_settings / _do_migration / _maybe_show_onboarding / _on_onboarding_done`

- [ ] **Step 6.6.2: closeEvent 显式清理 controller**

```python
def closeEvent(self, event):
    # 防止 QObject 引用环
    for ctrl in (self.list_controller, self.item_controller,
                 self.plugin_controller, self.cloud_controller):
        try:
            ctrl.setParent(None)
            ctrl.deleteLater()
        except Exception:
            pass
    super().closeEvent(event)
```

- [ ] **Step 6.6.3: 全量测试**

```bash
pytest -q
```

Expected: 现有 13 + Phase 1 一个 + Phase 2 三个 + Phase 3 两个 + Phase 4 一个 + Phase 5 一个 + Phase 6 四个 = 25 个测试文件全绿。

- [ ] **Step 6.6.4: 完整冒烟（spec §7 全部 14 项）**

逐项跑一遍。

- [ ] **Step 6.6.5: tag**

```bash
git add ui/controllers/ ui/main_window.py tests/test_controllers_*.py
git commit -m "refactor(p6): MainWindow 抽 4 controller,退化为壳+信号路由"
git tag pillar-6-controllers
```

---

## Phase 7: `core/plugin_extension_points.py`

**目标：** 抽 ExtensionPointRegistry，把"插件右键菜单"扩展点显式化，UI 通过它枚举而不再直引 PluginManager。

### Task 7.1: 实现 ExtensionPointRegistry

**Files:**
- Create: `core/plugin_extension_points.py`
- Test: `tests/test_extension_points.py`

- [ ] **Step 7.1.1: 写测试**

```python
# tests/test_extension_points.py
from core.plugin_extension_points import ExtensionPointRegistry


def test_register_and_enumerate_context_menu():
    reg = ExtensionPointRegistry()
    action = object()  # placeholder
    reg.register_context_menu("plugin_a", action)
    actions = reg.context_menu_actions(item=None)
    assert action in actions


def test_unregister_plugin_clears_actions():
    reg = ExtensionPointRegistry()
    action = object()
    reg.register_context_menu("plugin_a", action)
    reg.unregister_plugin("plugin_a")
    assert reg.context_menu_actions(item=None) == []


def test_per_plugin_isolation():
    reg = ExtensionPointRegistry()
    a, b = object(), object()
    reg.register_context_menu("plugin_a", a)
    reg.register_context_menu("plugin_b", b)
    reg.unregister_plugin("plugin_a")
    actions = reg.context_menu_actions(item=None)
    assert b in actions
    assert a not in actions
```

- [ ] **Step 7.1.2: 实现**

```python
# core/plugin_extension_points.py
"""ExtensionPointRegistry：UI 通过它枚举可用插件扩展。

本期只实现"右键菜单"扩展点，其它（search_providers / inline_actions）只占位。
"""

from collections import defaultdict
from typing import List


class ExtensionPointRegistry:
    def __init__(self):
        self._context_menu: dict = defaultdict(list)

    def register_context_menu(self, plugin_id: str, action) -> None:
        self._context_menu[plugin_id].append(action)

    def unregister_plugin(self, plugin_id: str) -> None:
        self._context_menu.pop(plugin_id, None)

    def context_menu_actions(self, item) -> List:
        result = []
        for actions in self._context_menu.values():
            result.extend(actions)
        return result

    # 占位
    def search_providers(self) -> list:
        return []

    def inline_actions(self) -> list:
        return []
```

### Task 7.2: PluginManager 接入 registry

**Files:**
- Modify: `core/plugin_manager.py`
- Modify: `core/app_context.py`

- [ ] **Step 7.2.1: PluginManager.load_plugin 注册扩展点**

打开 `core/plugin_manager.py`，找 `load_plugin`（加载完成时的位置）。在 plugin 加载成功后，把其 manifest 中的 context_menu actions 注册到 registry：

```python
class PluginManager:
    def __init__(self, extension_points=None):
        # ...原有逻辑
        self._extension_points = extension_points

    def load_plugin(self, ...):
        # 原有加载逻辑
        ...
        if self._extension_points is not None:
            for action in plugin.actions:  # 按现有 PluginAction 模型
                self._extension_points.register_context_menu(plugin.plugin_id, action)

    def unload_plugin(self, plugin_id):
        if self._extension_points is not None:
            self._extension_points.unregister_plugin(plugin_id)
        # 原有卸载逻辑
        ...
```

- [ ] **Step 7.2.2: AppContext 装配 registry 并传给 PluginManager**

回到 `core/app_context.py`，修改 `bootstrap`：

```python
from core.plugin_extension_points import ExtensionPointRegistry

# 在 plugin_manager 构造之前
ctx.extension_points = ExtensionPointRegistry()
ctx.plugin_manager = PluginManager(extension_points=ctx.extension_points)
```

如果 `PluginManager.__init__` 之前不接受 `extension_points` 参数，要在 PluginManager 里加（默认 `None`），保持向后兼容。

### Task 7.3: PluginActionController 改走 registry

**Files:**
- Modify: `ui/controllers/plugin_action_controller.py`

- [ ] **Step 7.3.1: 改 show_context_menu**

原 `_show_context_menu` 从 `self.ctx.plugin_manager.get_actions_for_item(item)` 取 actions。改为：

```python
def show_context_menu(self, pos):
    item = self._parent.list_widget.itemAt(pos)
    actions = self.ctx.extension_points.context_menu_actions(item)
    # 后续构造 QMenu 的代码不变
    ...
```

- [ ] **Step 7.3.2: 跑 plugin controller 测试 + smart_text 冒烟**

```bash
pytest tests/test_controllers_plugin.py tests/test_extension_points.py -v
python main.py  # 冒烟：右键菜单显示 smart_text，跑一次插件
```

### Task 7.4: 全量验证 + tag

- [ ] **Step 7.4.1: 全量 pytest**

```bash
pytest -q
```

Expected: 全部测试文件全绿。

- [ ] **Step 7.4.2: 完整冒烟（spec §7 全部 14 项再过一遍）**

- [ ] **Step 7.4.3: tag**

```bash
git add core/plugin_extension_points.py core/plugin_manager.py core/app_context.py ui/controllers/plugin_action_controller.py tests/test_extension_points.py
git commit -m "refactor(p7): 抽 ExtensionPointRegistry,插件菜单走扩展点"
git tag pillar-7-extension-points
```

---

## Phase 8: 完成定义验证 + 主线合并

### Task 8.1: 行数预算检查

- [ ] **Step 8.1.1: 量行数**

```bash
wc -l core/repository.py core/cloud_api.py ui/main_window.py ui/settings_dialog.py i18n.py
```

Expected:
- `core/repository.py` ≤ 200
- `core/cloud_api.py` ≤ 200
- `ui/main_window.py` ≤ 350
- `ui/settings_dialog.py` ≤ 30
- `i18n.py` ≤ 100

如果某项超，看哪些函数还可以下沉到对应 sub-module。

### Task 8.2: 启动时间对比

- [ ] **Step 8.2.1: 测启动**

跑 3 次取中位数：

```bash
python -c "import time; t=time.time(); import main; print(time.time()-t)"
```

与 Pre-Flight Step 0.3 的基线对比，差异在 ±10% 以内。

### Task 8.3: 零 warning

- [ ] **Step 8.3.1: 严格模式跑测试**

```bash
python -W error -m pytest -q
```

Expected: 零 warning。如有 DeprecationWarning / ResourceWarning，定位并修。

### Task 8.4: 完整冒烟最后一遍

- [ ] **Step 8.4.1: spec §7 全部 14 项**

逐项打 ✓。任何一项失败，回到对应 phase 修。

### Task 8.5: 合并到 main

- [ ] **Step 8.5.1: 生成 diff stat 自查**

```bash
git diff main..refactor/foundation --stat
git log main..refactor/foundation --oneline
```

逐文件 review 一遍，确认没有意外改动（schema、配置、插件 manifest、构建脚本）。

- [ ] **Step 8.5.2: squash 合并到 main**

```bash
git checkout main
git merge --squash refactor/foundation
git commit -m "refactor: 公共底盘重构（AppContext + db/cloud/i18n/settings/controllers/extension-points 七柱）

为后续插件 / 云同步 / 团队空间 / AI 四个方向铺路。
保持所有外部 import 路径、所有 public 方法签名、所有持久化产物完全不变。

- core/app_context.py：ServiceRegistry 统一装配
- core/db/：repository.py 切为 DAO + Query + SyncStateDAO + Facade
- core/cloud/：cloud_api.py 切为 auth/sync/files/spaces + Facade
- core/plugin_extension_points.py：扩展点注册中心
- ui/controllers/：MainWindow 抽 4 个 controller（≤350 行）
- ui/settings/：settings_dialog 按 Tab 拆分
- i18n_strings/：i18n.py 退化为 shim,字符串按领域拆

13 个原测试零修改全绿,新增 13 个测试全绿,14 项冒烟全过,启动时间 ±10% 内。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8.5.3: push 到 main**

```bash
git push origin main
```

### Task 8.6: 清理

- [ ] **Step 8.6.1: 删本地 tag（可选）**

```bash
git tag -d pillar-1-appcontext pillar-2-db pillar-3-cloud pillar-4-i18n pillar-5-settings pillar-6-controllers pillar-7-extension-points
```

- [ ] **Step 8.6.2: 删 refactor 分支**

```bash
git branch -d refactor/foundation
```

---

## Done Criteria 复核

最终 checklist：

- [ ] `core/repository.py` ≤ 200 行
- [ ] `core/cloud_api.py` ≤ 200 行
- [ ] `ui/main_window.py` ≤ 350 行
- [ ] `ui/settings_dialog.py` 转为 shim ≤ 30 行
- [ ] `i18n.py` ≤ 100 行
- [ ] 13 个现有测试文件零修改、全绿
- [ ] 13 个新增测试全绿
- [ ] 14 项冷启动 / 冒烟全过
- [ ] 启动时间相对重构前 ±10% 以内
- [ ] `python -W error -m pytest -q` 零 warning

全部打 ✓ 后，本次重构完成。后续 4 个方向（插件、云、空间、AI）可各自开新 spec → 新 plan，互不阻塞。
