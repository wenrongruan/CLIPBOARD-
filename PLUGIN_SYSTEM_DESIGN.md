# SharedClipboard 插件系统设计方案

## 1. 背景与目标

SharedClipboard 目前是一个功能完整的剪贴板历史管理工具，但缺乏可扩展性。用户希望能对已复制的内容进行二次处理，例如：

- **文本内容**：AI 翻译、AI 编辑、摘要提取、格式转换、代码格式化
- **图片内容**：AI 图像编辑、OCR 文字识别、图片压缩、水印添加

### 设计目标

- **简单易用**：插件只需放入 `plugins/` 目录即可，无需 pip 安装
- **安全透明**：插件声明所需权限，用户知情授权
- **类型感知**：插件声明支持的内容类型（文本/图片），系统自动过滤
- **可配置**：AI 类插件可通过统一配置界面管理 API Key 等参数
- **健壮可靠**：插件异步执行，支持取消/超时，崩溃不影响主程序
- **跨平台**：Windows / macOS / Linux 均可正常运行

---

## 2. Quick Start: 5 分钟创建你的第一个插件

### 第 1 步：创建插件目录

```
plugins/
└── my_plugin/
    ├── manifest.json    ← 插件清单
    └── plugin.py        ← 插件代码
```

### 第 2 步：编写 manifest.json

```json
{
    "id": "my_plugin",
    "name": "我的插件",
    "version": "1.0.0",
    "description": "一个简单的示例插件",
    "entry_point": "plugin.py"
}
```

### 第 3 步：编写 plugin.py

```python
from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ClipboardItem, ContentType


class MyPlugin(PluginBase):
    def get_id(self):
        return "my_plugin"

    def get_name(self):
        return "我的插件"

    def get_description(self):
        return "一个简单的示例插件"

    def get_actions(self):
        return [
            PluginAction(
                action_id="reverse",
                label="反转文本",
                icon="🔄",
                supported_types=[ContentType.TEXT],
            )
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        if action_id == "reverse" and item.text_content:
            return PluginResult(
                success=True,
                content_type=ContentType.TEXT,
                text_content=item.text_content[::-1],
                action=PluginResultAction.COPY,
            )
        return PluginResult(success=False, error_message="无文本内容")
```

### 第 4 步：重启应用

在设置 → 插件选项卡中确认插件已加载。

### 第 5 步：使用插件

右键点击任意剪贴板文本条目 → 选择"反转文本" → 结果自动复制到剪贴板。

---

## 3. 插件目录结构

```
plugins/
├── example_uppercase/          # 示例：文本转大写
│   ├── manifest.json           # 插件清单（必需）
│   └── plugin.py               # 插件入口（必需）
├── ai_translate/               # 示例：AI 翻译
│   ├── manifest.json
│   ├── plugin.py
│   └── config.json             # 插件自有配置（由框架自动管理）
└── image_editor/               # 示例：AI 图像编辑
    ├── manifest.json
    ├── plugin.py
    └── assets/                 # 插件资源文件（可选）
```

插件搜索路径（按优先级）：
1. **项目内置**：`<app_root>/plugins/` — 随应用分发的示例插件
2. **用户安装**：`<config_dir>/plugins/` — 用户自行添加的插件
   - Windows: `%APPDATA%/SharedClipboard/plugins/`
   - macOS: `~/Library/Application Support/SharedClipboard/plugins/`
   - Linux: `~/.config/SharedClipboard/plugins/`

---

## 4. 插件清单格式 (`manifest.json`)

### 完整示例

```json
{
    "id": "ai_translate",
    "name": "AI 翻译",
    "version": "1.0.0",
    "description": "使用 AI 将剪贴板文本翻译为多种语言",
    "author": "Your Name",
    "entry_point": "plugin.py",
    "min_app_version": "1.1.0",
    "api_version": "1",
    "homepage": "https://github.com/example/ai-translate-plugin",
    "license": "MIT",
    "permissions": ["network", "clipboard_write"],
    "dependencies": {
        "pip": ["openai>=1.0.0"]
    },
    "config_schema": {
        "api_key": {
            "type": "string",
            "label": "API Key",
            "description": "OpenAI API Key",
            "required": true,
            "secret": true
        },
        "model": {
            "type": "select",
            "label": "模型",
            "options": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
            "default": "gpt-4o-mini"
        },
        "base_url": {
            "type": "string",
            "label": "API Base URL",
            "default": "https://api.openai.com/v1"
        }
    },
    "timeout": 60
}
```

### 字段说明

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | string | 是 | - | 唯一标识符，snake_case |
| `name` | string | 是 | - | 显示名称（支持中文） |
| `version` | string | 是 | - | 语义化版本号 |
| `description` | string | 是 | - | 简短描述 |
| `entry_point` | string | 是 | - | 入口 Python 文件路径 |
| `author` | string | 否 | - | 作者名 |
| `min_app_version` | string | 否 | - | 最低兼容的应用版本 |
| `api_version` | string | 否 | `"1"` | 插件 API 版本号 |
| `homepage` | string | 否 | - | 插件项目主页 |
| `license` | string | 否 | - | 许可证 |
| `permissions` | list | 否 | `["clipboard_read", "clipboard_write"]` | 权限声明（详见第 7 节） |
| `dependencies` | object | 否 | `{}` | 依赖声明 |
| `config_schema` | object | 否 | `{}` | 配置项声明（详见第 4.1 节） |
| `timeout` | number | 否 | `30` | 执行超时秒数 |

### 4.1 配置项声明 (`config_schema`)

插件通过 `config_schema` 声明需要的配置项，框架会自动生成配置 UI 并管理存储。

**支持的类型**：

| type | 控件 | 额外属性 |
|------|------|----------|
| `string` | QLineEdit | `secret: true` 时使用密码模式 |
| `number` | QSpinBox | `min`, `max`, `step` |
| `boolean` | QCheckBox | - |
| `select` | QComboBox | `options: [...]` |

**每个配置项的通用属性**：

| 属性 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `type` | string | 是 | string / number / boolean / select |
| `label` | string | 是 | 显示标签 |
| `description` | string | 否 | 说明文字 |
| `default` | any | 否 | 默认值 |
| `required` | bool | 否 | 是否必填 |
| `secret` | bool | 否 | 是否为敏感信息（密码模式） |

**配置存储位置**：`<config_dir>/plugins/<plugin_id>/config.json`

---

## 5. 插件 API 定义

### 5.1 核心数据结构

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional
from core.models import ContentType

class PluginResultAction(Enum):
    """插件执行结果的处理方式"""
    COPY = "copy"        # 将结果复制到系统剪贴板
    SAVE = "save"        # 将结果保存为新的剪贴板条目
    REPLACE = "replace"  # 替换原有条目的内容

@dataclass
class PluginAction:
    """插件提供的单个操作"""
    action_id: str                        # 操作标识，如 "translate_en"
    label: str                            # 显示名称，如 "翻译为英文"
    icon: str                             # 单个 emoji 图标，如 "🌐"
    supported_types: List[ContentType]    # 支持的内容类型列表

@dataclass
class PluginResult:
    """插件执行结果"""
    success: bool                                          # 是否成功
    content_type: ContentType = ContentType.TEXT            # 结果内容类型
    text_content: Optional[str] = None                     # 文本结果
    image_data: Optional[bytes] = None                     # 图片结果（原始字节）
    action: PluginResultAction = PluginResultAction.COPY   # 结果处理方式
    error_message: Optional[str] = None                    # 失败时的错误信息
```

### 5.2 插件基类 (`PluginBase`)

所有插件必须继承此基类。抽象方法（必须实现）仅 4 个，其余为可选覆盖。

```python
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional, List

class PluginBase(ABC):
    """插件基类 - 所有插件必须继承此类"""

    # ========== 抽象方法（必须实现） ==========

    @abstractmethod
    def get_id(self) -> str:
        """返回插件唯一标识（必须与 manifest.json 中的 id 一致）"""

    @abstractmethod
    def get_name(self) -> str:
        """返回插件显示名称"""

    @abstractmethod
    def get_actions(self) -> List[PluginAction]:
        """返回插件提供的所有操作列表"""

    @abstractmethod
    def execute(
        self,
        action_id: str,
        item: ClipboardItem,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> PluginResult:
        """
        执行插件操作。

        参数:
            action_id: 要执行的操作标识
            item: 剪贴板条目（包含完整内容）
            progress_callback: 进度回调 (percent: 0-100, message: str)
            cancel_check: 取消检查函数，返回 True 表示用户已取消

        返回:
            PluginResult 包含执行结果

        注意:
            - 此方法在工作线程中调用，禁止直接操作 Qt 控件
            - 长时间操作应定期调用 cancel_check() 检查取消状态
            - 使用 progress_callback 报告进度
        """

    # ========== 可选覆盖 ==========

    def get_description(self) -> str:
        """返回插件简短描述（默认从 manifest 读取）"""
        return ""

    def on_load(self) -> None:
        """插件加载时调用 — 用于初始化"""
        pass

    def on_unload(self) -> None:
        """插件卸载时调用 — 用于清理资源"""
        pass

    def on_config_changed(self, config: dict) -> None:
        """配置变更时调用 — 用于响应设置变化"""
        pass

    # ========== 框架注入（插件可直接使用，无需覆盖） ==========

    @property
    def logger(self) -> logging.Logger:
        """插件专属 logger（由框架自动注入）"""
        return getattr(self, '_logger', logging.getLogger('plugin.unknown'))

    def get_config(self) -> dict:
        """获取插件配置（由框架自动从 config.json 加载）"""
        return getattr(self, '_config', {})
```

---

## 6. 插件管理器架构

### 6.1 整体流程

```mermaid
flowchart TB
    subgraph 启动时
        A[扫描 plugins 目录] --> B[读取 manifest.json]
        B --> C{校验版本 & 依赖}
        C -->|通过| D[importlib 动态导入]
        C -->|失败| E[标记为不可用<br/>记录原因]
        D --> F[实例化插件]
        F --> G[注入 logger + config]
        G --> H[调用 on_load]
        H --> I[就绪]
    end

    subgraph 运行时
        J[用户右键点击条目] --> K[get_actions_for_item<br/>按内容类型过滤]
        K --> L[构建右键菜单]
        L --> M{用户选择动作}
        M --> N{是否有任务执行中?}
        N -->|是| O[提示"有插件正在执行"]
        N -->|否| P[创建 PluginWorker]
        P --> Q[启动超时计时器]
        Q --> R[工作线程执行<br/>plugin.execute]
        R --> S{执行结果}
        S -->|成功| T[处理结果<br/>COPY / SAVE / REPLACE]
        S -->|失败| U[显示错误信息]
        S -->|取消| V[静默结束]
        S -->|超时| W[自动取消 + 提示]
    end
```

### 6.2 PluginManager

`PluginManager` 是一个 `QObject`，负责插件的完整生命周期：

```python
class PluginManager(QObject):
    # 信号
    action_progress = Signal(int, str)        # (进度百分比, 消息)
    action_finished = Signal(object, object)  # (PluginResult, 原始 ClipboardItem)
    action_error = Signal(str)                # 错误消息

    def __init__(self):
        self._plugins: dict[str, PluginBase] = {}       # plugin_id -> 实例
        self._manifests: dict[str, dict] = {}            # plugin_id -> manifest
        self._active_worker: Optional[PluginWorker] = None  # 并发互斥
        self._timeout_timer: Optional[QTimer] = None

    # ========== 生命周期 ==========

    def load_plugins(self):
        """扫描并加载所有插件"""
        # 1. 遍历插件目录，读取 manifest.json
        # 2. 校验版本兼容性 (_check_version_compat)
        # 3. 校验依赖 (_check_dependencies)
        # 4. importlib 动态导入
        # 5. 实例化插件，注入 _logger 和 _config
        # 6. 调用 on_load()

    def unload_all(self):
        """卸载所有插件（应用退出时调用）"""

    def reload_plugins(self):
        """重新加载所有插件（设置页"重新加载"按钮）"""
        # unload_all() + load_plugins()

    # ========== 查询 ==========

    def get_loaded_plugins(self) -> List[dict]:
        """返回已加载插件信息列表（用于设置页显示）"""
        # 返回 [{id, name, version, description, enabled, status, permissions, missing_deps}, ...]

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        """检查插件是否启用"""

    def get_actions_for_item(self, item: ClipboardItem) -> List[Tuple[str, PluginAction]]:
        """返回当前条目可用的插件动作列表 [(plugin_id, action), ...]"""
        # 遍历已启用插件，按 supported_types 过滤

    # ========== 执行 ==========

    def run_action(self, plugin_id: str, action_id: str, item: ClipboardItem):
        """在工作线程中执行插件动作（带并发控制和超时）"""
        # 1. 检查 _active_worker 是否为 None（并发互斥）
        # 2. 创建 PluginWorker，连接信号
        # 3. 启动超时 QTimer（从 manifest.timeout 或默认 30s）
        # 4. 启动 worker

    def cancel_action(self):
        """取消当前执行的插件动作"""
        # 调用 _active_worker.cancel()

    # ========== 内部方法 ==========

    def _check_version_compat(self, manifest: dict) -> bool:
        """校验 min_app_version"""
        min_ver = manifest.get("min_app_version")
        if not min_ver:
            return True
        try:
            min_parts = tuple(int(x) for x in min_ver.split("."))
            app_parts = tuple(int(x) for x in Config.APP_VERSION.split("."))
            return app_parts >= min_parts
        except (ValueError, AttributeError):
            return True

    def _check_dependencies(self, manifest: dict) -> Tuple[bool, List[str]]:
        """检查 pip 依赖是否已安装"""
        missing = []
        for dep in manifest.get("dependencies", {}).get("pip", []):
            pkg_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip()
            try:
                importlib.import_module(pkg_name)
            except ImportError:
                missing.append(dep)
        return len(missing) == 0, missing

    def _init_plugin_logger(self, plugin_id: str) -> logging.Logger:
        """为插件创建独立 logger"""
        logger = logging.getLogger(f"plugin.{plugin_id}")
        log_dir = Config.get_config_dir() / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / f"plugin_{plugin_id}.log",
            maxBytes=1024 * 1024,  # 1MB
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        return logger

    def _load_plugin_config(self, plugin_id: str) -> dict:
        """加载插件配置"""
        config_path = Config.get_config_dir() / "plugins" / plugin_id / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_plugin_config(self, plugin_id: str, config: dict):
        """保存插件配置"""
        config_dir = Config.get_config_dir() / "plugins" / plugin_id
        config_dir.mkdir(parents=True, exist_ok=True)
        with open(config_dir / "config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
```

### 6.3 PluginWorker (QThread)

```python
class PluginWorker(QThread):
    """在工作线程中执行插件操作，支持取消"""
    progress = Signal(int, str)        # 进度更新
    finished = Signal(object)          # PluginResult
    error = Signal(str)                # 错误消息

    def __init__(self, plugin: PluginBase, action_id: str, item: ClipboardItem):
        super().__init__()
        self._plugin = plugin
        self._action_id = action_id
        self._item = item
        self._cancelled = False

    def cancel(self):
        """请求取消执行"""
        self._cancelled = True
        self.requestInterruption()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            result = self._plugin.execute(
                self._action_id,
                self._item,
                progress_callback=self._on_progress,
                cancel_check=lambda: self._cancelled,
            )
            if self._cancelled:
                return  # 取消后不发射结果信号
            self.finished.emit(result)
        except Exception as e:
            self._plugin.logger.exception(
                f"Plugin execution failed: {self._action_id}"
            )
            if not self._cancelled:
                self.error.emit(f"{self._plugin.get_name()}: {str(e)}")

    def _on_progress(self, percent: int, message: str):
        if not self._cancelled:
            self.progress.emit(percent, message)
```

### 6.4 错误隔离策略

| 场景 | 处理方式 |
|------|---------|
| manifest.json 格式错误 | 跳过该插件，记录 WARNING 日志 |
| 版本不兼容 | 标记为不可用，设置页显示原因 |
| 依赖缺失 | 标记为不可用，设置页提供"安装依赖"按钮 |
| 加载时异常 | 跳过该插件，记录异常堆栈到日志 |
| 执行时异常 | 捕获异常，返回 `PluginResult(success=False)`，记录堆栈 |
| 执行超时 | 自动取消 worker，显示超时提示 |

---

## 7. 安全性设计

### 设计原则

采用**声明式权限 + 用户知情**模型。不做运行时沙箱（Python 无原生沙箱机制，`RestrictedPython` 对 AI SDK 不兼容，subprocess 隔离无法共享对象）。这与 VS Code 扩展、Obsidian 插件采用相同的安全模型。

### 权限类型

| 权限 | 说明 | 默认 |
|------|------|------|
| `clipboard_read` | 读取剪贴板内容 | 所有插件默认拥有 |
| `clipboard_write` | 写回剪贴板 / 修改条目 | 所有插件默认拥有 |
| `network` | 访问网络（AI 类插件需要） | 需声明 |
| `file_read` | 读取文件系统 | 需声明 |
| `file_write` | 写入文件系统 | 需声明 |

### UI 展示

设置页插件列表中，声明了 `network` / `file_write` 等敏感权限的插件，在描述下方显示权限标签：

```
☑ AI 翻译 v1.0.0
  使用 AI 将文本翻译为多种语言
  🌐 网络访问
```

首次启用声明敏感权限的插件时，弹出确认对话框。

---

## 8. UI 集成设计

### 8.1 右键上下文菜单（主交互方式）

在 `MainWindow` 中为 `QListWidget` 启用自定义右键菜单：

```
┌──────────────────────┐
│ 📋 复制              │  ← 内置操作
│ ★  收藏              │
│ 🗑  删除              │
├──────────────────────┤  ← 分隔线
│ 🌐 AI 翻译           │  ← 多动作插件 → 子菜单
│   ├ 翻译为英文        │
│   ├ 翻译为日文        │
│   └ 翻译为韩文        │
│ ✨ AI 编辑            │
│   ├ 润色文本          │
│   ├ 扩写              │
│   └ 缩写              │
│ Aa 文本转大写         │  ← 单动作插件直接显示
└──────────────────────┘
```

**菜单构建规则**：
- 内置操作（复制、收藏、删除）始终在最上方
- 分隔线后显示插件动作
- 多动作插件使用子菜单（QMenu），单动作插件直接作为菜单项
- 只显示支持当前内容类型的动作
- 禁用的插件不显示

### 8.2 进度显示与取消

插件执行期间，复用现有的 `copy_feedback_label` 样式，在主窗口底部显示进度条：

```
┌──────────────────────────────┐
│  🔄 AI 翻译中... 45%  [取消] │  ← 执行中（含取消按钮）
└──────────────────────────────┘

┌──────────────────────────────┐
│  ✅ 已复制到剪贴板            │  ← 成功（2 秒后自动消失）
└──────────────────────────────┘

┌──────────────────────────────┐
│  ❌ 翻译失败: API Key 无效    │  ← 失败
└──────────────────────────────┘

┌──────────────────────────────┐
│  ⏰ 插件执行超时              │  ← 超时
└──────────────────────────────┘
```

### 8.3 结果处理

| PluginResultAction | 行为 |
|-------------------|------|
| `COPY` | 将结果复制到系统剪贴板，显示"已复制到剪贴板" |
| `SAVE` | 将结果保存为新的剪贴板条目，刷新列表 |
| `REPLACE` | 更新原条目内容，刷新列表 |

### 8.4 设置页「插件」选项卡

在现有 SettingsDialog 的「筛选与存储」和「关于」选项卡之间插入：

```
┌───────────────────────────────────────────────┐
│ 通用 │ 数据库 │ 筛选与存储 │ 插件 │ 关于      │
├───────────────────────────────────────────────┤
│                                               │
│  已安装插件                                    │
│  ┌───────────────────────────────────────┐    │
│  │ ☑ AI 翻译 v1.0.0              [⚙ 设置]│    │
│  │   使用 AI 将文本翻译为多种语言         │    │
│  │   🌐 网络访问                          │    │
│  ├───────────────────────────────────────┤    │
│  │ ☑ 文本转大写 v1.0.0                   │    │
│  │   将文本转换为大写字母                 │    │
│  ├───────────────────────────────────────┤    │
│  │ ☐ 图像编辑 v0.1.0                     │    │
│  │   AI 图像编辑工具                      │    │
│  │   ⚠ 缺少依赖: Pillow>=10.0.0         │    │
│  └───────────────────────────────────────┘    │
│                                               │
│  [📂 打开插件目录]  [🔄 重新加载]  [📋 查看日志]│
│                                               │
└───────────────────────────────────────────────┘
```

### 8.5 插件配置对话框

点击插件的"⚙ 设置"按钮，根据 `config_schema` 自动生成配置表单：

```
┌─────────────────────────────────┐
│ AI 翻译 - 设置                   │
├─────────────────────────────────┤
│                                 │
│  API Key *                      │
│  ┌─────────────────────────┐   │
│  │ ●●●●●●●●●●●●●●●●●●     │   │  ← secret: true → 密码模式
│  └─────────────────────────┘   │
│  OpenAI API Key                 │
│                                 │
│  模型                           │
│  ┌─────────────────────────┐   │
│  │ gpt-4o-mini         ▼   │   │  ← type: select
│  └─────────────────────────┘   │
│                                 │
│  API Base URL                   │
│  ┌─────────────────────────┐   │
│  │ https://api.openai.com/v│   │
│  └─────────────────────────┘   │
│                                 │
│         [取消]  [保存]          │
└─────────────────────────────────┘
```

---

## 9. 示例插件

### 9.1 文本转大写（内置示例）

`plugins/example_uppercase/manifest.json`:
```json
{
    "id": "example_uppercase",
    "name": "文本转大写",
    "version": "1.0.0",
    "description": "将文本内容转换为大写字母",
    "author": "SharedClipboard",
    "entry_point": "plugin.py",
    "min_app_version": "1.1.0"
}
```

`plugins/example_uppercase/plugin.py`:
```python
from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ClipboardItem, ContentType


class UppercasePlugin(PluginBase):
    def get_id(self):
        return "example_uppercase"

    def get_name(self):
        return "文本转大写"

    def get_actions(self):
        return [
            PluginAction(
                action_id="to_upper",
                label="转换为大写",
                icon="Aa",
                supported_types=[ContentType.TEXT],
            )
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        if action_id == "to_upper" and item.text_content:
            if progress_callback:
                progress_callback(50, "转换中...")
            result_text = item.text_content.upper()
            if progress_callback:
                progress_callback(100, "完成")
            return PluginResult(
                success=True,
                content_type=ContentType.TEXT,
                text_content=result_text,
                action=PluginResultAction.COPY,
            )
        return PluginResult(success=False, error_message="无文本内容")
```

### 9.2 AI 翻译插件（第三方示例）

展示配置机制、依赖处理、取消检查、日志记录的完整最佳实践：

`plugins/ai_translate/manifest.json`:
```json
{
    "id": "ai_translate",
    "name": "AI 翻译",
    "version": "1.0.0",
    "description": "使用 AI 将剪贴板文本翻译为多种语言",
    "author": "Your Name",
    "entry_point": "plugin.py",
    "min_app_version": "1.1.0",
    "permissions": ["network"],
    "dependencies": {
        "pip": ["openai>=1.0.0"]
    },
    "config_schema": {
        "api_key": {
            "type": "string",
            "label": "API Key",
            "description": "OpenAI API Key",
            "required": true,
            "secret": true
        },
        "model": {
            "type": "select",
            "label": "模型",
            "options": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
            "default": "gpt-4o-mini"
        },
        "base_url": {
            "type": "string",
            "label": "API Base URL",
            "default": "https://api.openai.com/v1"
        }
    },
    "timeout": 60
}
```

`plugins/ai_translate/plugin.py`:
```python
from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ClipboardItem, ContentType


class AITranslatePlugin(PluginBase):
    def get_id(self):
        return "ai_translate"

    def get_name(self):
        return "AI 翻译"

    def get_actions(self):
        return [
            PluginAction("translate_en", "翻译为英文", "🇬🇧", [ContentType.TEXT]),
            PluginAction("translate_ja", "翻译为日文", "🇯🇵", [ContentType.TEXT]),
            PluginAction("translate_ko", "翻译为韩文", "🇰🇷", [ContentType.TEXT]),
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        # 1. 参数校验
        lang_map = {
            "translate_en": "English",
            "translate_ja": "Japanese",
            "translate_ko": "Korean",
        }
        target_lang = lang_map.get(action_id)
        if not target_lang or not item.text_content:
            return PluginResult(success=False, error_message="不支持的操作")

        # 2. 读取配置
        config = self.get_config()
        api_key = config.get("api_key")
        if not api_key:
            return PluginResult(
                success=False,
                error_message="请在插件设置中配置 API Key",
            )

        model = config.get("model", "gpt-4o-mini")
        base_url = config.get("base_url", "https://api.openai.com/v1")

        # 3. 检查取消
        if cancel_check and cancel_check():
            return PluginResult(success=False, error_message="已取消")

        if progress_callback:
            progress_callback(10, "正在连接 AI 服务...")

        # 4. 调用 API
        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)

            self.logger.info(f"Translating to {target_lang}, model={model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": f"Translate to {target_lang}. Return only the translation."},
                    {"role": "user", "content": item.text_content},
                ],
            )

            # 5. 再次检查取消（API 调用后）
            if cancel_check and cancel_check():
                return PluginResult(success=False, error_message="已取消")

            if progress_callback:
                progress_callback(90, "翻译完成")

            translated = response.choices[0].message.content
            self.logger.info(f"Translation complete: {len(translated)} chars")

            return PluginResult(
                success=True,
                content_type=ContentType.TEXT,
                text_content=translated,
                action=PluginResultAction.COPY,
            )
        except Exception as e:
            self.logger.exception("Translation failed")
            return PluginResult(success=False, error_message=f"翻译失败: {e}")
```

---

## 10. 插件开发教程

### 从零创建一个 AI 翻译插件

#### 准备工作

1. 确保 SharedClipboard >= 1.1.0
2. 安装 openai: `pip install openai`
3. 准备一个 OpenAI API Key

#### 创建插件骨架

```bash
# 在 plugins 目录下创建
mkdir plugins/ai_translate
```

创建 `manifest.json`（参考第 9.2 节示例）和 `plugin.py`。

#### 关键开发模式

**模式 1：读取配置**
```python
config = self.get_config()
api_key = config.get("api_key")
if not api_key:
    return PluginResult(success=False, error_message="请配置 API Key")
```

**模式 2：进度报告**
```python
if progress_callback:
    progress_callback(10, "正在连接...")
# ... 耗时操作 ...
if progress_callback:
    progress_callback(90, "几乎完成")
```

**模式 3：取消检查**
```python
# 在每个耗时步骤之间检查
if cancel_check and cancel_check():
    return PluginResult(success=False, error_message="已取消")
```

**模式 4：日志记录**
```python
self.logger.info("开始翻译")
self.logger.error(f"API 调用失败: {e}")
self.logger.exception("完整堆栈")  # 自动记录异常堆栈
```

#### 测试插件

使用 `PluginTestHelper` 快速测试：

```python
# test_plugin.py（在插件目录下运行）
import sys
sys.path.insert(0, "../..")  # 添加项目根目录到路径

from core.plugin_api import PluginTestHelper
from plugin import AITranslatePlugin

plugin = AITranslatePlugin()
plugin._config = {"api_key": "your-key-here", "model": "gpt-4o-mini"}

result = PluginTestHelper.run_plugin(plugin, "translate_en", "你好世界")
print(f"成功: {result.success}")
print(f"结果: {result.text_content}")
print(f"错误: {result.error_message}")
```

#### 调试技巧

- 插件日志位于 `<config_dir>/logs/plugin_<id>.log`
- 设置页 → 插件 → "查看日志"可直接打开日志目录
- `self.logger.exception(...)` 会记录完整的异常堆栈

---

## 11. API 参考速查表

### PluginBase 方法一览

| 方法 | 类型 | 说明 |
|------|------|------|
| `get_id()` | 抽象 | 返回插件 ID |
| `get_name()` | 抽象 | 返回显示名称 |
| `get_actions()` | 抽象 | 返回操作列表 |
| `execute(action_id, item, progress_callback, cancel_check)` | 抽象 | 执行操作 |
| `get_description()` | 可选 | 返回描述 |
| `on_load()` | 可选 | 加载时回调 |
| `on_unload()` | 可选 | 卸载时回调 |
| `on_config_changed(config)` | 可选 | 配置变更回调 |
| `logger` | 属性 | 插件专属 logger |
| `get_config()` | 方法 | 获取插件配置 dict |

### PluginAction 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `action_id` | str | 操作标识 |
| `label` | str | 显示名称 |
| `icon` | str | 图标（emoji 或文本） |
| `supported_types` | List[ContentType] | 支持的内容类型 |

### PluginResult 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `success` | bool | - | 是否成功 |
| `content_type` | ContentType | TEXT | 结果类型 |
| `text_content` | str? | None | 文本结果 |
| `image_data` | bytes? | None | 图片结果 |
| `action` | PluginResultAction | COPY | 结果处理方式 |
| `error_message` | str? | None | 错误信息 |

### manifest.json 字段

| 字段 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `id` | 是 | - | 唯一标识 |
| `name` | 是 | - | 显示名称 |
| `version` | 是 | - | 版本号 |
| `description` | 是 | - | 描述 |
| `entry_point` | 是 | - | 入口文件 |
| `author` | 否 | - | 作者 |
| `min_app_version` | 否 | - | 最低应用版本 |
| `api_version` | 否 | `"1"` | API 版本 |
| `homepage` | 否 | - | 项目主页 |
| `license` | 否 | - | 许可证 |
| `permissions` | 否 | `[clipboard_read, clipboard_write]` | 权限 |
| `dependencies.pip` | 否 | `[]` | pip 依赖 |
| `config_schema` | 否 | `{}` | 配置声明 |
| `timeout` | 否 | `30` | 超时秒数 |

---

## 12. 测试指南

### 12.1 PluginTestHelper

在 `core/plugin_api.py` 中提供测试辅助类：

```python
class PluginTestHelper:
    """插件开发者测试工具"""

    @staticmethod
    def create_test_item(
        text: str = "Hello World",
        content_type: ContentType = ContentType.TEXT,
    ) -> ClipboardItem:
        """创建测试用 ClipboardItem"""
        return ClipboardItem(
            id=1,
            content_type=content_type,
            text_content=text if content_type == ContentType.TEXT else None,
            content_hash="test_hash_000000000000000000000000",
            preview=text[:50] if text else "[test image]",
            device_id="test_device",
            device_name="Test Device",
        )

    @staticmethod
    def run_plugin(
        plugin: PluginBase,
        action_id: str,
        text: str = "Hello World",
    ) -> PluginResult:
        """快速执行插件并返回结果"""
        item = PluginTestHelper.create_test_item(text)
        return plugin.execute(action_id, item)
```

### 12.2 项目级测试

在 `tests/test_plugin_system.py` 中测试框架核心逻辑：

```python
def test_load_example_plugin():
    """测试示例插件能正常加载"""
    manager = PluginManager()
    manager.load_plugins()
    plugins = manager.get_loaded_plugins()
    assert any(p["id"] == "example_uppercase" for p in plugins)

def test_execute_uppercase():
    """测试大写插件执行"""
    from plugins.example_uppercase.plugin import UppercasePlugin
    plugin = UppercasePlugin()
    result = PluginTestHelper.run_plugin(plugin, "to_upper", "hello")
    assert result.success
    assert result.text_content == "HELLO"

def test_invalid_manifest():
    """测试无效 manifest 不会导致崩溃"""
    # 创建临时目录，放入无效 manifest
    # 验证 load_plugins() 正常返回，不抛异常

def test_concurrent_execution():
    """测试并发互斥"""
    # 验证第二次 run_action() 在第一个未完成时被拒绝
```

---

## 13. 需要修改的文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/plugin_api.py` | **新建** | PluginBase、PluginAction、PluginResult、PluginResultAction、PluginTestHelper |
| `core/plugin_manager.py` | **新建** | PluginManager、PluginWorker、依赖检查、版本校验、日志初始化 |
| `plugins/example_uppercase/manifest.json` | **新建** | 示例插件清单 |
| `plugins/example_uppercase/plugin.py` | **新建** | 示例插件实现 |
| `config.py` | **修改** | 添加 `get_plugins_enabled()`、`set_plugin_enabled()`、`get_user_plugins_dir()` |
| `main.py` | **修改** | 创建 PluginManager 并传递给 MainWindow，退出时卸载 |
| `ui/main_window.py` | **修改** | 右键菜单、插件执行、进度显示（含取消）、设置页插件选项卡、插件配置对话框 |
| `ui/styles.py` | **修改** | 添加插件进度条、权限标签等样式 |
| `i18n.py` | **修改** | 添加插件相关翻译键 |
| `core/repository.py` | **修改** | 添加 `update_item_content()` 方法（支持 REPLACE 操作） |

---

## 14. 实现优先级

| 阶段 | 内容 | 说明 |
|------|------|------|
| **P0 - 核心框架** | `plugin_api.py` + `plugin_manager.py` + `config.py` 修改 | 含取消机制、并发互斥、日志框架 |
| **P0 - 配置机制** | manifest `config_schema` + 配置存储 + 配置 UI 生成 | AI 插件的前置条件 |
| **P0 - UI 集成** | 右键菜单 + 进度条（含取消按钮）+ `main.py` 集成 | 核心交互 |
| **P1 - 设置页** | 插件选项卡（启用/禁用 + 权限标识 + 配置入口） | 管理界面 |
| **P1 - 示例插件** | `example_uppercase` 验证 API | 开发者参考 |
| **P1 - 安全声明** | permissions 字段 + 设置页权限展示 | 用户知情 |
| **P1 - 依赖管理** | dependencies 检查 + 安装按钮 | 第三方插件支持 |
| **P1 - 超时处理** | QTimer 超时 + manifest timeout 字段 | 健壮性 |
| **P1 - 测试工具** | PluginTestHelper + 示例测试 | 开发者体验 |
| **P2 - 完善** | REPLACE 操作、国际化、样式优化 | 细节打磨 |

---

## 15. 未来扩展方向

- **插件配置 UI 增强**：支持更多控件类型（颜色选择器、文件路径选择等）
- **插件市场**：在线浏览和安装插件
- **事件钩子**：插件可订阅剪贴板事件（新增、删除、同步等）
- **快捷键绑定**：为常用插件动作分配快捷键
- **批量操作**：对多个剪贴板条目批量执行插件操作
- **插件间通信**：允许插件组合使用（如 OCR -> 翻译管道），通过事件总线实现
- **热重载**：文件变更自动重新加载插件（开发模式）
