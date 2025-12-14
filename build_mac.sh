#!/bin/bash
# Mac 一键打包脚本
# 使用方法：在 Mac 终端中运行 ./build_mac.sh

set -e

echo "=========================================="
echo "  共享剪贴板 - macOS 打包脚本"
echo "=========================================="

# 检查是否在 macOS 上运行
if [[ "$(uname)" != "Darwin" ]]; then
    echo "错误：此脚本只能在 macOS 上运行"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "[1/5] 检查 Homebrew..."
if ! command -v brew &> /dev/null; then
    echo "正在安装 Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # 添加 Homebrew 到 PATH (Apple Silicon)
    if [[ -f "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
else
    echo "Homebrew 已安装"
fi

echo ""
echo "[2/5] 检查 Python..."
if ! command -v python3 &> /dev/null; then
    echo "正在安装 Python..."
    brew install python@3.11
else
    echo "Python 已安装: $(python3 --version)"
fi

echo ""
echo "[3/5] 创建虚拟环境..."
if [[ ! -d "venv" ]]; then
    python3 -m venv venv
fi
source venv/bin/activate

echo ""
echo "[4/5] 安装依赖..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo ""
echo "[5/5] 打包应用..."
pyinstaller --onefile --windowed \
    --name "共享剪贴板" \
    --osx-bundle-identifier "com.sharedclipboard.app" \
    --osx-entitlements-file "" \
    --add-data "core:core" \
    --add-data "ui:ui" \
    --add-data "utils:utils" \
    --add-data "Info.plist:." \
    --hidden-import "PySide6.QtCore" \
    --hidden-import "PySide6.QtGui" \
    --hidden-import "PySide6.QtWidgets" \
    --hidden-import "PIL" \
    main.py

# 替换 Info.plist 以隐藏 Dock 图标
echo "配置应用为菜单栏模式（隐藏 Dock 图标）..."
cp Info.plist "dist/共享剪贴板.app/Contents/Info.plist"

echo ""
echo "=========================================="
echo "  打包完成！"
echo "=========================================="
echo ""
echo "应用位置: $SCRIPT_DIR/dist/共享剪贴板.app"
echo ""
echo "安装方法："
echo "  将 '共享剪贴板.app' 拖到 '应用程序' 文件夹"
echo ""

# 打开 dist 文件夹
open dist/

echo "按回车键退出..."
read
