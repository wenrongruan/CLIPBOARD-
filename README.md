# 共享剪贴板 (SharedClipboard)

跨设备剪贴板同步工具，支持 Windows 和 macOS。

## 功能特性

- **剪贴板历史** - 自动保存复制的文本和图片
- **跨设备同步** - 多台设备共享同一数据库，自动同步剪贴板内容
- **模糊搜索** - 快速搜索历史记录
- **收藏功能** - 重要内容可收藏，不会被自动清理
- **边缘停靠** - 窗口隐藏在屏幕边缘，鼠标靠近自动滑出
- **系统托盘** - 后台运行，不占用任务栏

## 下载安装

从 [Releases](https://github.com/wenrongruan/CLIPBOARD-/releases) 下载：

| 平台 | 文件 |
|------|------|
| Windows | `SharedClipboard.exe` |
| macOS | `共享剪贴板-macOS.dmg` |

### macOS 安装说明

1. 下载 `.dmg` 文件
2. 双击打开，将应用拖到 Applications 文件夹
3. 首次打开：右键点击应用 → 选择"打开"（绕过安全提示）

## 使用方法

1. 运行应用后，图标出现在系统托盘/菜单栏
2. 鼠标移到屏幕右边缘，窗口自动滑出
3. 点击任意记录即可复制到剪贴板
4. 点击 ⚙ 可设置停靠位置和数据库路径

## 多设备同步

将数据库文件放在共享位置（如网盘同步文件夹）：

1. 打开设置 ⚙
2. 修改数据库路径到共享文件夹（如 `D:\Dropbox\clipboard.db`）
3. 所有设备使用相同的数据库路径

## 从源码运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 技术栈

- Python 3.11+
- PySide6 (Qt for Python)
- SQLite (WAL 模式)
- Pillow

## 许可证

MIT License
