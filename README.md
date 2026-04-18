# SharedClipboard
跨平台剪贴板历史管理器，面向 Windows、macOS 和 Linux。

## 主要功能
- 记录文本和图片剪贴板历史。
- 支持搜索、收藏、固定到屏幕边缘。
- 支持系统托盘运行和全局热键唤出主窗口。
- 支持三种同步模式：`local`、`mysql`、`cloud`。
- 内置插件系统，当前仓库包含 `smart_text` 和 `ai_image_gen`。
- 设置页支持数据库、过滤、语言、热键、插件管理和云端同步入口。

## 当前项目结构
- `main.py`：应用入口，初始化托盘、剪贴板监听、同步服务和插件管理器。
- `config.py`：配置中心，负责 `settings.json`、数据目录、密钥存储和同步模式。
- `core/`：数据库、仓库、模型、同步、云端 API、插件系统。
- `ui/`：主窗口、设置页、插件配置页和云端登录界面。
- `plugins/`：内置插件和第三方插件目录。
- `tests/`：当前自动化测试。

## 快速开始
```bash
pip install -r requirements.txt
python main.py
```

## 依赖
- Python 3.11+
- PySide6
- Pillow
- pynput
- PyMySQL
- httpx
- keyring

## 配置与数据位置
应用会把运行数据放到系统配置目录下的 `SharedClipboard` 子目录中：
- Windows: `%APPDATA%\SharedClipboard\`
- macOS: `~/Library/Application Support/SharedClipboard/`
- Linux: `~/.config/SharedClipboard/`

常见文件和目录包括：
- `settings.json`：应用配置。
- `clipboard.db`：默认 SQLite 数据库。
- `plugins/`：用户安装插件。
- `logs/`：插件和应用日志。

密钥和令牌优先保存在系统 `keyring` 中。若系统后端不可用，应用会降级并在启动时提示。

## 插件系统
设置页的「插件」标签可查看已安装插件、启用或禁用插件、打开用户插件目录、查看插件日志，并从云端插件商店安装插件。

插件加载顺序由代码决定：
- 内置插件目录：仓库根目录下的 `plugins/`
- 用户插件目录：`<config_dir>/plugins/`
- 冻结包运行时的可执行文件同级 `plugins/`

## 测试
```bash
pytest -q
```

当前仓库测试结果：`61 passed`

## 说明
- 主窗口采用边缘停靠和托盘模式运行。
- 复制历史既支持本地 SQLite，也支持 MySQL 和云端同步。
- `REPLACE` 类插件操作会更新现有条目的内容，仓库层会清理被替换掉的另一种 payload，避免残留脏数据。
