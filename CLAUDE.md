# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作提供指导。

## 语言要求

请始终使用中文与用户对话。所有回复、解释和沟通都应使用中文。

## 项目概述

SharedClipboard（共享剪贴板）是一个 Windows 桌面应用，用于剪贴板历史管理和跨设备同步。基于 PySide6（Qt for Python）构建，以系统托盘应用形式运行，带有边缘吸附滑出窗口。

### 配套网站与 API

项目配套的网站和 API 代码位于：`E:/python/共享剪贴板/CLIPBOARD-/website`

> **注意**：`website/` 是一个独立的 Git 仓库（remote: `github.com:wenrongruan/jlike.git`），有自己的提交历史和 CLAUDE.md。对网站的修改需要在该目录下单独 commit 和 push。

### AI 生图工作台插件

AI 生图工作台插件项目位于：`E:/python/chat_image_gen`

## 运行应用

```bash
python main.py
```

## 依赖安装

```bash
pip install -r requirements.txt
```

核心依赖：PySide6 (>=6.6.0)、Pillow (>=10.0.0)

## 架构

### 核心层 (`core/`)
- **models.py**：`ClipboardItem` 数据类，包含 `ContentType` 枚举（TEXT/IMAGE）
- **database.py**：`DatabaseManager`，使用 SQLite/WAL 模式，FTS5 全文搜索，数据库锁重试逻辑
- **repository.py**：`ClipboardRepository`，提供分页和搜索的 CRUD 操作
- **clipboard_monitor.py**：`ClipboardMonitor`，每 500ms 轮询系统剪贴板，通过内容哈希去重检测文本/图片变化
- **sync_service.py**：`SyncService`，轮询数据库获取其他设备的新条目（默认 1 秒间隔）

### UI 层 (`ui/`)
- **edge_window.py**：`EdgeHiddenWindow` 基类 — 无边框窗口，吸附到屏幕边缘（左/右/上/下），带滑入/滑出动画
- **main_window.py**：`MainWindow` 继承 `EdgeHiddenWindow` — 搜索、分页、设置对话框
- **clipboard_item.py**：`ClipboardItemWidget`，渲染单个剪贴板条目
- **styles.py**：暗色主题 QSS 样式表

### 配置 (`config.py`)
- `Config` 类提供静态方法管理设置（存储在 `%APPDATA%/SharedClipboard/settings.json`）
- 设备 ID 由 MAC 地址哈希生成
- 数据库默认为项目根目录下的 `clipboard.db`

### 工具 (`utils/`)
- **hash_utils.py**：SHA-256 内容哈希（截断为 32 字符）
- **image_utils.py**：基于 Pillow 的缩略图生成

## 关键设计模式

1. **基于信号的通信**：Qt 信号将剪贴板变化和同步事件连接到 UI 更新
2. **轮询优于事件**：剪贴板监控使用 QTimer 轮询（在 Windows 上比 Qt 的 dataChanged 信号更可靠）
3. **数据库去重**：内容哈希防止重复条目
4. **延迟加载图片**：缩略图单独存储；仅在复制回剪贴板时加载完整图片

## 数据库结构

SQLite 数据库，支持 FTS5 搜索。主表 `clipboard_items`：
- id、content_type、text_content、image_data、image_thumbnail
- content_hash（唯一）、preview、device_id、device_name
- created_at（毫秒时间戳）、is_starred

## 多设备同步

设备共享同一数据库文件（如通过网络驱动器）。每个设备有唯一的 `device_id`。同步服务查询条件为 `id > last_sync_id AND device_id != this_device`。

## 跨平台支持

应用同时支持 Windows 和 macOS：

### 平台特定调整
- **config.py**：`Config.IS_WINDOWS`、`Config.IS_MACOS`、`Config.IS_LINUX` 标志
- **styles.py**：平台特定字体（Windows 用微软雅黑，macOS 用 SF Pro）
- **edge_window.py**：使用 `availableGeometry()` 适配 macOS 菜单栏和 Dock
- **main.py**：macOS 菜单栏图标，支持暗色模式的模板图片

### 构建 / 打包

#### Windows — 打包为单文件 exe

项目已有 `SharedClipboard.spec`，直接使用：

```bash
pip install pyinstaller   # 如未安装
pyinstaller SharedClipboard.spec --clean
```

产物：`dist/SharedClipboard.exe`（约 66MB，含所有依赖和 icons 资源）

spec 文件要点：
- 入口：`main.py`
- 数据文件：`('icons', 'icons')` — 打包 icons 目录
- hiddenimports：`pynput.keyboard._win32`、`pynput.mouse._win32`、`pymysql`
- 图标：`icons/app.ico`
- `console=False` — 无控制台窗口
- `upx=True` — 启用 UPX 压缩

如需修改打包配置（如添加新的 hiddenimport 或数据文件），直接编辑 `SharedClipboard.spec`。

#### macOS — 打包为 .app

使用 py2app：
```bash
pip install py2app
python build_macos.py py2app
```

产物：`dist/共享剪贴板.app`

也可用 PyInstaller：
```bash
pyinstaller --onefile --windowed --name "SharedClipboard" main.py
```
