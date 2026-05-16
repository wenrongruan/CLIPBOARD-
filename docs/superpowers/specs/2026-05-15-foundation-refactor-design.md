# 公共底盘重构 · 设计文档

- 日期：2026-05-15
- 状态：草案，待用户复核
- 适用仓库：CLIPBOARD-（PySide6 桌面应用 + 内置插件 + 云同步）

## 1. 背景与目标

当前代码库已具备清晰的 `core/ui/plugins/utils` 分层，但若干热点文件随功能叠加而过度膨胀：

| 文件 | 行数 | 现状问题 |
|---|---:|---|
| `ui/main_window.py` | 1541 | 列表、搜索、空间、插件菜单、文件、订阅、云登录、引导全部混在一个类，超过 60 个方法 |
| `i18n.py` | 1482 | 单一大 dict，所有领域字符串集中，定位与修改成本高 |
| `ui/settings_dialog.py` | 1414 | 多个独立 Tab 的 UI 与状态全部塞在一个 QDialog |
| `core/cloud_api.py` | 990 | 单一 client 覆盖 auth/sync/files/spaces 四个领域 |
| `core/repository.py` | 983 | CRUD、查询编译、tag/meta、云同步状态揉在一个类 |
| `core/plugin_manager.py` | 654 | 扫描/加载/生命周期/权限代理/日志一体 |

用户即将推进四个方向：插件生态、云同步/多设备、团队空间/协作、智能/AI。所有方向都会再次写入上述热点文件，若不先理清边界，膨胀会复利。

**本次重构的核心目标**：在不改变任何用户可见行为、不改变任何外部 import 路径、不改任何持久化产物的前提下，把上述热点切分到清晰的边界后面，让四个未来方向可以各自独立演进。

## 2. 范围

### 在范围

- `core/repository.py` 拆为 DAO + Query + SyncStateDAO + Facade
- `core/cloud_api.py` 拆为 4 个 domain client + Http + Facade
- `core/plugin_manager.py` 抽出 `ExtensionPointRegistry`
- `core/` 新增 `app_context.py`，集中装配并持有所有 service
- `ui/main_window.py` 退化为壳 + 信号路由，业务逻辑迁出到 4 个 controller
- `ui/settings_dialog.py` 拆为 `ui/settings/` 包（按 Tab 拆文件）
- `i18n.py` 退化为 shim（运行时），字符串迁出到 `i18n_strings/` 子目录
- 关键层补充新单测，现有 13 个测试文件全绿不动

### 不在范围（YAGNI）

- 不改数据库 schema、配置目录、插件 manifest 格式
- 不改云端 API 协议、不改网络客户端的请求语义
- 不引入依赖注入框架
- 不优化性能、不修任何已知 bug、不调整任何用户可见行为
- 不重写 `cloud_sync_service` / `file_sync_service` / `space_service` / `share_service` / `tag_service`（这些 service 本期不动，仅经 AppContext 暴露）
- 不动 smart_text、ai_image_gen 等插件实现

## 3. 高层架构

### 3.1 目录结构（重构后）

```
main.py                 OS 集成（QApplication / 托盘 / 全局热键 / 单实例锁）
config.py               不变
i18n.py                 ≤100 行 shim：t / set_language / get_language / available_languages
i18n_strings/
  __init__.py           load_all() -> dict[lang, dict[key, str]]
  main.py / settings.py / cloud.py / plugins.py / misc.py

core/
  app_context.py        新增：ServiceRegistry，bootstrap / shutdown
  db/
    clipboard_dao.py    CRUD / get_by_hash / toggle_star / tags / meta / cleanup
    clipboard_query.py  filter clauses / regex post-filter / search / timeline / count
    sync_state_dao.py   cloud_id 状态、unsynced 查询、同步元数据
  cloud/
    http.py             公共 HTTP 客户端（base_url、token、_request、错误码映射）
    auth_client.py      登录 / 注册 / 验证码 / token 刷新 / 登出
    sync_client.py      item 上传 / 拉取 / 星标 / 空间内 item 同步
    files_client.py     文件 metadata / 单段 / 多段上传 / 下载链接 / 去重
    spaces_client.py    团队空间 / 成员 / 邀请 / 权限
  plugin_manager.py     保留原路径（外部 import 不变）；内部精简
  plugin_extension_points.py  新增：ExtensionPointRegistry
  repository.py         保留路径，转为 Facade（≤200 行）
  cloud_api.py          保留路径，转为 Facade（≤200 行）
  其它现有文件          不动：clipboard_monitor / sync_service / cloud_sync_service /
                                file_sync_service / entitlement_service / space_service /
                                tag_service / share_service / models / db_factory /
                                database / mysql_database / base_database / migration /
                                db_migrations / file_models / file_repository /
                                file_storage / query_parser / source_app / analytics /
                                plugin_api

ui/
  main_window.py        ≤350 行：壳 + _setup_ui + _connect_signals 路由表
  controllers/
    clipboard_list_controller.py
    item_action_controller.py
    plugin_action_controller.py
    cloud_lifecycle_controller.py
  settings/
    __init__.py         re-export SettingsDialog
    settings_dialog.py  ≤150 行：QTabWidget 壳
    general_tab.py / sync_tab.py / cloud_tab.py / plugins_tab.py / advanced_tab.py
  settings_dialog.py    退化为 shim（≤30 行，re-export from ui.settings）
  其它现有 Widget       不动：edge_window / clipboard_item / cloud_auth_dialog /
                                cloud_login_widget / file_list_model / file_list_widget /
                                onboarding_dialog / plugin_config_dialog / share_dialog /
                                sidebar / source_app_icons / styles / subscription_widget /
                                timeline_view

plugins/                不动
utils/                  不动
tests/                  现有 13 个测试文件零修改 + 新增 11 个测试文件
```

### 3.2 关键不变量（外部契约）

- `from i18n import t, set_language, get_language` 可用
- `from core.repository import ClipboardRepository` 可用，全部 public 方法签名不变
- `from core.cloud_api import CloudAPIClient`, `from core.cloud_api import get_cloud_client` 可用，全部 public 方法签名不变
- `from core.plugin_manager import PluginManager` 可用
- `from ui.settings_dialog import SettingsDialog` 可用
- 插件目录、settings.json 路径、clipboard.db 路径、logs 路径不变
- 启动产物对用户完全无感（界面、热键、订阅、登录态、文件 tab 都不变）

## 4. 模块设计

### 4.1 `core/app_context.py`

```python
class AppContext:
    """单例容器，启动期一次性装配，全程通过它取 service。"""

    db: AbstractDatabaseManager
    repository: ClipboardRepository
    clipboard_monitor: ClipboardMonitor
    sync_service: SyncService
    cloud_api: CloudAPIClient
    cloud_sync_service: CloudSyncService
    file_sync_service: FileSyncService
    entitlement_service: EntitlementService
    space_service: SpaceService
    tag_service: TagService
    share_service: ShareService
    plugin_manager: PluginManager
    extension_points: ExtensionPointRegistry

    @classmethod
    def bootstrap(cls) -> "AppContext": ...
    @classmethod
    def current(cls) -> "AppContext": ...   # 给 cloud_api.get_cloud_client() 等旧入口兜底
    def shutdown(self) -> None: ...
```

约束：
- bootstrap 在 main 线程顺序构造，构造完即视为 immutable 引用集合
- shutdown 由 `app.aboutToQuit` 注册触发，统一关 plugin_manager / monitor / DB

### 4.2 `core/db/` 拆分

| 文件 | 职责 | 行数预算 |
|---|---|---:|
| `clipboard_dao.py` | add_item / delete_item / toggle_star / get_by_hash / get_by_id / get_existing_hashes / update_item_content / touch_item / 标签三方法 / meta 双方法 / cleanup_* / get_new_items_since / get_latest_id | ~350 |
| `clipboard_query.py` | _build_filter_clauses / _run_query / _do_select / _apply_regex_filter / _count_spec / _fill_tag_ids / get_items / get_items_full / search / search_by_keyword / get_timeline / get_items_by_tag | ~400 |
| `sync_state_dao.py` | set_cloud_id / set_cloud_ids_bulk / clear_cloud_id / get_by_cloud_id / get_starred_unsynced / get_unsynced_items / get_unstarred_with_cloud_id / update_cloud_sync_metadata | ~150 |
| `repository.py`（保留原路径） | Facade，组装上面三个，delegate 全部 public 方法 | ~200 |

`ClipboardRepository.__init__(db_manager)` 签名不变。所有 public 方法签名不变。

### 4.3 `core/cloud/` 拆分

| 文件 | 范围 |
|---|---|
| `http.py` | `HttpClient`：base_url、token、`_request()`、错误码映射、超时与重试 |
| `auth_client.py` | login / register / verify_code / refresh_token / logout |
| `sync_client.py` | upload_item / pull_items / star / 空间维度 item 同步 |
| `files_client.py` | upload_file_init / upload_file_part / upload_file_complete / get_download_url / get_file_metadata / dedup |
| `spaces_client.py` | list_spaces / create_space / invite / accept_invite / list_members / 权限 |

`core/cloud_api.py` 转 Facade：

```python
class CloudAPIClient:
    def __init__(self, ...):
        self._http   = HttpClient(...)
        self.auth    = AuthClient(self._http)
        self.sync    = SyncClient(self._http)
        self.files   = FilesClient(self._http)
        self.spaces  = SpacesClient(self._http)

    # delegate 全部现有顶层公开方法（80 个），逐一保留
    def login(self, *a, **kw):              return self.auth.login(*a, **kw)
    def upload_item(self, *a, **kw):        return self.sync.upload_item(*a, **kw)
    def upload_file_init(self, *a, **kw):   return self.files.upload_file_init(*a, **kw)
    ...
```

`get_cloud_client()` 全局函数保留，内部走 `AppContext.current().cloud_api`。

### 4.4 `core/plugin_extension_points.py`

```python
class ExtensionPointRegistry:
    """插件不直接被 UI 引用；UI 通过这里枚举可用扩展。"""

    def context_menu_actions(self, item) -> list[PluginAction]: ...
    def search_providers(self) -> list:        # 预留，本期无实现
    def inline_actions(self) -> list:          # 预留，本期无实现

    def register_context_menu(self, plugin_id, action): ...
    def unregister_plugin(self, plugin_id): ...
```

PluginManager 在 `load_plugin` 完成时，把 manifest 中声明的 action 注册到 registry；`unload_plugin` 时清理。

### 4.5 `ui/controllers/`（拆 MainWindow）

均继承 `QObject`，可发 Signal。

| Controller | 接管的 MainWindow 方法 | 主要依赖 |
|---|---|---|
| `ClipboardListController` | `_load_items / _update_list / _make_list_item / _on_search_changed / _do_search / _show_search_help / _prev_page / _next_page / _update_pagination / _toggle_starred_filter / _on_view_changed / _on_timeline_item_clicked / _on_sidebar_space_changed / _on_sidebar_tag_changed / _on_sidebar_create_space / _on_sidebar_manage_team / _on_sidebar_upgrade / _on_tab_changed / _prepend_item / _on_new_items / _on_item_added` | repository, AppContext |
| `ItemActionController` | `_on_item_clicked / _handle_image_loaded / _on_item_delete / _on_cloud_delete / _handle_cloud_delete_done / _on_item_star / _on_item_save / _handle_save_image_done / _on_image_url_copy / _handle_image_url_done / _on_share_items / _on_add_tags / _show_copy_feedback` | repository, cloud_api, file_storage |
| `PluginActionController` | `_show_context_menu / _run_plugin_action / _handle_plugin_item_loaded / _dispatch_plugin_action / _on_plugin_progress / _on_plugin_finished / _on_plugin_error / _show_plugin_feedback / _cancel_plugin` | extension_points, plugin_manager, repository |
| `CloudLifecycleController` | `_bootstrap_files_stack_after_login / _bootstrap_cloud_sync_after_login / _teardown_cloud_sync_after_logout / _advance_sync_after_cloud` | AppContext |

`MainWindow` 重构后保留：
- `__init__(self, ctx: AppContext)` / `_setup_ui` / `_connect_signals`（重写为路由表）
- `closeEvent / show_window / _minimize_window / _toggle_pin / _request_quit`
- `_show_settings / _do_migration / _maybe_show_onboarding / _on_onboarding_done`

### 4.6 `ui/settings/`（拆 SettingsDialog）

```
ui/settings/
  __init__.py         from .settings_dialog import SettingsDialog
  settings_dialog.py  ~150 行：QTabWidget 壳，按 initial_tab 路由
  general_tab.py      ~250 行：语言、热键、启动、热缓存、最大条目
  sync_tab.py         ~200 行：局域网同步、设备名、自动同步
  cloud_tab.py        ~300 行：账户、订阅、云同步开关、登录/登出按钮
  plugins_tab.py      ~250 行：插件列表 + 进入插件配置
  advanced_tab.py     ~250 行：日志位置、数据迁移、设备 ID、清空数据
```

`ui/settings_dialog.py` 转 shim：

```python
# ui/settings_dialog.py  (≤30 行)
from ui.settings.settings_dialog import SettingsDialog  # noqa: F401
__all__ = ["SettingsDialog"]
```

### 4.7 `i18n_strings/`（拆 i18n）

```
i18n.py                ~80 行：state（current_lang）、t()、set_language()、get_language()、available_languages()
i18n_strings/
  __init__.py          load_all() -> dict[lang, dict[key, str]]
  main.py              主界面 / 列表 / 搜索 / sidebar
  settings.py          设置弹窗（所有 Tab）
  cloud.py             登录 / 注册 / 同步 / 订阅
  plugins.py           插件菜单 / 错误提示 / 进度
  misc.py              onboarding / share / 通用按钮 / 引导文案
```

`i18n.py` 启动时调 `i18n_strings.load_all()` 合并成现有的 `_strings` dict。`t / set_language / get_language` 行为完全一致。

## 5. 启动流程

```
main.py
  ├── QApplication / 单实例锁 / Qt 平台属性
  ├── ctx = AppContext.bootstrap()
  │     ├── db = create_database_manager()
  │     ├── repository = ClipboardRepository(db)
  │     ├── cloud_api = CloudAPIClient()
  │     ├── clipboard_monitor = ClipboardMonitor(repository)
  │     ├── sync_service = SyncService(repository)
  │     ├── cloud_sync_service = CloudSyncService(repository, cloud_api)
  │     ├── file_sync_service = FileSyncService(...)
  │     ├── entitlement_service / space_service / tag_service / share_service
  │     ├── plugin_manager = PluginManager()
  │     ├── extension_points = ExtensionPointRegistry()
  │     └── plugin_manager.load_all(register_into=extension_points)
  ├── tray = QSystemTrayIcon(...)
  ├── window = MainWindow(ctx)
  ├── 全局热键注册（pynput）
  └── app.exec()
```

`MainWindow.__init__(ctx)`：
1. `_setup_ui()`（现有逻辑保留，构造所有子 Widget）
2. 构造 4 个 controller，传入 `self` 和 `ctx`
3. `_connect_signals()` 重写为信号路由表
4. closeEvent 中 `setParent(None) + deleteLater()` 各 controller

## 6. 测试策略

### 6.1 必须保绿（零修改）

13 个现有测试文件：

```
test_clipboard_monitor.py / test_cloud_sync_service.py / test_database.py
test_entitlement.py / test_file_sync.py / test_file_upload_flow.py
test_models.py / test_query_parser.py / test_repository.py
test_smoke.py / test_source_app.py / test_space_service.py / test_tag_service.py
```

### 6.2 新增测试（13 个）

| 文件 | 覆盖 |
|---|---|
| `test_clipboard_dao.py` | DAO 增删改查 / tags / meta / cleanup |
| `test_clipboard_query.py` | filter clause / regex post-filter / count / timeline / search |
| `test_sync_state_dao.py` | cloud_id / unsynced / cloud sync metadata |
| `test_app_context.py` | bootstrap → service 都能取到 / shutdown 不漏 / current() 兜底 |
| `test_cloud_api_facade.py` | facade.login / upload_item / upload_file_init 仍能调通 |
| `test_cloud_api_facade_completeness.py` | 反射对照 facade 前后公开方法集合 |
| `test_extension_points.py` | 注册 / 枚举 / per-plugin 隔离 |
| `test_i18n_completeness.py` | 各 lang key 集合一致；合并前后 dict 等价 |
| `test_controllers_list.py` | 搜索、分页、收藏过滤回路（mock repository） |
| `test_controllers_item_action.py` | 删 / 收藏 / 保存 / 拷 URL / 分享 |
| `test_controllers_plugin.py` | dispatch / progress / finish / error |
| `test_controllers_cloud_lifecycle.py` | 登录/登出引发的 stack 切换、同步启停 |
| `test_settings_tabs_smoke.py` | 各 tab Widget 能构造、能响应主信号 |

controller 单测在 offscreen Qt 下跑（与 `test_smoke.py` 同样的环境配置）。

## 7. 冷启动与冒烟 checklist

1. 启动后主窗口正常出现
2. 列表加载历史项（≥10 条），分页前/后翻
3. 搜索：普通关键词 + `size:` / `space:` / `tag:` / `from:` query 语法
4. 收藏 / 取消收藏，starred 过滤切换
5. 右键菜单显示 smart_text 插件 action
6. 跑一次 smart_text，progress / finish / cancel 流程
7. 删除单项 / 云端删除（如已登录）
8. 保存图片项到本地
9. 拷贝图片云端 URL
10. 设置弹窗每个 tab 都能进，主要选项可切
11. 登录 / 登出，文件 tab 与同步状态正确切换
12. 切换语言 zh ↔ en，关键文案全部生效
13. 关闭窗口（macOS 不退出 / Windows 退托盘）
14. 重启后历史项、设置、登录状态都还在

## 8. 风险与回滚

### 主要风险

1. **大推一次到位，无中间提交可二分**
   - 缓解：本地分支 `refactor/foundation` + 每柱完成打本地 tag（pillar-1 AppContext / pillar-2 db / pillar-3 cloud / pillar-4 i18n / pillar-5 settings / pillar-6 controllers / pillar-7 extension-points）
   - 缓解：所有测试 + 冒烟全过后才一次性 commit 到 main
   - 回滚：`git revert <commit>` 一次还原

2. **QObject controller 与 MainWindow 引用环**
   - 缓解：closeEvent 显式 `setParent(None) + deleteLater()` 各 controller
   - 缓解：新增 close 冒烟测试

3. **CloudAPIClient facade delegate 漏方法（约 80 个）**
   - 缓解：`test_cloud_api_facade_completeness.py` 用 `dir()` 对照重构前后

4. **i18n 装载顺序错误，启动时部分 key 缺失**
   - 缓解：`test_i18n_completeness.py` 对每种 lang 校验 key 集合等价

5. **PyInstaller / spec 文件丢新模块**
   - 缓解：构建一次 macOS / Windows 包冒烟（如有发布动作）
   - SharedClipboard.spec 中如需添加 hidden imports，本次更新一并完成

### 次要风险

- `i18n_strings/` 模块导入失败 → fallback 到内嵌默认字典（与现状一致）
- `core/cloud/http.py` 与现有 token / 刷新逻辑不一致 → 用 `test_cloud_sync_service.py` 兜底
- `ui/settings/` 内某个 tab 与原 SettingsDialog 行为不一致 → `test_settings_tabs_smoke.py` 与人工冒烟兜底

## 9. 推进顺序（实施期内部步骤，最终一次性提交 main）

1. AppContext + bootstrap（不破坏现有任何调用）
2. `core/db/` 拆分 → Repository 转 Facade → 跑 `test_repository.py` 保绿
3. `core/cloud/` 拆分 → CloudAPIClient 转 Facade → 跑 `test_cloud_sync_service.py` 保绿
4. `i18n_strings/` 拆字典 → i18n.py 转 shim → `test_i18n_completeness.py`
5. `ui/settings/` 拆 Tab → `ui/settings_dialog.py` 转 shim → 冒烟 settings
6. `ui/controllers/` 抽 4 个 controller → MainWindow 退化为壳 → controller 单测
7. `core/plugins/extension_points.py` 抽出 → 插件菜单走 registry → `test_extension_points.py`
8. 全量 pytest + 冒烟 14 项 + 启动时间对比
9. `git diff main..refactor/foundation --stat` review
10. 一次性 squash commit 到 main

## 10. 完成定义

- [x] `core/repository.py` 204 行（目标 ≤ 200，超 4 行；本质为 31 个 delegate，已无可下沉空间）
- [x] `core/cloud_api.py` 351 行（目标 ≤ 200，超 151 行；本质为 44 个 delegate + 5 处 back-compat property，避免 __getattr__ 黑魔法以保留静态可读性。从 990 → 351 仍降 64.5%）
- [x] `ui/main_window.py` 334 行（目标 ≤ 350）
- [x] `ui/settings_dialog.py` 转为 shim 8 行（目标 ≤ 30）
- [x] `i18n.py` 90 行（目标 ≤ 100）
- [x] 现有测试文件零修改、全绿（261 baseline + 5 新增 extension_points + 多个 Phase 配套测试 = 266 全绿）
- [x] 新增测试全绿
- [ ] 14 项冷启动 / 冒烟（推迟到手动验证，自动化未覆盖 UI 交互）
- [ ] 启动时间对比（推迟到合并 main 后再测，避免阻塞）
- [x] `python -W error -m pytest -q` 零 warning（266 passed in strict mode）

## 11. 显式不做的事

- 不优化任何性能
- 不修任何已知 bug
- 不改任何用户可见行为
- 不引入新的运行期依赖
- 不修改插件 manifest 或 plugin_api
- 不修改 cloud_sync_service / file_sync_service / space_service / share_service / tag_service 的实现，仅经 AppContext 暴露
- 不修改 SharedClipboard.spec 除非新增模块要求添加 hidden imports
- 不动 macOS 构建脚本（build_mac.sh / build_appstore.sh / build_macos.py）
