# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作提供指导。

## 语言要求

请始终使用中文与用户对话。所有回复、解释和沟通都应使用中文。

## 项目概述

SharedClipboard（共享剪贴板）是一个 Windows 桌面应用，用于剪贴板历史管理和跨设备同步。基于 PySide6（Qt for Python）构建，以系统托盘应用形式运行，带有边缘吸附滑出窗口。


### 项目、官网和API、插件

1. **主项目**：`E:/python/共享剪贴板/CLIPBOARD-`（remote: github.com:wenrongruan/CLIPBOARD-.git）
2. **website 子项目**：`E:/python/共享剪贴板/CLIPBOARD-/website`（remote: github.com:wenrongruan/jlike.git，独立 Git 仓库）
3. **ai图片插件**: 'E:\python\chat_image_gen' (remote: git@github.com:wenrongruan/aladdinpic-app.git，独立 Git 仓库)


## 运行应用

```bash
python main.py
```

## 依赖安装

```bash
pip install -r requirements.txt
```

核心依赖：PySide6 (>=6.6.0)、Pillow (>=10.0.0)、pynput (>=1.7.6)、pymysql (>=1.1.0)、httpx (>=0.27.0)、keyring (>=25.0.0)

## 架构

### 核心层 (`core/`)
- **models.py**：`ClipboardItem` 数据类，包含 `ContentType` 枚举（TEXT/IMAGE）和可选的 `cloud_id` 字段
- **database.py**：`DatabaseManager`，使用 SQLite/WAL 模式，FTS5 全文搜索，数据库锁重试逻辑，schema 版本管理（v2）
- **base_database.py** / **db_factory.py**：数据库抽象基类和工厂模式，支持 SQLite 和 MySQL 后端
- **mysql_database.py**：`MySQLDatabaseManager`，MySQL/RDS 数据库支持
- **repository.py**：`ClipboardRepository`，提供分页和搜索的 CRUD 操作，自动适配 SQLite/MySQL 占位符
- **clipboard_monitor.py**：`ClipboardMonitor`，按可配置间隔轮询系统剪贴板（默认 500ms），通过内容哈希去重，异步图片处理
- **sync_service.py**：`SyncService`，自适应轮询（1~30 秒），有新数据时重置为 1 秒，无新数据逐步增加间隔
- **cloud_sync_service.py** / **cloud_api.py**：云端同步服务，通过 HTTP API 与云端交互
- **plugin_manager.py** / **plugin_api.py**：插件系统，支持加载和管理第三方插件
- **migration.py**：数据库迁移工具

### UI 层 (`ui/`)
- **edge_window.py**：`EdgeHiddenWindow` 基类 — 无边框窗口，吸附到屏幕边缘（左/右/上/下），带滑入/滑出动画，支持悬浮模式和窗口拖动
- **main_window.py**：`MainWindow` 继承 `EdgeHiddenWindow` — 搜索、分页、设置对话框、云端集成和插件管理
- **clipboard_item.py**：`ClipboardItemWidget`，渲染单个剪贴板条目
- **cloud_auth_dialog.py** / **cloud_login_widget.py**：云端认证和登录 UI
- **subscription_widget.py**：订阅管理组件
- **styles.py**：暗色主题 QSS 样式表

### 配置 (`config.py`)
- `Config` 类提供类方法管理设置（Windows: `%APPDATA%/SharedClipboard/settings.json`，macOS: `~/Library/Application Support/SharedClipboard/settings.json`）
- 设备 ID 由随机 UUID 生成（16 字符），避免 MAC 地址隐私泄露
- 数据库默认为配置目录下的 `clipboard.db`
- 同步模式可选：local（本地共享数据库）/ mysql（远程 MySQL）/ cloud（云端 API）

### 工具 (`utils/`)
- **hash_utils.py**：SHA-256 内容哈希（截断为 32 字符）
- **image_utils.py**：基于 Pillow 的缩略图生成、图片压缩（含云端上传压缩）
- **secure_store.py**：安全密钥存储（基于 keyring 库）

## 关键设计模式

1. **基于信号的通信**：Qt 信号将剪贴板变化和同步事件连接到 UI 更新
2. **轮询优于事件**：剪贴板监控使用 QTimer 轮询（在 Windows 上比 Qt 的 dataChanged 信号更可靠）
3. **数据库去重**：内容哈希防止重复条目
4. **延迟加载图片**：缩略图单独存储；仅在复制回剪贴板时加载完整图片

## 数据库结构

SQLite 数据库（schema v2），支持 FTS5 搜索。主表 `clipboard_items`：
- id、content_type、text_content、image_data、image_thumbnail
- content_hash（唯一）、preview、device_id、device_name
- created_at（毫秒时间戳）、is_starred、cloud_id（云同步标识）

辅助表：`app_meta`（存储 schema_version 等元数据）、`clipboard_fts`（FTS5 虚拟表）

## 多设备同步

支持三种同步模式（通过 `Config.get_sync_mode()` 切换）：
1. **local**：设备共享同一 SQLite 数据库文件（如通过网络驱动器）
2. **mysql**：多设备连接同一 MySQL/RDS 数据库
3. **cloud**：通过云端 API 同步（`cloud_sync_service.py`）

每个设备有唯一的 `device_id`。本地同步服务查询条件为 `id > last_sync_id AND device_id != this_device`。

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
- 数据文件：`('icons', 'icons')` + `('plugins', 'plugins')` — 打包 icons 和 plugins 目录
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
