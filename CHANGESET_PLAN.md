# CHANGESET_PLAN — v1.0 收口改动落库方案

Date: 2026-05-21
作者视角：仓库内 agent。  
范围：仅本仓库当前工作区的 `git status` 改动。  
原则：不回退任何已有改动；按意图分组拆成可独立 revert 的小 commit；只描述当前实现，不写愿景。

> 关键事实回顾
>
> - 已修改文件 20 个、新增文件 8 个，详见下方 §1。
> - `pytest -q` 已通过 296 项（README 中也已同步）。
> - 本方案不执行 `git add`、不创建 commit、不跑测试，只规划。

---

## 1. 当前工作区盘点

### 1.1 新增文件（8 个，untracked）

| 文件 | 角色 | 谁会用 |
| --- | --- | --- |
| `core/health_reporter.py` | 进程内健康状态聚合（去重、format_summary） | `main.py` 在启动/运行时降级时调用 |
| `core/startup_metrics.py` | 启动阶段耗时收集器（`phase()` 上下文管理器） | `main.py` 包裹关键启动阶段 |
| `tests/test_health_reporter.py` | 上面模块的单测 | 与 `core/health_reporter.py` 同生命周期 |
| `tests/test_startup_metrics.py` | 上面模块的单测 | 与 `core/startup_metrics.py` 同生命周期 |
| `tests/test_clipboard_e2e_local.py` | 本地剪贴板主路径 E2E（fake clipboard → 真 monitor → 真 SQLite） | 守护 v1.0 产品承诺 |
| `PRODUCT_V1.md` | v1.0 产品边界文档 | docs |
| `RELEASE_CHECKLIST.md` | 发布检查表 | docs |
| `RISK_REGISTER.md` | 发布风险台账（P0/P1/P2） | docs |

### 1.2 已修改文件（20 个，按意图分桶）

| 意图分桶 | 涉及文件 |
| --- | --- |
| A. 启动观测 + 健康状态聚合（main.py 内联托盘→集中上报） | `main.py`（部分 hunk） |
| B. 可选增强延迟启动 + 故障隔离（插件 / 云同步 / 文件云同步） | `main.py`（另一部分 hunk）、`tests/test_smoke.py`（部分用例） |
| C. 插件加载完成可订阅刷新 + 商店懒加载 + 设置页说明 | `core/plugin_manager.py`、`ui/settings/plugins_tab.py`、`ui/settings/settings_dialog.py`、`ui/settings/team_tab.py`、`tests/test_settings_tabs_smoke.py`、`tests/test_smoke.py`（`plugins_changed` 断言部分） |
| D. AppContext 懒加载 `cloud_api` + `reset` 同步清空 ctx 引用 | `core/app_context.py`、`core/cloud_api.py`（writeback hunk）、`tests/test_app_context.py` |
| E. 登录页支持自定义服务器地址（自托管 / 私有部署） | `config.py`、`core/cloud_api.py`（`rebuild_cloud_client_for_url` hunk）、`ui/cloud_login_widget.py` |
| F. 标签云同步双向打通（v3.5） | `core/tag_service.py`、`core/repository.py`、`core/cloud_sync_service.py`、`tests/test_cloud_sync_service.py` |
| G. 首启引导跟随真实复制推进 | `ui/main_window.py` |
| H. 主路径单测对齐（监听主路径 + FTS 前缀匹配） | `tests/test_clipboard_monitor.py`、`tests/test_query_parser.py` |
| I. 发布文档索引 + 测试数刷新 | `README.md` |

---

## 2. 拆分原则

1. **意图单一**：一个 commit 只回答一个"为什么"。
2. **可独立 revert**：每个 commit 都应该能单独被 `git revert` 而不让代码不可编译/导入失败。
3. **测试随源代码**：所有新增/调整的测试都和触发其变化的源代码进入同一个 commit。
4. **不动无关文件**：方案里指定的 hunk 之外不要 `git add -p` 进来。
5. **顺序服从依赖**：被 import / 被信号订阅的一方必须先 land。

---

## 3. 推荐落库顺序（共 10 个 commit）

下表的"依赖"列指"该 commit 落地之前哪个 commit 必须已经在 HEAD"。

| # | Commit 主题 | 涉及 hunk / 文件 | 依赖 |
| --- | --- | --- | --- |
| 1 | `feat(infra): 新增 health_reporter / startup_metrics 模块` | 4 个新文件（见 §4.1） | — |
| 2 | `chore(main): 接入启动耗时观测 + 健康状态聚合` | `main.py` 的健康/计时相关 hunks（见 §4.2） | #1 |
| 3 | `feat(startup): 插件 / 云同步 / 文件云同步延迟启动与故障隔离` | `main.py` 的延迟启动 hunks + `tests/test_smoke.py` 的延迟启动用例（见 §4.3） | #2 |
| 4 | `feat(plugin): plugins_changed 信号 + 设置页订阅 + 商店懒加载` | 见 §4.4 | — |
| 5 | `feat(cloud): AppContext 懒加载 cloud_api + reset 同步清空 ctx 引用` | 见 §4.5 | — |
| 6 | `feat(cloud): 登录页支持自定义服务器地址` | 见 §4.6 | — |
| 7 | `feat(tags): 标签云同步双向打通（v3.5）` | 见 §4.7 | — |
| 8 | `feat(ui): 首启引导跟随真实复制推进` | `ui/main_window.py` | — |
| 9 | `test: 本地剪贴板主路径 E2E + 监听主路径单测 + FTS 前缀对齐` | 见 §4.9 | 推荐放在 #1–#8 之后；不阻塞 |
| 10 | `docs: v1.0 产品边界 / 发布检查表 / 风险台账 + README 索引` | 见 §4.10 | 放最后，描述的就是 #1–#9 的现状 |

---

## 4. 每个 commit 的细节

### 4.1 commit #1 — `feat(infra): 新增 health_reporter / startup_metrics 模块`

- **范围**
  - `core/health_reporter.py`（新）
  - `core/startup_metrics.py`（新）
  - `tests/test_health_reporter.py`（新）
  - `tests/test_startup_metrics.py`（新）
- **意图**：先把"工具模块 + 自带单测"独立 land，让后续 `main.py` 改动有可 import 的对象。
- **建议 commit 信息**

  ```
  feat(infra): 新增 health_reporter / startup_metrics 基础模块

  - health_reporter：进程内线程安全的健康状态表，同一 component 只
    保留最新一条；提供 format_summary() 给 UI 聚合提示。
  - startup_metrics：phase() 上下文管理器记录启动阶段耗时，
    format_summary() 在 SC_STARTUP_METRICS=1 时输出。
  - 两者都不依赖 Qt，可单测；尚未接入 main.py。
  ```

- **依赖**：无。
- **回滚**：直接 `git revert`；当前没有调用方，零副作用。

### 4.2 commit #2 — `chore(main): 接入启动耗时观测 + 健康状态聚合`

- **范围（`main.py` 的子集 hunk）**
  - `from contextlib import nullcontext` 与 `_STARTUP_PERF_T0` / `_SC_STARTUP_METRICS` 的新增。
  - `from core.startup_metrics import StartupMetrics` 的新增 import。
  - `ClipboardApp.__init__` 中：`self.startup_metrics = StartupMetrics(...)` 以及围绕 `_init_components` / `_create_tray_icon` / `_create_main_window` / `_init_hotkey` 的 `with self.startup_metrics.phase(...)` 包裹、`startup_metrics.mark("event_loop_ready")`。
  - 新增 `_record_health_issue`、`_flush_startup_health_notifications`、`_on_runtime_health_warning`。
  - 将旧的 `_maybe_warn_mysql_fallback` / `_maybe_warn_degraded_store` **改名为** `_collect_mysql_fallback_health` / `_collect_degraded_store_health`，并改成走 `_record_health_issue` 而不是直接 `showMessage`。
  - `_init_components` 中云端同步启动失败分支改为 `_record_health_issue("cloud_sync", "warning", ...)`。
  - `_init_hotkey` 中 `HOTKEY_AVAILABLE = False` / 无辅助权限 / 注册失败三处加 `_record_health_issue("hotkey", ...)`。
  - `_check_hotkey_listener_alive` 不存活时调 `_on_runtime_health_warning("hotkey", ...)`。
  - `run()` 末尾 `if _SC_DEBUG or _SC_STARTUP_METRICS: logger.warning(f"[startup-metrics] ...")`。
- **不包含**：所有"延迟启动"相关 hunk —— 留给 #3。
- **意图**：把原本散落在 UI 层的"内联托盘 showMessage"汇拢到 `health_reporter`，并把启动各阶段耗时落到 `StartupMetrics`。这一步**不改变默认启动顺序**，便于隔离回归。
- **建议 commit 信息**

  ```
  chore(main): 接入 startup_metrics + health_reporter

  - 用 startup_metrics.phase() 包裹 ClipboardApp 关键启动阶段，
    SC_STARTUP_METRICS=1 时输出 [startup-metrics] 行。
  - 把 MySQL 降级、keyring 降级、云端启动失败、热键不可用/无权限/注册失败
    全部改为 _record_health_issue() 入 health_reporter，启动结束后
    通过 _flush_startup_health_notifications 合并成一条托盘提示。
  - 不改变启动顺序，纯接线 + 改名（_maybe_warn_* → _collect_*_health）。
  ```

- **依赖**：#1（import 才能成功）。
- **回滚风险**：低；revert 后 UI 提示回退到逐条托盘弹窗（每个降级一条）。

### 4.3 commit #3 — `feat(startup): 插件 / 云同步 / 文件云同步延迟启动与故障隔离`

- **范围**
  - `main.py` 剩余 hunk：
    - `_init_components` 中**删除** `self.plugin_manager.load_plugins()` 与对应 `logger.debug` 计时行。
    - 新增 `self.clipboard_monitor.monitor_unhealthy` / `monitor_stopped` 信号到 `_on_runtime_health_warning("clipboard_monitor", ...)` 的连接。
    - `QTimer.singleShot(1500, self._load_plugins_deferred)`。
    - 把 `QTimer.singleShot(20000, self.cloud_sync_service.start)` 改成 `self._start_cloud_sync_deferred`。
    - 文件同步分支从内联 `_start_file_sync` 闭包改为 `QTimer.singleShot(20000, self._start_file_sync_deferred)`，门槛改为 `self.cloud_api and settings().files_sync_enabled`。
    - 新增方法：`_load_plugins_deferred` / `_startup_phase` / `_start_cloud_sync_deferred` / `_start_file_sync_deferred` / `_ensure_file_sync_services`。
    - atexit 注册引入幂等开关 `_cloud_cursor_atexit_registered` / `_file_cursor_atexit_registered`。
  - `tests/test_smoke.py` 中的延迟启动用例：`test_deferred_plugin_loader_calls_load_plugins`、`test_deferred_plugin_loader_reports_failure`、`test_deferred_cloud_sync_start_reports_failure`、`test_deferred_file_sync_start_reports_failure`、`test_deferred_sync_start_registers_atexit_once`、`test_deferred_file_sync_builds_services_on_demand`。
- **不包含**：`tests/test_smoke.py` 中 `test_plugin_manager_load_empty` 关于 `plugins_changed` 信号的 3 行新增 —— 留给 #4。
- **意图**：把"网络 / 文件系统 / 插件"三类可选增强从同步启动剥离，失败时通过 #2 的 `_on_runtime_health_warning` 上报而不阻断本地剪贴板路径，对应 `PRODUCT_V1.md` §"v1.0 Optional Enhancements"。
- **建议 commit 信息**

  ```
  feat(startup): 插件 / 云同步 / 文件云同步延迟启动 + 故障隔离

  - 插件加载从 _init_components 同步路径下放到 QTimer(1500ms)，启动 UI
    不再等待插件。失败上报到 health_reporter("plugin_manager")。
  - 云端同步 / 文件云同步的 start() 包装到 _start_*_deferred()，
    失败时上报 health 而不中断本地剪贴板。
  - 文件云同步服务（entitlement_service + file_repository + FileCloudSyncService）
    改为按需构造，未启用时不创建。
  - atexit 注册改为幂等，避免延迟启动重复注册 cursor 持久化回调。
  - 主路径单测覆盖延迟加载成功/失败与 atexit 一次性注册。
  ```

- **依赖**：#2（用到 `_on_runtime_health_warning`、`_startup_phase` 帮助器、`startup_metrics`）。
- **回滚风险**：中。回滚后启动同步加载插件、20s 后内联启动 file_sync。云端同步逻辑仍能跑，但失败提示退化。

### 4.4 commit #4 — `feat(plugin): plugins_changed 信号 + 设置页订阅 + 商店懒加载`

- **范围**
  - `core/plugin_manager.py`：新增 `plugins_changed = Signal()`；`load_plugins` 末尾 emit；`uninstall_plugin` 卸载成功后 emit。
  - `ui/settings/plugins_tab.py`：构造函数新增 `auto_load_store: bool = True`；订阅 `plugin_manager.plugins_changed` 到 `_refresh_plugin_list`；按 `auto_load_store and not IS_APPSTORE_BUILD` 调 `_load_store_plugins`；新增"插件是可选自动化增强..."的描述 QLabel。
  - `ui/settings/settings_dialog.py`：构造函数加 `auto_load_store: bool = True`，透传给 `PluginsTab`。
  - `ui/settings/team_tab.py`：新增"团队空间是可选协作增强..."的描述 QLabel（与插件描述风格一致，归入同一意图：标记可选增强）。
  - `tests/test_settings_tabs_smoke.py`：`SettingsDialog` 和 `PluginsTab` 构造时传 `auto_load_store=False`；`PluginsTab` 从循环里抽出来单独构造。
  - `tests/test_smoke.py`：`test_plugin_manager_load_empty` 中追加 `pm.plugins_changed` 连接断言 `changed_events == [True]`。
- **意图**：让设置页能在 #3 的延迟插件加载完成后自动刷新，并允许测试 / App Store 构建关闭商店自动联网；同时给设置页加可选增强提示，呼应 `PRODUCT_V1.md`。
- **建议 commit 信息**

  ```
  feat(plugin): plugins_changed 信号 + 设置页订阅 + 商店懒加载

  - PluginManager: 新增 plugins_changed 信号，load_plugins / uninstall_plugin
    完成后 emit。
  - PluginsTab: 订阅 plugins_changed 自动 _refresh_plugin_list；新增
    auto_load_store=True kwarg，关闭可避免测试 / App Store 构建联网拉商店。
  - SettingsDialog: 透传 auto_load_store。
  - PluginsTab / TeamTab: 顶部增加"可选增强"描述，明确失败不影响本地剪贴板。
  - 单测 smoke 走 auto_load_store=False，规避离线 CI 拉商店。
  ```

- **依赖**：无（独立可 land；但与 #3 协同最好）。
- **回滚风险**：低；回滚后设置页插件列表在 1.5s 延迟加载后不会自动刷新（需手动重开窗口）。

### 4.5 commit #5 — `feat(cloud): AppContext 懒加载 cloud_api + reset 同步清空 ctx 引用`

- **范围**
  - `core/app_context.py`：
    - 删除 `from config import ... settings`（保留 `get_cloud_access_token`）、删除 bootstrap 顶层的 `from core.cloud_api import get_cloud_client`。
    - 删除"始终构造 cloud_api"的逻辑。
    - 登录态分支内才 `from core.cloud_api import get_cloud_client` 并构造 `ctx.cloud_api`。
    - 登录态下不再启动 `entitlement_service` 与 `FileCloudSyncService`（这些已转到 #3 的 `_ensure_file_sync_services` 按需构造）；但保留 `file_repository = CloudFileRepository(ctx.db)`，未登录置 None。
  - `core/cloud_api.py` 的 hunks：
    - `get_cloud_client` 捕获 `ctx_for_writeback`，新建 client 后回写 `ctx.cloud_api = client`。
    - `reset_cloud_client` 增加：把 `ctx.cloud_api` 也加入 close 列表并清空。
    - **不包含** `rebuild_cloud_client_for_url` 函数（留给 #6）。
  - `tests/test_app_context.py`：
    - `test_bootstrap_returns_context_with_all_services` 把 `assert ctx.cloud_api is not None` 改为 `assert ctx.cloud_api is None`。
    - 新增 `test_cloud_api_is_created_lazily_and_written_back`、`test_reset_cloud_client_clears_context_reference`、`test_logged_in_bootstrap_defers_file_sync_worker`。
- **意图**：未登录用户不背 HTTP client；登录态启动不再构造 file_sync worker。与 #3 的"按需构造文件同步"配套；本 commit 只保证 AppContext 端不预先实例化。
- **建议 commit 信息**

  ```
  feat(cloud): AppContext 懒加载 cloud_api + reset 同步清空 ctx 引用

  - bootstrap 不再无条件构造 CloudAPIClient；未登录时 ctx.cloud_api = None。
  - 登录态分支只装配 cloud_sync_service 与 file_repository，
    entitlement_service / file_sync_service 推迟到 _ensure_file_sync_services。
  - core.cloud_api.get_cloud_client 在创建实例后回写到 AppContext；
    reset_cloud_client 同步关闭并清空 ctx.cloud_api 引用，避免双单例。
  - 单测覆盖懒加载、写回、reset 清空、登录态延迟 file_sync。
  ```

- **依赖**：无（与 #3 协同最佳，但 #3 的 `_ensure_file_sync_services` 已经具备无 ctx 引用时也能构造的兜底，所以 #5 单独 land 也不会让"延迟文件同步"挂掉）。
- **回滚风险**：中。回滚后未登录启动会重新构造空的 cloud_api 客户端（仅是冗余），#3 中的 `_ensure_file_sync_services` 仍能工作。

### 4.6 commit #6 — `feat(cloud): 登录页支持自定义服务器地址`

- **范围**
  - `config.py`：
    - 删除 `_ALLOWED_API_DOMAINS` 白名单常量，新增 `_LOCAL_API_HOSTS = {"localhost","127.0.0.1","::1"}`。
    - `validate_cloud_api_url` 改写：仅校验"合法 URL + 非本地必须 HTTPS"，不再做域名白名单。
    - 新增 `normalize_cloud_api_url(url)`：trim、去尾斜杠、裸主机补 `https://`。
    - `set_cloud_api_url` 走 `normalize_cloud_api_url` 再 `validate_cloud_api_url`。
  - `core/cloud_api.py`：**仅 `rebuild_cloud_client_for_url` 函数新增** —— 关闭旧 client、清 ctx 引用、用新 base_url 重建并回写。
  - `ui/cloud_login_widget.py`：
    - 顶部新增 `from config import normalize_cloud_api_url, set_cloud_api_url, settings`、`from core.cloud_api import ... rebuild_cloud_client_for_url`、`from urllib.parse import urlparse`。
    - 表单加 `服务器:` `QLineEdit`，默认填 `settings().cloud_api_url or "https://www.jlike.com"`，placeholder `https://www.jlike.com`，含 tooltip。
    - 注册/隐私链接改为 `self.register_label`，跟随 `url_edit.textChanged` 调用 `_refresh_register_links` 重渲染（自托管用户跳对应站点）。
    - `_do_login` 中先 `normalize_cloud_api_url`，与 `settings().cloud_api_url` 不同时 `set_cloud_api_url` + `rebuild_cloud_client_for_url`；即便相同也校对当前 client `base_url` 一致性，必要时重建。
- **意图**：开放服务器地址给自托管 / 私有部署 / 本地调试镜像；继续要求 HTTPS（本地回环除外）以避免 token 中间人。
- **建议 commit 信息**

  ```
  feat(cloud): 登录页支持自定义服务器地址（自托管 / 私有部署）

  - config: 取消域名白名单，改为"合法 URL + 非本地强制 HTTPS"，
    新增 normalize_cloud_api_url（trim、去尾斜杠、裸主机补 https://）。
  - cloud_api: 新增 rebuild_cloud_client_for_url：HttpClient 的 base_url
    构造时固定，切换服务器必须丢掉旧 client。
  - cloud_login_widget: 新增"服务器"输入框，默认值取 settings 当前 URL；
    登录前若 URL 变化则 set_cloud_api_url + rebuild client；注册/隐私
    链接跟随 URL，自托管用户也能跳到对应站点。
  ```

- **依赖**：无（与 #5 互不依赖；#5 已修改 cloud_api.py 的其他 hunk，本 commit 只新增函数）。
- **回滚风险**：中。回滚后用户失去自托管入口，登录强制走 `www.jlike.com`；既有登录用户不受影响。
- **特别提醒**：`core/cloud_api.py` 在 #5 和 #6 中各取一部分 hunk，必须用 `git add -p` 分块；两个 commit 落库后 `git diff origin/main core/cloud_api.py` 应该等于工作区现状。

### 4.7 commit #7 — `feat(tags): 标签云同步双向打通（v3.5）`

- **范围**
  - `core/tag_service.py`：新增 `list_names_for_item(item_id) -> List[str]`，JOIN `clipboard_tags`/`tag_definitions`；表不存在时静默返回 `[]`。
  - `core/repository.py`：在 `ClipboardRepository.__init__` 中 `from .tag_service import TagService; self.tag_service = TagService(self)`（lazy import 避免循环）。
  - `core/cloud_sync_service.py`：
    - `do_pull`：解析 `item_data["tags"]` 收集 `tag_names`；落库后通过 `repository.tag_service.apply_tag_names(item_id, space, tag_names)` 合并（add-only，不删除本地标签）。
    - `do_push`：在 `upload_items` payload 中按 `item.id` 读 `repository.tag_service.list_names_for_item(item.id)`；非空才带 `tags` 字段。
  - `tests/test_cloud_sync_service.py`：新增 `TestCloudSyncTagsRoundTrip` 测试类，4 个用例（push 带 tags、push 无 tags 不带字段、pull 给新条目写标签、pull 合并到已有条目）。
- **意图**：让标签随云同步对称传递，避免设备间标签丢失；保留 add-only 语义防止误删。
- **建议 commit 信息**

  ```
  feat(tags): 标签云同步双向打通

  - tag_service.list_names_for_item: 给同步上行读取条目标签名列表，
    旧库未迁移 clipboard_tags / tag_definitions 时静默返回空。
  - repository: 在构造时挂 self.tag_service，供 _SyncWorker 直接使用。
  - cloud_sync_service:
    * do_push: payload 中按需带 tags=[...]，空列表不发，保持向后兼容。
    * do_pull: 解析云端 tags，调用 apply_tag_names 合并到本地（add-only）。
  - 单测覆盖 push 带 tags / 不带 tags、pull 新建条目写标签、pull 合并已有条目。
  ```

- **依赖**：无。
- **回滚风险**：低。回滚后多端标签退回单向（本地）；老客户端无感。

### 4.8 commit #8 — `feat(ui): 首启引导跟随真实复制推进`

- **范围**：仅 `ui/main_window.py` 的两处 hunk —— `_connect_signals` 中新增 `self.clipboard_monitor.item_added.connect(self._advance_onboarding_after_copy)`，以及 `_advance_onboarding_after_copy` 方法实现。
- **意图**：首启教程的"第 1 步：复制点什么"应由真实剪贴板事件驱动，避免假定用户已完成。
- **建议 commit 信息**

  ```
  feat(ui): 首启引导第 1 步跟随真实剪贴板复制自动推进

  连接 clipboard_monitor.item_added 到 _advance_onboarding_after_copy；
  对话框未开时静默忽略。
  ```

- **依赖**：无。
- **回滚风险**：极低。

### 4.9 commit #9 — `test: 本地剪贴板主路径 E2E + 监听主路径单测 + FTS 前缀对齐`

- **范围**
  - `tests/test_clipboard_e2e_local.py`（新）—— 守护 v1.0 主路径。
  - `tests/test_clipboard_monitor.py`：新增 `TestHandleTextSourceApp.test_main_path_saves_text_emits_signal_and_touches_duplicate`，覆盖"主路径入库 + 信号 + 重复复制置顶不新增"。
  - `tests/test_query_parser.py`：4 处断言由 `"python"` 改为 `"python*"` 等（与现行 `fts_match_expression()` 的前缀匹配实现对齐；源代码本次未改）。
- **意图**：把"本地主路径不能坏"用测试钉死；同时把已经偏离实现的 FTS 断言修正。
- **建议 commit 信息**

  ```
  test: 守护本地剪贴板主路径 + FTS 前缀匹配断言对齐

  - test_clipboard_e2e_local.py: 新增 E2E，fake clipboard → 真 monitor → 真
    SQLite repository，断言 add → search → 重复复制置顶不新增。
  - test_clipboard_monitor.test_main_path_saves_text_emits_signal_and_touches_duplicate:
    覆盖监听器主路径。
  - test_query_parser: FTS 表达式断言改为 keyword* / phrase + keyword* 与
    现有实现一致。
  ```

- **依赖**：建议放在 #1–#8 之后，否则 E2E 跑过时不能验证完整集成。但**单独 land 也安全**。
- **回滚风险**：极低；纯测试代码。

### 4.10 commit #10 — `docs: v1.0 产品边界 / 发布检查表 / 风险台账 + README 索引`

- **范围**
  - `PRODUCT_V1.md`（新）
  - `RELEASE_CHECKLIST.md`（新）
  - `RISK_REGISTER.md`（新）
  - `README.md`（测试数 `61 passed` → `296 passed`、追加"发布收口文档"索引段）
- **意图**：文档反映 #1–#9 之后的实际状态，包含 health_reporter、startup_metrics、E2E、延迟启动、`PluginManager.plugins_changed` 等当前实现。
- **建议 commit 信息**

  ```
  docs: v1.0 产品边界 + 发布检查表 + 风险台账

  - PRODUCT_V1.md: 明确"本地剪贴板历史"为默认体验，云端 / 文件 / 团队 /
    插件为可选增强；启动失败必须降级到本地。
  - RELEASE_CHECKLIST.md: 自动化测试、SC_STARTUP_METRICS 基线、手测、
    降级检查、打包检查、最终发布闸。
  - RISK_REGISTER.md: P0 / P1 / P2 发布风险，引用现有守护代码与单测。
  - README.md: 测试数刷新为 296 passed；新增发布收口文档索引。
  ```

- **依赖**：放最后，描述的就是上方所有 commit 的现状。
- **回滚风险**：零（纯文档）。

---

## 5. 文件级冲突 / 拆分指引

### 5.1 `main.py`（388 行 diff，跨 #2 / #3）

必须用 `git add -p` 把 hunk 分到两个 commit：

- **进 #2 的 hunk 关键字搜索**：`StartupMetrics`、`_STARTUP_PERF_T0`、`_SC_STARTUP_METRICS`、`_record_health_issue`、`_flush_startup_health_notifications`、`_on_runtime_health_warning`、`_collect_mysql_fallback_health`、`_collect_degraded_store_health`、`[startup-metrics]`、`health_reporter`。
- **进 #3 的 hunk 关键字搜索**：`_load_plugins_deferred`、`_start_cloud_sync_deferred`、`_start_file_sync_deferred`、`_ensure_file_sync_services`、`_startup_phase`、`_cloud_cursor_atexit_registered`、`_file_cursor_atexit_registered`、`monitor_unhealthy`、`monitor_stopped`、`QTimer.singleShot(1500, self._load_plugins_deferred)`。

工作流建议：

```powershell
git add -p main.py        # 选 #2 的 hunk
git commit -m "..."
git add -p main.py        # 选 #3 剩余 hunk
git commit -m "..."
git diff main.py          # 期望为空，否则有遗漏
```

### 5.2 `core/cloud_api.py`（跨 #5 / #6）

- **进 #5 的 hunk**：`ctx_for_writeback`、`reset_cloud_client` 内新增的 `clients` 列表与 `ctx.cloud_api = None`。
- **进 #6 的 hunk**：`def rebuild_cloud_client_for_url(...)` 函数整段。

校验：

```powershell
git diff origin/main core/cloud_api.py   # commit #5+#6 后应等于工作区
```

### 5.3 `tests/test_smoke.py`（跨 #3 / #4）

- **进 #4**：仅 `test_plugin_manager_load_empty` 内新增的 3 行（`changed_events`、`pm.plugins_changed.connect(...)`、`assert changed_events == [True]`）。
- **进 #3**：其余 5 个新增的 `test_deferred_*` 用例。

### 5.4 `tests/test_app_context.py` / `tests/test_cloud_sync_service.py` / `tests/test_settings_tabs_smoke.py` / `tests/test_query_parser.py` / `tests/test_clipboard_monitor.py`

均属于单一 commit，无需拆分。

---

## 6. 测试与验证建议（不在本次执行范围）

仅作为提交者的参考：

- 每个 commit 后跑一次 `pytest -q`；目标维持 `296 passed`。
- #3 落地后另跑 `pytest tests/test_smoke.py -q` 与 `python main.py` 手测一次启动顺序。
- #5 落地后跑 `pytest tests/test_app_context.py -q`。
- #6 落地后冒烟登录两次：默认 `https://www.jlike.com`，以及自填 `https://www.jlike.com:9443`（或本地 `http://127.0.0.1:8000`）。
- #7 落地后跑 `pytest tests/test_cloud_sync_service.py -q` 并跨设备触发一次 push/pull。
- #10 落地后无需验证。

---

## 7. 风险与回滚要点

1. **#5 与 #6 共改 `core/cloud_api.py`**：单独 revert 任一 commit 时，剩余 hunk 仍在 `cloud_api.py` 中，可能出现"`rebuild_cloud_client_for_url` 存在但 `reset_cloud_client` 不再清 ctx"或反之的中间态。理论上仍能编译，但请避免选择性回退；要回就把 #5+#6 一起回。
2. **#2 与 #3 共改 `main.py`**：先回 #3 再回 #2。反过来回 #2 会让 `_load_plugins_deferred` 等方法引用未定义的 `_on_runtime_health_warning` 与 `_startup_phase`。
3. **#4 涉及 `PluginManager.plugins_changed` 新信号**：单独回退不会引起调用方报错（设置页对信号的 connect 用了 `hasattr` 守护），但回退后设置页失去自动刷新；可接受。
4. **#7 标签同步**：服务端若未实现 `tags` 字段会忽略；老客户端不受影响。回滚后只是退回到 v3.4 前的单向标签。
5. **#6 服务器地址校验**：若用户已在 `settings.json` 中保存了非白名单域名（例如自托管），`#6` 一旦回退，下次启动 `validate_cloud_api_url` 会拒绝该 URL。需要在回滚后手动改回 `https://www.jlike.com`。
6. **避免误伤已有工作**：当前工作区还有未提交的、跟本次 v1.0 收口无关的改动？盘点结果：没有。`git status` 列出的 28 项都已经在本计划里归桶。如果后续临开 PR 前再有 staged 改动，先 `git stash` 隔离。

---

## 8. 不在本计划范围内（明确不动）

- 不修改 `website/` 任何文件（与本次收口无关）。
- 不动 `plugins/`、`utils/`、`installers/` 等未在 `git status` 中出现的目录。
- 不重新格式化、不修复 LF/CRLF 警告（Git 自动转换无副作用，避免引入噪声 hunk）。
- 不补 `core/query_parser.py` 源代码（本次未改，#9 只对齐断言）。
- 不主动新增 type hint / 重构 / 删注释。

---

## 9. 一键 cheatsheet（供执行者）

```text
# 1) infra
git add core/health_reporter.py core/startup_metrics.py \
        tests/test_health_reporter.py tests/test_startup_metrics.py
git commit -m "feat(infra): ..."

# 2) main.py 健康/计时 hunks
git add -p main.py    # 选 §5.1 中"进 #2"的 hunk
git commit -m "chore(main): ..."

# 3) main.py 延迟启动 hunks + smoke 用例
git add -p main.py    # 剩余 hunk
git add -p tests/test_smoke.py    # 选 §5.3 中"进 #3"的 hunk
git commit -m "feat(startup): ..."

# 4) 插件信号 + 设置页
git add core/plugin_manager.py ui/settings/plugins_tab.py \
        ui/settings/settings_dialog.py ui/settings/team_tab.py \
        tests/test_settings_tabs_smoke.py
git add -p tests/test_smoke.py    # plugins_changed 3 行
git commit -m "feat(plugin): ..."

# 5) AppContext 懒加载
git add core/app_context.py tests/test_app_context.py
git add -p core/cloud_api.py    # §5.2 中"进 #5"的 hunk
git commit -m "feat(cloud): AppContext 懒加载 cloud_api ..."

# 6) 自定义服务器地址
git add config.py ui/cloud_login_widget.py
git add -p core/cloud_api.py    # 剩余 rebuild_cloud_client_for_url
git commit -m "feat(cloud): 登录页支持自定义服务器地址"

# 7) 标签云同步
git add core/tag_service.py core/repository.py core/cloud_sync_service.py \
        tests/test_cloud_sync_service.py
git commit -m "feat(tags): ..."

# 8) 首启引导
git add ui/main_window.py
git commit -m "feat(ui): 首启引导第 1 步跟随真实剪贴板复制自动推进"

# 9) 测试
git add tests/test_clipboard_e2e_local.py \
        tests/test_clipboard_monitor.py tests/test_query_parser.py
git commit -m "test: 守护本地剪贴板主路径 + FTS 前缀匹配断言对齐"

# 10) 文档
git add PRODUCT_V1.md RELEASE_CHECKLIST.md RISK_REGISTER.md README.md
git commit -m "docs: v1.0 产品边界 + 发布检查表 + 风险台账"

# 校验
git status        # 应该 clean
git log --oneline -10
```

---

End of plan.
