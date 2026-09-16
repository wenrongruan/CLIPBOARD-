# SharedClipboard 代码全面审查报告

> **修复状态（2026-09-16 修复完成后追加）**：本报告的 P0 全部 8 条、P1 全部 13 条、P2 中 10 条已修复，
> 全量测试通过（402 用例，含新增 18 条回归用例 `tests/test_review_fixes_20260916.py`）。
> 修复明细见文末「修复完成记录」。

- **审查日期**：2026-09-16
- **审查范围**：`/Users/macair/Documents/python/CLIPBOARD-` 客户端源码（`main.py` / `config.py` / `core/` / `ui/` / `plugins/` / `utils/` / `scripts/` / `tests/` / 构建脚本），并对照同仓库后端 `website/api/` 校验接口契约
- **代码规模**：约 32,400 行 Python（不含 `venv/` `dist/` `build/` `website/` 前端）
- **审查方式**：静态审查（模块分工并行深挖）+ 关键结论**逐条回到源码/后端复核取证**
- **本次动作**：**只读审查，未修改任何源码**（本报告文件为新增，非代码改动）

---

## 一、结论速览

| 等级 | 数量 | 含义 |
|---|---|---|
| **P0** | **8** | 会导致数据永久丢失、进程崩溃、任意代码执行或凭据窃取 |
| **P1** | **13** | 功能失效、静默错误、性能瓶颈、安全纵深缺失 |
| **P2** | **15** | 可维护性、一致性、体验细节 |

**一句话结论**：代码整体工程质量在中上水平（SQL 全部参数化无注入、DB 连接已 `threading.local()` 隔离、密钥落盘 0600 且原子写、图标缓存有 LRU 上限）——**基础面是干净的**。但存在三类**致命且已可复现证据**的问题：

1. **云同步链路的字段名与后端契约断裂**，导致"跨设备文件永远同步不进来"且游标不可逆推进；
2. **数据库迁移功能整条链路是坏的，却向用户报告"迁移成功"**——用户据此删除旧库即全量丢失历史；
3. **插件权限代理可被一行代码绕过**，配合用户插件目录无签名加载，构成完整的本地提权/凭据窃取路径。

---

## 二、P0 —— 必须立即修复（8 条）

### P0-1 客户端读的字段名与后端返回不一致 → 跨设备文件永久同步失败

**位置**：`core/file_sync_service.py:91`（对照 `website/api/controllers/FileController.php:892-908`）

```python
# 客户端
sha = srv.get("content_sha256", "") or ""
```
```php
// 后端 serializeFileRow() 实际返回
'cloud_id' => (int)$row['id'],
'sha256'   => $row['content_sha256'],   // 注意：键名是 sha256，不是 content_sha256
```

**影响**：`sha` 恒为 `""` → 走到 `core/file_sync_service.py:113` 的 `if not ... re.fullmatch(r"[a-fA-F0-9]{64}", sha) is None: continue`，**所有非删除条目 100% 被跳过**。更严重的是 `max_id = cid` 在 **第 89-90 行先于任何校验执行**，游标已经越过这些条目，`since_id` 不再回退 → 这些数据**不可恢复**。用户表现为"只能删不能收"：删除 tombstone 走独立分支仍生效，新增文件永远拉不进来。

**建议**：
```python
sha = (srv.get("content_sha256") or srv.get("sha256") or "")
```
并且**把 `max_id` 的推进改为只对处理成功的条目计算**（失败项进重试计数器，参考 `cloud_sync_service.min_retryable_skip` 的做法），否则任何一次解析异常都会烧掉游标。

---

### P0-2 云同步推送进入永久重传循环，且向用户上报虚假成功

**位置**：`core/cloud_sync_service.py:215-234`（对照 `ClipboardController.php:149-163`）

后端是 `INSERT IGNORE`（`uk_user_hash` 唯一键），且 **仅在 `$rowCount > 0` 时才追加 `$createdItems[]`**。因此重试时（服务端已落库、回包无 id）：

```python
server_items = self.cloud_api.upload_items(upload_items)   # 命中去重 → 返回 []
...
cloud_id_pairs = []                                        # 本地 cloud_id 永远为 NULL
uploaded_count = len(server_items) if server_items else len(batch)   # ← 还谎报成功
```

**影响**：`_load_unsynced_from_db` 按 `cloud_id IS NULL` 捞取 → 每 10 秒重传同一批（图片条目还会重传二进制），无限循环。而 `ClipboardController.php:234` 的 `AND device_id != :device_id` 意味着**本设备上传的条目永远拉不回来补 `cloud_id`，循环无法自愈**。同时 UI 弹出"上传成功 N 条"。

**建议**：
- 后端：命中 `INSERT IGNORE` 时用 `ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)` 回填已有 id，或 SELECT 回查后一并返回；
- 客户端：成功数改用 `len(cloud_id_pairs)`，并为重试项加 attempt 上限 + 指数退避。

---

### P0-3 去重键不含 space_id → 跨空间误绑 cloud_id，可删除团队数据

**位置**：`core/cloud_sync_service.py:93-121` + `core/db/clipboard_dao.py:149-153`

`get_existing_hashes()` 的 `WHERE content_hash IN (...)` 无 space 过滤，命中后直接 `update_cloud_sync_metadata(existing.id, cloud_id=server_id)`。

**影响**：同步团队空间时，若个人空间已有同 hash 条目，团队条目不会在本地出现（该空间永久缺条目），反而把团队的 `server_id` 挂到个人条目上。用户随后点"删除云端副本"（`ui/controllers/item_action_controller.py:145-174`）会 DELETE 掉**团队那条记录，波及所有成员**。

**建议**：去重判据改为 `(space_id, content_hash)` 复合键。

---

### P0-4 数据库迁移 100% 静默失败，却弹窗提示"迁移完成"

**位置**：`core/migration.py:9-15`（对照 `core/models.py:69-83`）

```python
_INSERT_SQL = """INSERT OR IGNORE INTO clipboard_items (
    content_type, text_content, image_data, image_thumbnail,
    content_hash, preview, device_id, device_name,
    created_at, is_starred                      # ← 10 列 / 10 个 ?
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
```
而 `to_db_tuple()` 自 v3.4 起返回 **13** 个值（末尾多了 `space_id / source_app / source_title`）。异常被吞：
```python
except Exception as e:
    logger.warning(f"批量迁移失败: {e}")   # 不上抛、不计数
```
另：`INSERT OR IGNORE` 是 SQLite 专有语法，目标为 MySQL 时必然语法错误。

**影响**：用户在 `ui/main_window_helpers.py:236` 触发迁移后，进度条走完、弹窗提示"迁移完成 N 条"（N=0），**目标库实际一条未写入**。用户据此删除旧库 → 剪贴板历史全部丢失。

**建议**：按 `to_db_tuple()` 长度生成列与占位符；按方言选择 `INSERT IGNORE`（MySQL）；批量失败改为向上抛 `finished_err`，绝不用 warning 静默。

---

### P0-5 插件权限代理可被 `proxy._real` 一行绕过

**位置**：`core/plugin_manager.py:41-59`

```python
object.__setattr__(self, "_real", real_client)     # 写进实例 __dict__

def __getattr__(self, name):                        # 仅在常规查找失败时触发
    if name.startswith("_") and name != "__class__":
        raise PermissionError(...)
```

`_real` 就在实例 `__dict__` 里，`__getattr__` **永远不会为它触发** → `proxy._real` 直接返回真实 `CloudAPIClient`。同时代理只拦截带 `_plugin_permission` 标注的属性，`CloudAPIClient.get_tokens()`（返回 access + refresh token）等未标注方法**默认放行**。

**影响**：manifest 权限模型形同虚设，任意插件一行代码即可导出用户长期 token 并离线复用云端身份。这是"默认允许"而非"默认拒绝"。

**建议**：改用 `__getattribute__` 拦截（或用 `__real` 私有名 + 显式方法白名单），只放行显式授权的方法名集合，`get_tokens/set_tokens/refresh_token` 一律排除；加一条测试断言「facade 公开方法 ∩ 未标注权限 == 空集」。

---

### P0-6 用户插件目录无签名/白名单即被 exec（非 MAS 构建）

**位置**：`core/plugin_manager.py:565-589`

```python
user_dir = get_user_plugins_dir()      # ~/Library/Application Support/SharedClipboard/plugins
if user_dir != builtin_dir:
    dirs.append(user_dir)
...
spec.loader.exec_module(module)        # 直接执行
```

**影响**：任何能写该目录的进程（同用户即可，无需 root）下次启动即获得与主程序同等权限的任意代码执行，可全量读取剪贴板历史（含密码/token）并常驻。`IS_APPSTORE_BUILD` 只挡住这一条路径，**非 MAS 构建完全裸奔**。另：`load_plugins()` 不看 `is_plugin_enabled`，用户在设置里"禁用"后重启前 `on_load()` 仍会执行一次。

**建议**：插件首次加载前做 manifest + 代码哈希白名单（用户显式确认后写入受保护清单）；加载前校验目录属主与非 group/other 可写；禁用状态在加载前判断。

---

### P0-7 配置文件单个字段类型异常 → 启动即崩溃且不可自愈

**位置**：`config.py:369-380` + `config.py:203-255`

```python
except (json.JSONDecodeError, IOError) as e:   # 只兜底这两类
```
但 `_snapshot_from_dict` 内部是裸强转：`port=int(data.get("mysql_port", 3306))`、`max_items=int(...)`、`last_sync_id=int(...)` 等十余处。

**影响**：`settings.json` 里任意整数字段变成 `null` 或字符串（手改、旧版本写入、跨版本残留），`int(None)` 抛 `TypeError`，**不在兜底范围内**，异常穿透 `settings()` → 应用闪退。JSON 本身没损坏，所以走不到恢复分支——**没有任何回到默认值的路径**，用户每次启动都崩，只能手动编辑 JSON。

**建议**：兜底放宽到 `(json.JSONDecodeError, OSError, ValueError, TypeError, AttributeError)`；`_snapshot_from_dict` 改为逐字段容错（加 `_as_int(v, default)` 助手）。

---

### P0-8 迁移 QThread 强引用被覆盖 → `QThread: Destroyed while thread is still running` 直接 abort

**位置**：`ui/main_window_helpers.py:243-266`

```python
window._migration_worker = worker    # 单一槽位，重复迁移被新 worker 覆盖
worker.start()
```
函数每次"设置 → 改数据库 → 确认迁移"都会重入，旧 worker 失去唯一 Python 引用；且 finished 后从不 `deleteLater`。

**影响**：旧线程仍在 `isRunning()` 时被 GC 析构 → Qt 触发 `qFatal` **直接 abort 整个进程**（项目自己在 `plugins_tab._track_thread` 里已记录过这个坑）。此外每次迁移泄漏一个 QThread。

**建议**：复用 `_ACTIVE_THREADS` 模式（finished 时 discard + deleteLater），并在启动前拦截重入。

---

## 三、P1 —— 高优先级（13 条）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 1 | `core/cloud/http.py:370-381` | 遇到 401 就无差别重发原请求，无方法与路径白名单 | `/api/v1/ai/generate` 等扣费接口被重复提交，**重复扣积分** |
| 2 | `ui/controllers/item_action_controller.py:163-168` | `api.delete_item()` 返回值未判断，直接 emit 成功 | 网络失败也清本地 `cloud_id`，与 P0-2 叠加形成重传循环 |
| 3 | `core/cloud/files_client.py:104-105` | presigned URL（含 `OSSAccessKeyId` 与签名）进异常文本并写库 | 签名随 DB / 日志 / 崩溃上报外泄，过期前可直接 PUT/GET |
| 4 | `core/cloud/http.py:482` | 存储 URL 白名单放行明文 `http` | 签名与文件内容明文过链路 |
| 5 | `core/db/clipboard_query.py:311-320` | LIKE 回退未转义 `%` `_` 且无 `ESCAPE`；MySQL 上 `_has_fts=False` 是唯一搜索路径 | 语义错误 + LONGTEXT 全表扫描 |
| 6 | `core/db/clipboard_query.py:296-305` | FTS5 MATCH 表达式无语法兜底 | 搜 `AND`、`*`、`a**b` 抛 `OperationalError`，冒泡后**弹"加载失败"并清空整个列表** |
| 7 | `core/file_storage.py:24-29` | `sandbox_path_for(sha)` 未校验直接拼路径 + `mkdir(parents=True)` | 当前调用链已做 hex64 校验，**属纵深防御缺失**；一旦新增未校验路径即可穿越容器写任意文件 |
| 8 | `core/db_migrations.py:83-93` | WAL 模式下用 `shutil.copy2` 备份，未拷 `-wal` 也未 checkpoint | 备份是残缺快照，且每次都被覆盖，回滚点不可靠 |
| 9 | `utils/secure_store.py:149-169` | 升级到 keyring 后不清理配置文件里的旧 base64 副本 | 旧 token 永久留存；钥匙串失效时静默回落到过期 token |
| 10 | `main.py:185` + `i18n.py:42-45` | 切换语言后托盘菜单不重建，`set_language` 对非法值静默忽略 | 改语言不重启部分不生效，用户感觉"选了没反应" |
| 11 | `main.py:715-731` | `_check_hotkey_listener_alive` 定义了但**从未被调用** | pynput 缺权限时静默失败，用户按热键没反应却无任何提示 |
| 12 | `ui/controllers/clipboard_list_controller.py:213-231` | `takeItem()` 返回值丢弃，且未先 `removeItemWidget()` | Qt 明确要求手动删除；该函数**每次复制都调用**，稳定累积孤儿行对象与残留控件 |
| 13 | `plugins/ai_image_gen/plugin.py:45-61` | 执行仓库外自动探测到的 `chat_image_gen.py` | 开发机场景下可被劫持执行，且把 `auth.json` 路径注入子进程 |

**补充（P1，设计层面）**：`website/api/controllers/ClipboardController.php:6-14` 的 TODO 自述——**剪贴板正文（可能含密码、token、私密消息）以明文写入 MySQL 与 OSS**，服务端掌握全部明文。这是当前架构最大的单点风险，建议排期端到端加密（客户端派生 KEK，服务端不持密钥）。

---

## 四、P2 —— 可维护性与体验（15 条，摘要）

**性能**
- `core/db/clipboard_query.py:136-140`：每次搜索执行两遍完整查询（`search` + `_count_spec`），成本翻倍。
- `core/file_sync_service.py:364-379`：下载后重读整个文件再算 SHA-256，1 GB 文件多一次全盘读；建议在流式写盘时增量 `h.update(chunk)`。
- `core/tag_service.py:204-222`：`apply_tag_names` 每个标签三轮事务（查 + 建 + 写），建议批量 `executemany`。
- `core/clipboard_monitor.py:93-103`：清理在主线程触发，`SELECT COUNT(*) WHERE is_starred=0` 无索引全表扫。
- `ui/share_dialog.py:192-197`：创建分享链接的 HTTP 请求在模态对话框里**同步执行**，弱网时整个 UI 冻结。

**一致性 / 正确性**
- `core/db/clipboard_query.py:85`：排序无 tiebreaker（`ORDER BY created_at DESC`），`touch_item` 会造成同毫秒并列 → 分页重复/漏行。建议 `ORDER BY created_at DESC, id DESC` + 复合索引。
- `core/db/clipboard_query.py:89`：`get_items` 不回填 `tag_ids`，与 `search` 行为不一致。
- `core/db/clipboard_query.py:444-453`：MySQL `FROM_UNIXTIME` 与 SQLite `strftime` 时区口径不一致。
- `core/cloud/sync_client.py:62-66`：`has_more` 未处理，长离线恢复时每轮只推进 100 条。
- `core/file_sync_service.py:570`：`if self._uploading and self._downloading and self._deleting: return` 写成 `and`，守卫实际无效。
- `core/plugin_manager.py:339-342`：热重载不清 `_active_worker` 与失败插件的注册项。
- `plugins/ai_image_gen/plugin.py:35` vs `core/plugin_manager.py:640`：配置路径不一致，UI 保存的配置插件永远读不到。

**UI / 代码风格**
- `ui/clipboard_item.py:98`：`QTimer.singleShot(0, _decode_and_set)` 未绑 context 对象，行提前销毁会抛 `RuntimeError`。
- `ui/controllers/clipboard_list_controller.py:147/175/295`：行高魔法数字 `76/92/8` 三处硬编码，改样式易不同步（历史上造成过"删除按钮被截一半"）。
- `ui/controllers/item_action_controller.py:114/235`：图片加载与图片保存共用 `max_workers=1` 的执行器，保存大图期间点击复制全部排队。
- `ui/cloud_login_widget.py:115-121`：用户输入的服务器地址拼进 QLabel 富文本；`:177-186` 以 `logger.warning` 打印用户邮箱。
- `ui/edge_window.py:446`：热键唤出后 1.5 秒保护期一到就自动滑出，与"唤出即固定"的直觉不符。
- `main.py:675-702 / 918-944`：macOS 版本分支 URL 构造逐字重复 20 行；`main.py:7/18/32/33` 存在未使用导入。
- `ui/controllers/plugin_action_controller.py:263-274`：猴子补丁改写 `mousePressEvent`，每次调用挂新闭包形成引用环。

**测试 / 构建**
- 根 `conftest.py:32` 无条件 `os._exit()` → coverage/junit-xml 结果文件丢失，CI 上静默产出空报告。
- `tests/test_smoke.py:52-70`：插件核心路径几乎零覆盖（唯一用例把目录打成空，只断言 `_plugins == {}`），本次 P0-5/6/7 全部无测试阻挡。
- `build_mac.sh:25`：`curl ... | bash` 直装 Homebrew，无校验且缺 `set -u`/`pipefail`。
- `SharedClipboard.spec:8`：`datas` 未包含 `plugins` 目录，用该 spec 构建会丢失全部内置插件。
- `main.py:994`：`os._exit(0)` 兜底定时器与 `app.quit()` 竞态，可能截断落盘与 DB 关闭，且进程一律以 0 退出掩盖失败。

---

## 五、做得好的地方（值得保持）

审查不应只挑毛病，以下几处是**明显高于同类项目平均水平**的，修改时请别误伤：

1. **SQL 注入面干净**：除 `core/database.py:262` 的 `PRAGMA busy_timeout`（整数格式化）外，core 层全部走 `?` 参数化，`MySQLDatabaseManager._to_mysql` 只处理 SQL 文本、不碰参数。
2. **线程模型健康**：`DatabaseManager` / `MySQLDatabaseManager` 均已改为 `threading.local()` 每线程一连接 + `weakref.finalize` 回收，未发现跨线程共享连接。
3. **敏感信息不进日志**：`clipboard_monitor.py:221` 刻意只记文本长度而非正文，全 core 未发现剪贴板内容落日志。
4. **密钥存储规范**：`settings.json` 原子写 + 非 Windows `chmod 0600`，`auth.json` 0600 且排除备份（`http.py:219-266`）；未发现 0777 类宽权限。
5. **构建脚本未泄露密钥**：App 专用密码走 `APPLE_APP_PASSWORD` 环境变量，上传用 `--password "@env:APPLE_APP_PASSWORD"`，无明文口令。
6. **图标缓存受控**：`SourceAppIconCache` 有 LRU `_MAX_ENTRIES=128`，且先缩到 32px 再编码（这项优化把 134ms/App 降到 0.4ms）。
7. **i18n 数据完整**：8 种语言 × 154 个 key，零缺漏、零跨域键名冲突。

---

## 六、建议的修复顺序

| 批次 | 内容 | 理由 |
|---|---|---|
| **第一批（立即）** | P0-4 迁移、P0-7 配置容错、P0-8 线程 abort | 三个都是"用户可自主触发、后果不可逆"的崩溃/数据丢失，改动量小（都在 20 行内） |
| **第二批** | P0-1、P0-2 云同步（**需前后端联调**） | 需要同时改 `FileController.php` 回包字段与 `ClipboardController.php` 的 `INSERT IGNORE` 回填，是全项目风险最高的改动，建议加契约测试 |
| **第三批** | P0-3 跨空间去重、P0-5 / P0-6 插件安全 | 涉及 schema 与权限模型，需要设计评审 |
| **第四批** | P1 全量（尤其 #6 FTS 兜底、#5 LIKE 转义、#12 takeItem 泄漏） | 影响日常体验与长期稳定性 |
| **第五批** | P2 与端到端加密排期 | 技术债清理 |

**横向建议**：
- 为「客户端 ↔ 后端字段契约」补一组**契约测试**（直接解析 `website/api/controllers/*.php` 的 `Response::success` 键名，与客户端 `srv.get(...)` 比对），P0-1 这类问题本可以零成本拦住。
- 把「静默失败」列为代码评审红线：本项目 P0-4、P0-2、P1-2 的根因都是 `except: logger.warning` / 忽略返回值后**继续上报成功**。建议约定——失败必须上抛或显式通知用户，禁止降级为日志后继续走成功路径。

---

*本报告基于 2026-09-16 的代码状态（`git HEAD = d0b918d`，工作区另有未提交的 5 个文件修改）。所有 P0 结论均已回到源码或后端实现逐条复核取证。*

---

## 附：修复完成记录（2026-09-16）

**验证**：全量 pytest 通过（402 用例，0 失败，含新增回归测试 18 条）；所有改动文件 `py_compile` 通过；`build_mac.sh` 过 `bash -n`。

### P0（8/8 全部修复）

| # | 修复内容 | 文件 |
|---|---|---|
| 1 | 迁移 SQL 按目标库真实 schema 动态生成 13 列、方言冲突策略（SQLite `INSERT OR IGNORE` / MySQL `INSERT IGNORE`）、批量失败改为上抛 `RuntimeError`（经 `finished_err` 弹窗告知用户） | `core/migration.py` |
| 2 | `_snapshot_from_dict` 逐字段容错（`_as_int/_as_str/_as_str_tuple/_as_str_map`）；`_load_locked` 兜底扩到 `OSError/ValueError/TypeError/AttributeError` 并拒绝非 dict 顶层 | `config.py` |
| 3 | 迁移 QThread 改用共享 `track_thread()`（强引用至 finished + deleteLater），启动前拦截重入并提示"迁移正在进行中"（新增 8 语言文案 `migration_in_progress`） | `ui/thread_utils.py`（新）、`ui/main_window_helpers.py`、`ui/settings/plugins_tab.py`、`i18n_strings/misc.py` |
| 4 | 文件同步兼容 `sha256`/`content_sha256` 双字段名；游标只在处理成功或放弃重试后推进（连续 5 次失败才放弃）；处理 `has_more` 翻页（单轮上限 20 页，无进展即停） | `core/file_sync_service.py` |
| 5 | `uploaded_count` 改为真实确认数 `len(cloud_id_pairs)`；新增 `push_unconfirmed` 信号，服务端去重不回 id 的条目累计 3 次后放弃重传（`_push_gave_up`），打破无限循环 | `core/cloud_sync_service.py` |
| 6 | 去重判据带 space 维度：`get_existing_hashes(hashes, space_id, space_scoped=True)`，SQL 用 `COALESCE(space_id,'')` 归一化个人空间 | `core/db/clipboard_dao.py`、`core/repository.py`、`core/cloud_sync_service.py` |
| 7 | 插件权限代理重写为**默认拒绝**：real client 与白名单捕获在闭包里、实例 `__slots__=()`，`_real`/`get_tokens`/任何未登记方法一律 `PermissionError`；白名单从 4 个 domain client 上标注了 `@requires_plugin_permission` 的方法动态收集 | `core/plugin_manager.py` |
| 8 | 禁用插件不再执行任何代码（状态标 `disabled`）；用户插件目录 group/other 可写时整体拒绝加载 | `core/plugin_manager.py` |

### P1（13/13 全部修复）

1. 401 重试只对 GET/HEAD 放行（`_401_RETRY_METHODS`），扣费类 POST 不再被重放 — `core/cloud/http.py`
2. 云端删除检查 `delete_item` 返回值，失败不再误清本地 `cloud_id` — `ui/controllers/item_action_controller.py`
3. presigned URL 错误信息只报 host，签名/AccessKeyId 不再落入 DB/日志/异常文本 — `core/cloud/files_client.py`
4. 存储 URL 只放行 https（本地自测可用 `SC_ALLOW_INSECURE_STORAGE=1` 显式打开） — `core/cloud/http.py`
5. LIKE 通配符转义（`!` 作 ESCAPE 字符，双方言安全） — `core/db/clipboard_query.py`
6. FTS5 MATCH 语法错误自动降级 LIKE，搜 `AND`/`*` 不再整列表报错 — `core/db/clipboard_query.py`
7. `sandbox_path_for` 强制 64 位 hex 校验（`validate_sha256`）；`materialize_for_open` 文件名白名单化 — `core/file_storage.py`
8. SQLite 备份前先 `PRAGMA wal_checkpoint(TRUNCATE)`；备份文件带时间戳、保留最近 5 份 — `core/db_migrations.py`
9. keyring 写入成功后清掉配置文件里的旧 base64 凭据副本；b64 回落读取时打 warning；新增能力探测 `can_use_keyring()` — `utils/secure_store.py`
10. 切语言后重建托盘菜单（`_build_tray_menu` + `tray_rebuild_callback`）；`set_language` 归一化旧别名（`zh-CN`→`zh_CN`）并不再静默吞非法值 — `main.py`、`i18n.py`、`ui/main_window_helpers.py`
11. `_check_hotkey_listener_alive` 接上调用（启动 3s 后探测） — `main.py`
12. `prepend_item` 的 `takeItem` 行显式回收（`_remove_row`：`removeItemWidget` + 清引用） — `ui/controllers/clipboard_list_controller.py`
13. 移除仓库相邻目录自动探测，只信任 `CHAT_IMAGE_GEN_DIR` 环境变量/插件配置文件；同时兼容标准 config.json 位置 — `plugins/ai_image_gen/plugin.py`

### P2（修复 10 条，搁置 5 条）

**已修复**：
1. `conftest.py` 失败时不再 `os._exit`（保留失败详情输出），全部通过时才接管退出
2. `QTimer.singleShot(0, image_label, cb)` 绑定 context + `shiboken6.isValid` 校验 — `ui/clipboard_item.py`
3. 新增独立 `_io_executor(max_workers=2)` 承接图片保存，不再阻塞复制路径 — `ui/main_window.py`、`item_action_controller.py`
4. 托盘菜单可重建（同 P1-10）
5. edge_window 显式唤出不再 1.5s 必然滑出（`_summoned` 标记；用户点别处失焦即收回，enterEvent 恢复常规逻辑） — `ui/edge_window.py`
6. 行高魔法数字收敛为 `ClipboardItemWidget.MIN_H_TEXT/MIN_H_IMAGE/ROW_EXTRA`，三处统一引用
7. `get_items` 回填 `tag_ids`；排序统一 `ORDER BY created_at DESC, id DESC`（tiebreaker 防翻页重复/漏行） — `core/db/clipboard_query.py`
8. `_drive_queues` 删除无效的 `and` 守卫 — `core/file_sync_service.py`
9. `SharedClipboard.spec` 补 `plugins` 目录 datas — `SharedClipboard.spec`
10. `build_mac.sh` 补 `set -euo pipefail`；移除 `curl | bash` 直装 Homebrew（改为提示手动审阅安装）；`main.py` 退出兜底改可取消定时器 + 强杀留痕；合并重复的 macOS 隐私面板打开逻辑（`_open_privacy_pane`）；清理未使用导入 — `main.py`

**搁置（需设计决策或涉及后端部署，不在本轮擅自改动）**：
- 端到端加密（后端 `ClipboardController.php` 明文存储 TODO）——需密钥派生方案设计与 schema 迁移，建议单独立项
- 后端 `INSERT IGNORE` 回填 id（`ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)`）——需后端发布；客户端已用"放弃重传"兜底打破循环
- 登出后 UI 组件残留旧服务引用、分享链接模态框同步 HTTP、云剪贴板 `has_more` 追赶循环、下载流式增量算 SHA——涉及交互/架构取舍，建议下轮专项处理

### 新增回归测试（`tests/test_review_fixes_20260916.py`，21 条）

- 迁移真实写入 5 条 + 失败上抛（P0-1）
- 配置 `null`/字符串/非 dict 顶层三种脏数据均回退默认值（P0-2）
- 合法/穿越/短 sha 三种路径输入（P0-7）
- 插件代理：`_real` 拒绝、`get_tokens/set_tokens` 拒绝、未声明权限 `get_balance` 拒绝、声明后放行、写入拒绝（P0-5）
- 文件同步：坏 sha 不推游标、`sha256` 字段兼容、5 次失败后放弃推进（P0-4）
- LIKE 转义、i18n 别名归一化
- 拉取落库 space_id 三态（服务端值 / space_key 兜底 / 个人为 None）

---

## 附二：二次复审记录（2026-09-16 下午）

两路独立复审（core 层 / UI 层）对全部修复 diff 找茬，共确认 **4 个 P1 + 8 个 P2**，已全部修复；另有 2 条指控经取证为误报。

### 已修复（复审新发现）

**P1：**
1. `_server_item_to_local` 不写 space_id —— 团队条目以 NULL 落库，与 (space_id, content_hash) 去重不配套，重拉整批重复插入、push 时被当个人空间推回。修复：读取 `data.get("space_id")`，缺失时 fallback `space_key`（`core/cloud_sync_service.py`）
2. `build_mac.sh` 加 `set -u` 后 `$DEVID_SIGN_CERT` 未设置直接退出，ad-hoc 签名分支永不可达。修复：`${DEVID_SIGN_CERT:-}`（本次 `set -u` 引入的回归，正是复审的价值）
3. 迁移 worker 二次触发时 `isRunning()` 对已 deleteLater 的包装抛 RuntimeError，重入保护自毁。修复：守卫加 try/except + finished 时清空 `window._migration_worker`
4. edge_window `_summoned` 是死代码（清标后无条件滑出），activateWindow 失败路径上"唤出即消失"依旧。修复：`_check_mouse_position` 中 `_summoned` 直接 return；新增 `changeEvent` 在失焦时清标恢复常规隐藏

**P2：**
5. `_push_gave_up` 只按 content_hash 全局放弃，会误伤其他空间的同内容条目 → 键改为 `(space, hash)`
6. `get_items_by_tag` 漏加 `id DESC` tiebreaker → 补齐
7. db_migrations 备份清理 glob 匹配不到 `.bak-wal`，永不清理 → glob 改 `.*.bak*` 并成对保留
8. main.py 权限引导框单槽位引用，两个引导同时挂起时先弹的被 GC → 改列表 `_permission_dialogs`
9. secure_store 清回落副本时漏掉旧明文键（`_read_from_config` 的兼容回退仍会命中）→ 新增 `_clear_legacy_key`
10. 云端删除失败只落日志，用户误以为已删 → 弹窗提示
11. thread_utils 对从未 start 的线程无释放路径 → 加 `destroyed.connect` 兜底
12. conftest 文档串未同步新的双路退出行为 → 更新

### 误报澄清

- "tray_rebuild_callback 从未注册" —— 不实，`main.py:345` 已挂 `self.main_window.tray_rebuild_callback = self._retranslate_tray`
- "SharedClipboard.spec 无改动" —— 该文件未被 git 跟踪（.gitignore），文件内容已正确包含 plugins datas

### 已知取舍（复审确认可接受，未改）

- 文件同步翻页中途失败：前 N-1 页已落库但 cursor 不动，下轮靠 `get_by_cloud_id` 幂等自愈（已加注释说明）
- `_MAX_PULL_SKIP` 放弃推进游标：瞬时错误（如 DB 锁）重试 5 轮后数据跳过 —— 相比旧实现"立即跳过"已是改善，按错误类型分级属后续优化
- conftest 失败路径可能以 SIGABRT(134) 结束 —— 仍是失败信号，CI 可区分

---

## 附三：线上兼容缺口修复（2026-09-16 傍晚，提交前专项核查）

提交前按"线上有真实运营用户"这一前提，对全部行为变更做了一次发版前核查。**结论：除下面这一条外，其余变更对线上安全**（https 强校验已核对后端 `OSS.php` 四处签 URL 全为 `https://`；内置插件只用 `base_url`；迁移 SQL 改为探测目标库真实列后裁剪，缺列不会硬报错）。

### 新发现并已修复：插件 domain 层调用写法被默认拒绝打挂

**位置**：`core/plugin_manager.py`（P0-5 修复的自身副作用）

P0-5 把权限代理从"默认允许"改成"默认拒绝"时，白名单只从 domain client 收集**方法名**并挂在 facade 上，于是 `client.auth` 这个属性本身落进了"未登记 → 拒绝"分支。

但旧实现是 `attr = getattr(self._real, name)` **直通** —— `client.auth` 返回的是**未代理的真实 `AuthClient`**。也就是说：

- `client.auth.ai_generate(...)` 是插件作者实际在用的写法（`core/plugin_api.py:147` 的文档只写"返回 CloudAPIClient 实例"，并没有约定只能走扁平方法名）；
- 更糟的是旧写法下 `client.auth._http.get_tokens()` 可直达 `HttpClient` 上的凭据入口 —— 这条旁路在旧实现里**连权限检查都没有**。

若只放行 facade 上的扁平方法名，按文档写的老插件升级后会立刻 `PermissionError`：

```python
proxy.auth          # 旧: 真实 AuthClient（直通、零检查）→ 新: PermissionError
```

**修复**：domain 名改为返回一个**同样默认拒绝的子代理**（而不是直通、也不是一律拒绝）。`_collect_plugin_allowed_methods` 返回值改为按 domain 分组的 `{domain: {方法: (bound, 权限)}}`，由 `_make_default_deny_proxy(label, methods, permissions)` 统一构造；facade 同时保留扁平方法名（`client.ai_generate()`）与 domain 子代理（`client.auth.ai_generate()`）两种写法。

修复后的行为对照：

| 调用 | 旧实现 | P0-5 初版（默认拒绝） | 现在 |
|---|---|---|---|
| `client.auth.ai_generate()` | ✅ 可用（零检查） | ❌ PermissionError | ✅ 可用（校验 network） |
| `client.auth._http.get_tokens()` | ✅ **可直达凭据** | ❌ | ❌ 拒绝 |
| `client.auth` | 真实对象 | ❌ | 子代理（不可绕过） |
| `client.get_balance()` | ✅（无权限校验） | 按 credits 校验 | 按 credits 校验 |
| `client._real` | ✅ 绕过全部 | ❌ | ❌ |

**教训**：给"默认允许"改"默认拒绝"时，**属性名本身也是 API 面**。旧实现里凡是能被 `getattr` 直通拿到的东西，插件都可能在用 —— 收敛权限面必须逐个列举并显式决定"放行 / 换成受控代理 / 拒绝"，不能只盯着方法名。

### 新增回归测试（`tests/test_review_fixes_20260916.py`，+7 条）

`TestPluginDomainProxyCompat`：domain 访问返回代理而非真实客户端、`_http`/`_facade` 被拒、声明 network 后 `auth.ai_generate` 可用、credits 权限门控、未登记方法与 `sync_client.get_tokens` 被拒、domain 写入被拒、`base_url` 仍可读。全量 412 用例通过。
