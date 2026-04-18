# SharedClipboard 插件系统设计

本文档以当前代码为准，描述 `core/plugin_api.py`、`core/plugin_manager.py`、`ui/plugin_config_dialog.py` 和设置页插件管理功能的真实行为。

## 1. 当前能力

插件系统已经具备以下能力：
- 扫描并加载内置插件和用户插件。
- 按 `min_app_version` 和 `dependencies.pip` 做基本兼容性检查。
- 支持异步执行、取消、超时和进度回调。
- 支持 `COPY`、`SAVE`、`REPLACE` 和 `NONE` 四种结果处理方式。
- 支持插件配置持久化和配置 UI 自动生成。
- 支持云端 API 客户端注入，并按 `permissions` 做方法级权限拦截。

当前仓库内置插件：
- `smart_text`：文本清理、大小写转换、编码解码、JSON 处理、行处理和统计。
- `ai_image_gen`：启动外部 `chat_image_gen` 工具。

## 2. 插件发现与加载

### 搜索目录

`PluginManager._get_plugin_dirs()` 会按下面顺序搜索：
1. 内置插件目录：仓库根目录的 `plugins/`
2. 用户插件目录：`<config_dir>/plugins/`
3. 冻结包模式下，可执行文件同级的 `plugins/`

`config_dir` 由 `config.get_config_dir()` 提供，通常位于系统配置目录下的 `SharedClipboard/`。

### 插件目录结构

```text
plugins/
  smart_text/
    manifest.json
    plugin.py
  ai_image_gen/
    manifest.json
    plugin.py
```

### 加载流程

`PluginManager.load_plugins()` 会：
1. 扫描目录下的 `manifest.json`。
2. 校验 `id`、`entry_point` 和相对路径安全性。
3. 检查 `min_app_version`。
4. 检查 `dependencies.pip` 是否可导入。
5. 动态导入插件模块并查找 `PluginBase` 子类。
6. 注入 `logger`、`config` 和 `cloud_client`。
7. 调用 `on_load()`。

插件路径会被限制在插件目录内部，避免通过 `entry_point` 逃逸到目录外。

## 3. manifest 规范

当前加载器实际使用的字段如下：

```json
{
  "id": "smart_text",
  "name": "智能文本",
  "version": "1.0.0",
  "description": "文本格式转换、编码解码、JSON处理等实用工具集",
  "author": "SharedClipboard",
  "entry_point": "plugin.py",
  "min_app_version": "1.1.0",
  "permissions": ["network", "clipboard_write"],
  "timeout": 10,
  "config_schema": {},
  "dependencies": {
    "pip": ["openai>=1.0.0"]
  }
}
```

### 字段说明

- `id`：插件唯一标识，`snake_case`。
- `name`：显示名称。
- `version`：版本号。
- `description`：插件描述。
- `author`：作者。
- `entry_point`：入口 Python 文件，相对插件目录。
- `min_app_version`：最低兼容应用版本。
- `permissions`：插件请求的权限列表。
- `timeout`：单次执行超时时间，单位秒，默认 `30`。
- `config_schema`：配置 UI 定义。
- `dependencies.pip`：需要额外安装的依赖。

`api_version` 不是当前加载器的必用字段，文档和代码都不依赖它。

## 4. 插件 API

### 4.1 `PluginResultAction`

`core/plugin_api.py` 中定义了四种结果动作：
- `NONE`：不对剪贴板或列表做额外处理。
- `COPY`：把结果复制回系统剪贴板。
- `SAVE`：把结果保存为新的历史条目。
- `REPLACE`：替换原条目内容。

### 4.2 `PluginAction`

```python
@dataclass
class PluginAction:
    action_id: str
    label: str
    icon: str
    supported_types: list[ContentType]
```

校验规则：
- `action_id` 不能为空。
- `label` 不能为空。
- `supported_types` 不能为空。

### 4.3 `PluginResult`

```python
@dataclass
class PluginResult:
    success: bool
    content_type: ContentType = ContentType.TEXT
    text_content: Optional[str] = None
    image_data: Optional[bytes] = None
    action: PluginResultAction = PluginResultAction.COPY
    error_message: Optional[str] = None
    cancelled: bool = False
```

当前约束：
- `cancelled=True` 会强制 `success=False`。
- `success=True` 且 `action != NONE` 时，至少要返回 `text_content` 或 `image_data`。

### 4.4 `PluginBase`

必须实现的抽象方法：
- `get_id()`
- `get_name()`
- `get_actions()`
- `execute(...)`

可选覆盖的方法：
- `get_description()`
- `on_load()`
- `on_unload()`
- `on_config_changed(config)`

运行时注入的辅助属性和方法：
- `logger`
- `get_config()`
- `get_cloud_client()`
- `check_credits(required)`
- `get_balance()`

### 4.5 执行上下文

`execute()` 会在工作线程中运行，应该遵守以下约束：
- 不直接操作 Qt 控件。
- 长耗时任务需要周期性检查 `cancel_check()`。
- 需要时通过 `progress_callback(percent, message)` 汇报进度。

## 5. 运行时行为

### 5.1 进程和线程模型

`PluginManager.run_action()` 只允许同时存在一个活跃任务。若已有插件在执行，新请求会被拒绝，并返回“busy”提示。

`PluginWorker` 负责在 `QThread` 中调用插件 `execute()`，并把进度、成功、失败和取消状态通过信号发回主线程。

### 5.2 超时与取消

- 超时时间来自 `manifest.timeout`，缺省为 `30` 秒。
- 用户可以在插件执行反馈条上取消任务。
- 超时或取消后，插件任务会被标记为取消，并在结束后做清理。

### 5.3 结果处理

主窗口在 `ui/main_window.py` 中消费插件结果：
- `COPY`：构造新的 `TextClipboardItem` 或 `ImageClipboardItem`，复制到系统剪贴板。
- `SAVE`：生成新条目并写入仓库。
- `REPLACE`：调用 `ClipboardRepository.update_item_content()` 更新原条目。
- `NONE`：只展示插件已执行完成，不修改剪贴板或历史列表。

仓库层的 `update_item_content()` 已经会在跨类型替换时清理另一侧 payload，避免旧的 `text_content`、`image_data` 或 `image_thumbnail` 残留。

## 6. 配置与插件商店

### 6.1 本地配置

插件配置存放在：

```text
<config_dir>/plugins/<plugin_id>/config.json
```

`PluginConfigDialog` 会根据 `config_schema` 自动生成表单，支持的字段类型如下：
- `string`
- `number`
- `boolean`
- `select`

其中 `secret: true` 的字符串字段会使用密码输入框。

### 6.2 设置页插件管理

设置页的「插件」标签提供：
- 查看已安装插件。
- 启用或禁用插件。
- 打开用户插件目录。
- 重载插件。
- 查看插件日志目录。
- 打开插件开发文档链接。
- 从云端插件商店安装插件。

插件商店使用 `settings().cloud_api_url` 作为基地址，请求：
- `GET /api/plugins/store`
- `GET /api/plugins/download/<plugin_id>`

安装后的插件会落到用户插件目录中，然后由 `PluginManager.reload_plugins()` 重新扫描。

## 7. 权限模型

当前权限模型只作用于注入给插件的云端客户端：
- `core/cloud_api.py` 中用 `@requires_plugin_permission("network")` 和 `@requires_plugin_permission("credits")` 标记可调用方法。
- `PluginManager._PluginCloudClientProxy` 会在访问这些方法时检查插件 `manifest.permissions`。
- 未声明对应权限的插件会收到 `PermissionError`。

这意味着权限检查是“按方法级别”生效的，而不是对整个插件模块做沙箱隔离。

## 8. 内置插件现状

### 8.1 `smart_text`

支持的动作包括：
- 清理格式
- 转大写 / 转小写 / 首字母大写
- 转 `snake_case` / `camelCase`
- URL 编码 / 解码
- Base64 编码 / 解码
- JSON 格式化 / 压缩
- 去重行 / 排序行
- 文本统计

### 8.2 `ai_image_gen`

这个插件只负责启动外部 `chat_image_gen` 工具，不直接生成图片。它会：
- 从环境变量 `CHAT_IMAGE_GEN_DIR`、插件配置或约定路径中定位外部工具。
- 在临时文件中传递文本或图片输入。
- 使用 `action=NONE` 返回，避免把结果误写回剪贴板。

## 9. 开发与测试

### 9.1 推荐的最小插件

```python
from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ContentType, TextClipboardItem


class DemoPlugin(PluginBase):
    def get_id(self):
        return "demo"

    def get_name(self):
        return "Demo"

    def get_actions(self):
        return [
            PluginAction("reverse", "反转文本", "↔", [ContentType.TEXT]),
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        if action_id != "reverse" or not isinstance(item, TextClipboardItem):
            return PluginResult(success=False, error_message="不支持的操作")
        return PluginResult(
            success=True,
            content_type=ContentType.TEXT,
            text_content=item.text_content[::-1],
            action=PluginResultAction.COPY,
        )
```

### 9.2 测试辅助

`PluginTestHelper` 便于构造测试用 `ClipboardItem` 并直接调用插件 `execute()`。当前仓库的测试重点仍然在：
- 数据模型
- 数据库
- 仓库
- 启动 smoke test

插件执行和云端联动属于后续更适合补充的集成测试范围。

## 10. 相关文件

- `core/plugin_api.py`
- `core/plugin_manager.py`
- `core/cloud_api.py`
- `ui/plugin_config_dialog.py`
- `ui/settings_dialog.py`
- `ui/main_window.py`
- `plugins/smart_text/`
- `plugins/ai_image_gen/`
