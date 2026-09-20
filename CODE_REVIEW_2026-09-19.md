# SharedClipboard 当前代码与 macOS 更新发布审查

- 审查日期：2026-09-19
- 基线：`main` / `4a462b8`，开始审查时工作区干净
- 范围：客户端 `config.py`、`main.py`、`core/`、`ui/`、`plugins/`、`tests/`，后端 `website/api/`，macOS 构建与发布脚本及现有产物
- 方法：三名 agent 分别审查核心数据、界面与平台、后端与发布；主审查 agent 核对配置并发、完整测试和发布版本。以下只列有源码证据或最小复现的发现。
- 本文前半部分保留首次审查时的证据和结论；文末记录随后执行的修复与验收。

## 结论

首次审查时的 3.3.6 旧包 **不宜作为 macOS 更新提交**。两项 P0 会造成跨空间云 ID 错绑或文件同步永久漏项；另外存在插件安装误删、设备撤销失效等 P1。修复和 3.3.7 候选包的状态见文末。

## P0：发布前必须修复

### 1. 相同内容跨空间仍会错绑云 ID

`core/database.py:26` 与 `core/mysql_database.py:37` 对 `content_hash` 设置全局唯一约束。虽然 `core/cloud_sync_service.py:95-101` 已按空间查询已有 hash，团队空间的新条目插入时仍与个人空间同 hash 条目冲突。`core/db/clipboard_dao.py:108-119` 在冲突后返回任意空间的旧条目 ID，`core/cloud_sync_service.py:108-117,158` 随即把团队的 `cloud_id` 写给这个个人条目。

最小复现：先存个人空间 `hash-same`，再拉取团队空间中同 hash、服务端 ID 为 77 的条目；结果个人条目成为 `space_id=None, cloud_id=77`，团队空间没有该条目。后续按该云 ID 删除可能误删团队记录。需要将唯一性和冲突回查都改为 `(space_id, content_hash)` 口径，并迁移 SQLite/MySQL 旧约束及补回归测试。

### 2. 文件同步游标越过尚待重试的条目

`core/file_sync_service.py:127-159` 处理一页时，即使较小 ID 失败并加入 `_pull_skip`，较大 ID 成功仍会把 `max_id` 推到较大值；下一轮 `do_pull` 在 `:85-99` 使用这个值作为 `since_id`。服务端 `website/api/controllers/FileController.php:577` 只返回更大的 ID。

最小复现：同页 ID 1 暂时失败、ID 2 成功，`_process_page` 返回游标 2 且 `_pull_skip[1]=1`；下一轮从 2 开始，ID 1 永不重试。应把游标封顶于最小待重试 ID 之前，并停止本轮后续翻页，直到该条成功或明确达到放弃阈值。

## P1：高优先级缺陷

| 问题 | 证据与触发条件 | 影响 / 修复方向 |
| --- | --- | --- |
| 文件改名、软删除无法传到其他设备 | `website/api/controllers/FileController.php:571-578` 仅以 `id > since_id` 拉取；`:745-750,802-805` 改名和删除只更新旧行；`core/file_sync_service.py:78-100` 持久推进游标。两设备已拉过文件后，在 A 改名或删除。 | B 永远收不到更新或删除标记。需用变更序号/事件流，或按 `updated_at` 加稳定游标同步。 |
| 团队成员无法下载他人剪贴板图片 | `website/api/controllers/ClipboardController.php:327-333` 允许拉取团队条目，但 `:606-613` 图片 URL 只允许作者 `user_id`；`core/cloud_sync_service.py:357-398` 需要再次取 URL。 | 成员 B 对 A 的图片重试后保存空图片占位。图片 URL 权限应按空间成员资格判断。 |
| 移除设备不能撤销桌面会话 | `core/cloud/auth_client.py:51-55` 登录不传 `device_id`；`website/api/controllers/AuthController.php:115,159,182,212` 将刷新令牌绑定空 ID 并沿用；`DeviceController.php:139-145` 只删目标设备 ID 的令牌。 | 删除设备后，现有桌面会话仍能刷新。登录和刷新均应传/绑定真实设备 ID，并覆盖注册与删除回归测试。 |
| 插件安装失败会删除所有用户插件 | `ui/settings/plugins_tab.py:87-99` 对恶意路径或损坏 ZIP 走 `rmtree(self._target_dir)`，而 `:447-449` 的 `_target_dir` 是整个用户插件根目录。临时目录实测旧插件随失败安装一起消失。 | 非 App Store 版本的已有插件被删除。只在独立临时目录解压，成功校验后移动目标插件，失败只清临时目录。 |
| 并发配置落盘可被旧快照覆盖 | `config.py:524-530,580-587` 在锁内抓快照、锁外写同一路径；`config.py:545-554` 使用同一 `.tmp`。让较早写入暂停，较晚写入先完成后再放行前者，实测内存 `fr_FR`、磁盘 `en_US`、`dirty=False`。 | UI 与后台 token/同步更新并发时可丢失最新设置。应串行化写入或给快照版本号，拒绝旧版本覆盖。 |
| 不同图片可能被当成同一张 | `core/clipboard_monitor.py:283-305` 仅用 64×64 缩图的 hash 判断重复并直接返回。两张 128×128 黑图仅一个像素不同，Qt offscreen 实测 hash 相同、第二张未入历史。 | 丢失图片历史。快速 hash 命中后需再比较完整图像内容。 |
| 云同步解析失败泄露剪贴板正文到日志 | `core/cloud_sync_service.py:378-380` 在异常日志中插入完整 `data`。传未知 `content_type` 和 `text_content='SECRET_TOKEN_123'`，实测日志包含该正文。 | 日志可能保存密码或令牌。仅记录服务端 ID、类型和异常摘要。 |

## P2：后续修复

- `website/api/controllers/AuthController.php:191-213` 的刷新令牌先查再删，既无事务也不检查删除行数。跨进程并发请求可重复消费同一令牌并各自签发新令牌；桌面端自身的进程内锁无法阻止这种情况。
- `core/macos_hotkey.py:146-155` 在全局监听器注册返回 `None` 时，已建立的本地监听器未清理；`main.py:707` 丢弃失败实例后也无法调用 `stop()`。模拟 AppKit 可复现一个遗留监听器；实际权限拒绝场景仍需真机确认。

## macOS 更新发布预检

| 检查项 | 结果 |
| --- | --- |
| 版本与产物 | `config.py:42` 仍为 `3.3.6`。现有 `dist/共享剪贴板.app` 是 `3.3.6 / 202607061231`，`.pkg` 同为 2026-07-06 产物；均早于当前 HEAD，不能代表本次代码。[Apple 公开商店页面](https://apps.apple.com/gy/app/sharedclipboard-sync/id6756561246?mt=12)的检索结果也显示 3.3.6；更新前需在 App Store Connect 核对当前状态，并建立递增版本与新构建号。 |
| Provisioning Profile | 仓库 profile 和旧包内嵌 profile 匹配 Bundle ID、Team ID、macOS 平台，有效期至 2027-05-16。 |
| 旧包结构 | universal2；App Store 插件边界为仅打包 `smart_text`，未见 `ai_image_gen`。 |
| 本机签名 | 受限执行环境查询曾显示 0 个有效身份、旧包不受信任；在可访问系统钥匙串的环境复核后，实际有 3 个有效代码签名身份，旧 `.app` 的 `codesign --verify --deep --strict` 及 `.pkg` 的证书链均通过。先前签名失败是执行环境误报。 |
| 旧包冒烟脚本 | 受限环境首次运行 `release_smoke_macos.sh` 为 10 pass、2 warn、5 fail。其中 `codesign`、`spctl` 两项需在可访问钥匙串的环境复核；另外三项是脚本误报。`release_smoke_macos.sh:109` 的 `--entitlements :-` 读不到权限，`--entitlements -` 可读；`:169-175` 只用 `find` 搜 `httpx`/`keyring` 文件，未查看 PyInstaller `PYZ.pyz`，两者实际分别包含 23/20 个模块。 |
| 尚未执行 | 未重建或上传；未进入 App Store Connect 核查后台构建状态、元数据或提交审核；未启动候选包做菜单栏、剪贴板、热键、搜索、退出等手工 UI 测试。 |

Apple 的[更新版本流程](https://developer.apple.com/help/app-store-connect/update-your-app/create-a-new-version)要求建立递增的 App Store 版本并上传对应的新构建；[macOS 构建号说明](https://developer.apple.com/documentation/xcode/preparing-your-app-for-distribution)要求新构建号递增。

## 验证记录

- `pytest -q`：退出码 0；收集 412 个用例，输出显示 1 个跳过，其余通过。`conftest.py` 在测试成功后用 `os._exit(0)` 绕过 Qt 线程析构，因此没有常规汇总行。
- `python3 -m compileall -q config.py utils core ui main.py`：通过；`core/` AST 语法扫描、后端 PHP 语法扫描和构建脚本 `bash -n` 均通过。
- P0 两项、P1 的插件清理、配置覆盖、图片 hash、正文日志均做了最小复现。后端跨设备问题根据客户端/服务端契约和 SQL 条件确认；尚未用真实双设备环境执行端到端验证。
- 首次审查前的工作区干净；该阶段仅新增本报告。

## 建议处理顺序

1. 修复两项 P0 和跨设备文件改名/删除、团队图片权限、设备撤销，补齐跨空间和跨设备回归测试。
2. 修复插件误删、配置落盘竞争、图片去重和敏感日志。
3. 修正发布冒烟脚本的三项误报，提高版本号并在可访问钥匙串的环境构建新候选包。
4. 对新包重新跑自动检查和 macOS 真机主路径/权限冒烟，然后核对 App Store Connect 状态与提交材料。

## 修复与验收（2026-09-19）

原审查列出的 P0、P1、P2 已在客户端和 `website/api` 两个仓库中修复：

| 范围 | 修复结果 |
| --- | --- |
| 剪贴板空间隔离 | SQLite v5、客户端 MySQL v7、服务端迁移均将 hash 唯一性限制在空间内；冲突回查及收藏批量回填也按空间处理。服务端继续按作者区分同空间记录，避免改变现有删除和配额权限。 |
| 云文件同步 | 新增 `cloud_file_events` 事件序号，初始迁移快照仅包含已完成文件和删除标记；完成上传、重命名、删除、AI/FlatLay 文件写入均记录事件。客户端改用独立事件游标，失败事件未解决前不越过它；旧 `since_id` 接口仍可用。 |
| 权限与认证 | 团队图片 URL 按现有成员资格授权；桌面注册、登录、刷新均传设备 ID；移除设备会撤销对应及历史空绑定令牌；刷新令牌使用事务和行锁保证一次性消费。 |
| 客户端稳定性 | 插件 ZIP 在独立目录校验安装，失败不删除现有插件；配置落盘串行化；图片快速 hash 命中后比较原图；云解析异常日志不再记录剪贴板正文；热键注册失败清理监听器。 |
| 发布检查 | 修正 entitlements 导出和 PyInstaller PYZ 依赖检查，版本提高至 3.3.7。 |

验证结果：客户端完整 `pytest -q` 退出码 0，1 项按环境跳过；`compileall`、两个仓库的 `git diff --check` 和构建脚本 `bash -n` 通过。后端 PHP 在本机 PHP 8.5 下关闭弃用告警后通过 **244 tests / 800 assertions**；未关闭告警时，旧测试产生 12 个 risky 标记，但没有断言失败。新增的文件事件、空间权限和客户端回归用例均通过。服务端剪贴板唯一索引迁移还在隔离的临时 MySQL 9.7 实例中实测：个人与两个团队同 hash 可共存，同作者同团队重复项被拒绝。

服务端文件事件迁移也在隔离的 MySQL 9.7 实例中实测：初次快照包含已完成文件与删除标记，排除 pending 存活行；重复运行不重复快照，新增完成文件仍可回填。重复 `INSERT IGNORE` 可能消耗自增 ID，产生空隙，但事件 ID 保持单调，游标不要求连续。

客户端 MySQL v6→v7 自动升级同样在隔离的 MySQL 9.7 实例中实测：旧全局唯一索引被替换后，个人及两个团队的同 hash 三条记录可共存；每个空间内重复写入仍被拒绝，重开数据库后三条记录保持完整。

已用 `APPSTORE_PROFILE_DIR=profiles ./build_appstore.sh` 构建本地 Mac App Store 候选包：**3.3.7 / build 202609191702**。`.app` 深度签名校验和 `.pkg` 证书链通过；`release_smoke_macos.sh` 为 **16 pass、3 warn、0 fail**。三个提醒分别是 MAS 包被本机 `spctl` 拒绝（Apple Distribution 签名的预期结果）、保留现有 sandbox container、检测到旧版非沙盒 Application Support。当前 `/Applications/共享剪贴板.app` 仍在运行，未另启候选包与其争用同一容器，手工 UI、双设备端到端和新装机验证尚待执行。

候选 `.pkg` 的 SHA-256：`a6f30d6e866d7f6db5a57db0b50a442e79e05591a8551f4e978ae51df36203a6`；主程序为 `x86_64` + `arm64` 双架构。

使用现有 App Store Connect API Key 做只读核查：Mac App Store 最新版本为 **3.3.6 / READY_FOR_SALE**，版本列表中尚无 3.3.7。候选包的营销版本号高于当前在售版本；上传前仍需按 App Store Connect 流程建立 3.3.7 版本并选择构建。

上线顺序：先执行 `website/api/migrations/` 的数据库迁移，再部署依赖事件表的 PHP 代码，最后上传和审核 3.3.7 包。当前仅完成本地候选包，**尚未部署后端或上传 App Store**。

已知数据模型限制：同一团队空间里，不同作者的相同 hash 可以在服务端分别存在；桌面端仍按 `(space_id, content_hash)` 合并为一条展示。修复保证后续记录不会覆盖这条本地记录的 `cloud_id`，避免跨作者错删。若产品要求同时展示这些相同内容，需另行引入作者维度并制定删除/配额规则。

## 二次审查修复

- 文件事件重拉时，删除事件只用 `cloud_id` 定位；历史 tombstone 不再凭相同 SHA 误删另一条活跃文件。新增真实 SQLite 回归用例覆盖旧删除事件与新活跃文件同 SHA 的顺序。
- 插件商店安装前校验 manifest ID；目标插件目录损坏或已存在时，先将该目录移至独立备份，再替换并清理备份。替换失败恢复原目录，其他插件不受影响；新增修复与失败回滚测试。
- 文件清理事务统一先锁用户 `usage_stats`、再更新 `cloud_files`，与删除、完成上传路径保持一致；回滚与定时清理加 `is_deleted = 0` 守门，防止已删除的待上传文件重复扣减 pending 配额。

二次修复后客户端完整测试退出码 0（1 项环境跳过），PHP 为 **244 tests / 800 assertions**；Python 编译、PHP 语法和两个仓库的 diff 空白检查通过。当前候选包已包含客户端二次修复，尚未部署或上传；后端并发锁顺序未用真实并发 MySQL 负载测试，仍需上线前的集成验证。
