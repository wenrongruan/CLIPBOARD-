#!/bin/bash
# Mac 一键打包脚本
# 使用方法：在 Mac 终端中运行 ./build_mac.sh

# Why -u / pipefail：脚本里有大量 find|while / awk|sort 管道，未设 pipefail 时
# 上游失败会被吞掉继续往下跑，产出半成品 app 还报告"打包完成"。
set -euo pipefail

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
    # Why 不再 curl | bash 直接执行远程脚本：中间人或仓库被篡改即以用户身份
    # 任意代码执行。改为下载到临时文件、提示用户审阅后自行执行。
    echo "未安装 Homebrew。出于安全考虑本脚本不再直接远程拉取执行安装脚本，"
    echo "请先手动安装 Homebrew 后重新运行本脚本："
    echo ""
    echo "  # 下载安装脚本并审阅"
    echo "  curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o /tmp/brew_install.sh"
    echo "  less /tmp/brew_install.sh"
    echo "  bash /tmp/brew_install.sh"
    echo ""
    exit 1
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
    --osx-bundle-identifier "com.wenrongruan.sharedclipboard" \
    --add-data "core:core" \
    --add-data "ui:ui" \
    --add-data "utils:utils" \
    --add-data "sql:sql" \
    --add-data "i18n_strings:i18n_strings" \
    --add-data "Info.plist:." \
    --hidden-import "PySide6.QtCore" \
    --hidden-import "PySide6.QtGui" \
    --hidden-import "PySide6.QtWidgets" \
    --hidden-import "PIL" \
    --hidden-import "AppKit" \
    --hidden-import "Foundation" \
    --hidden-import "Cocoa" \
    --hidden-import "Quartz" \
    main.py

# 替换 Info.plist 以隐藏 Dock 图标
echo "配置应用为菜单栏模式（隐藏 Dock 图标）..."
cp Info.plist "dist/共享剪贴板.app/Contents/Info.plist"

# 清除 quarantine 扩展属性（必须在所有 codesign 命令之前执行；
# 若在签名之后执行，xattr -cr 会擦除签名写入的扩展属性，导致公证失败）
xattr -cr "dist/共享剪贴板.app"
echo "已清除 quarantine 扩展属性"

# 签名：默认 ad-hoc（仅本机可用）；如需正式 DevID 分发，设置 DEVID_SIGN_CERT 环境变量
# 例：DEVID_SIGN_CERT="Developer ID Application: Your Name (TEAMID)" ./build_mac.sh
echo "签名应用..."
# Why ${VAR:-}：set -u 下直接引用未设置变量会立刻退出，ad-hoc 分支永远走不到
if [[ -n "${DEVID_SIGN_CERT:-}" ]]; then
    APP_BUNDLE="dist/共享剪贴板.app"

    # Inside-out 签名顺序（Apple 公证要求所有层级都带 --timestamp + --options runtime）：

    # (1) 所有 .so / .dylib（叶子层，最先签）
    find "$APP_BUNDLE" -type f \( -name "*.so" -o -name "*.dylib" \) | while read lib; do
        codesign --force --sign "$DEVID_SIGN_CERT" \
            --options runtime --timestamp "$lib" 2>/dev/null || true
    done

    # (2) framework 内部的主可执行（QtCore.framework/Versions/A/QtCore,
    #     Python.framework/Versions/3.11/Python 等）
    find "$APP_BUNDLE" -type d -name "*.framework" | while read fw; do
        fw_name=$(basename "$fw" .framework)
        for ver in "$fw"/Versions/*/; do
            [ -d "$ver" ] || continue
            [ -L "${ver%/}" ] && continue  # 跳过 Current 符号链接
            exe="${ver}${fw_name}"
            if [ -f "$exe" ]; then
                codesign --force --sign "$DEVID_SIGN_CERT" \
                    --options runtime --timestamp "$exe" 2>/dev/null || true
            fi
        done
    done

    # (3) framework 内嵌的 .app（如 Python.app），深度从深到浅
    find "$APP_BUNDLE/Contents/Frameworks" -type d -name "*.app" 2>/dev/null \
        | sort -r | while read inner_app; do
        codesign --force --sign "$DEVID_SIGN_CERT" \
            --options runtime --timestamp "$inner_app"
    done

    # (4) framework bundle 本身（按路径深度从深到浅）
    find "$APP_BUNDLE/Contents/Frameworks" -type d -name "*.framework" 2>/dev/null \
        | awk '{print length, $0}' | sort -rn | cut -d' ' -f2- | while read fw; do
        codesign --force --sign "$DEVID_SIGN_CERT" \
            --options runtime --timestamp "$fw"
    done

    # (5) 主 App Bundle（带 Entitlements.devid.plist，覆盖主可执行签名）
    codesign --force \
        --sign "$DEVID_SIGN_CERT" \
        --entitlements "Entitlements.devid.plist" \
        --options runtime \
        --timestamp \
        "$APP_BUNDLE"

    # 验证签名
    codesign --verify --deep --strict "$APP_BUNDLE" \
        && echo "签名验证通过" \
        || { echo "签名验证失败"; exit 1; }

    echo "已使用 DevID 证书签名（Hardened Runtime + Entitlements.devid.plist）"
    echo "后续步骤（手动执行）："
    echo "  # 1. 压缩为 zip（notarytool 推荐 zip 格式）"
    echo "  ditto -c -k --sequesterRsrc --keepParent dist/共享剪贴板.app dist/共享剪贴板.zip"
    echo "  # 2. 提交公证（--keychain-profile 对应 xcrun notarytool store-credentials 时设置的 profile 名）"
    echo "  xcrun notarytool submit dist/共享剪贴板.zip --keychain-profile \"AC_PASSWORD\" --wait"
    echo "  # 3. 装订公证票据"
    echo "  xcrun stapler staple dist/共享剪贴板.app"
    echo "  # 4. 验证 Gatekeeper 可通过"
    echo "  spctl -a -vv dist/共享剪贴板.app"
else
    codesign --force --deep --sign - "dist/共享剪贴板.app"
fi

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
