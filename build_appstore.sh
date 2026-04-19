#!/bin/bash
# =============================================================================
# SharedClipboard — Mac App Store 构建脚本
# =============================================================================
#
# 使用前请先设置以下变量：
#
#   TEAM_ID         Apple Developer Team ID（在 developer.apple.com 查看）
#   APPLE_ID        Apple ID 邮箱（用于上传）
#   APP_PASSWORD    App 专用密码（在 appleid.apple.com 生成）
#
# 用法:
#   chmod +x build_appstore.sh
#   ./build_appstore.sh
#
# 前提条件：
#   - macOS 12+
#   - Xcode Command Line Tools: xcode-select --install
#   - Python 3.11+（推荐通过 Homebrew 安装）
#   - 已安装 Mac App Store 发布证书：
#       "3rd Party Mac Developer Application: <名字> (<TEAM_ID>)"
#       "3rd Party Mac Developer Installer: <名字> (<TEAM_ID>)"
# =============================================================================

set -e  # 任何命令失败立即退出

# ─── 请修改以下变量 ────────────────────────────────────────────────────────────
TEAM_ID="N9B2B6LN88"
APPLE_ID="rwr@qq.com"            # Apple ID
APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"  # App 专用密码
# ──────────────────────────────────────────────────────────────────────────────

APP_NAME="共享剪贴板"
BUNDLE_ID="com.wenrongruan.sharedclipboard"
APP_SIGN_CERT="Apple Distribution: wenrong ruan (N9B2B6LN88)"
PKG_SIGN_CERT="3rd Party Mac Developer Installer: wenrong ruan (N9B2B6LN88)"

APP_BUNDLE="dist/${APP_NAME}.app"
PKG_OUTPUT="SharedClipboard_appstore.pkg"
ENTITLEMENTS="Entitlements.plist"   # MAS 沙盒版 entitlements（DevID 版请用 Entitlements.devid.plist）
VENV_DIR=".venv_appstore"

# 目标架构：默认 universal2；若本地 venv/wheels 非 universal2 将失败，
# 可用 TARGET_ARCH=x86_64 覆盖。建议用 python.org 官方 universal2 installer 或
# pip install --platform macosx_11_0_universal2 --only-binary=:all: 获取 fat wheels。
TARGET_ARCH="${TARGET_ARCH:-universal2}"

# 版本号从 config.py 动态读取（避免与源码脱节）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VER=$(cd "$SCRIPT_DIR" && python3 -c "from config import APP_VERSION; print(APP_VERSION)" 2>/dev/null || echo "0.0.0")
# Build 号优先读环境变量 BUILD_NUMBER，否则用时间戳
BUILD_NUM="${BUILD_NUMBER:-$(date +%Y%m%d%H%M)}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { echo -e "\n${GREEN}[$1/7]${NC} $2"; }
warn() { echo -e "${YELLOW}警告: $*${NC}"; }
fail() { echo -e "${RED}错误: $*${NC}"; exit 1; }

# ─── [1/7] 检查环境 ────────────────────────────────────────────────────────────
step 1 "检查环境"

[ "$(uname)" = "Darwin" ] || fail "此脚本只能在 macOS 上运行"
xcode-select -p &>/dev/null || fail "未找到 Xcode Command Line Tools，请运行: xcode-select --install"

PYTHON=$(command -v python3.11 || fail "未找到 python3.11，请从 python.org 安装 universal2 版本")
PY_VER=$($PYTHON --version 2>&1)
echo "Python: $PY_VER"

[ "$TEAM_ID" = "YOUR_TEAM_ID" ] && warn "TEAM_ID 未设置，签名步骤将跳过"
[ -f "$ENTITLEMENTS" ] || fail "找不到 Entitlements.plist"
[ -f "main.py" ] || fail "请在项目根目录运行此脚本"

echo "应用名称: ${APP_NAME}"
echo "Bundle ID: ${BUNDLE_ID}"

# ─── [2/7] 创建虚拟环境并安装依赖 ───────────────────────────────────────────────
step 2 "创建虚拟环境并安装依赖"

rm -rf "$VENV_DIR"  # 每次重建 venv（TARGET_ARCH=$TARGET_ARCH）
$PYTHON -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet PySide6 Pillow pymysql  # 不安装 pynput（App Sandbox 不支持输入监控）
pip install --quiet pyinstaller

# Pillow 不发布 universal2 wheel，本地默认装到当前架构的单拱 wheel，
# 会导致 PyInstaller target-arch=universal2 时报 IncompatibleBinaryArchError。
# 用 delocate-merge 把 arm64 + x86_64 wheel 融合为 universal2 后重装。
if [ "$TARGET_ARCH" = "universal2" ]; then
    PILLOW_VER=$(pip show Pillow | awk '/^Version:/ {print $2}')
    PIL_WEBP=$(python -c "import PIL, os; print(os.path.join(os.path.dirname(PIL.__file__), '_webp.cpython-311-darwin.so'))")
    if [ -f "$PIL_WEBP" ] && ! lipo -info "$PIL_WEBP" 2>/dev/null | grep -q "arm64 x86_64\|x86_64 arm64"; then
        echo "Pillow ${PILLOW_VER} 不是 universal2，融合两个架构 wheel..."
        pip install --quiet delocate
        PILLOW_FUSE_DIR="$SCRIPT_DIR/.pillow_fuse"
        rm -rf "$PILLOW_FUSE_DIR" && mkdir -p "$PILLOW_FUSE_DIR"
        pip download --no-deps --only-binary=:all: \
            --platform macosx_11_0_arm64 --python-version 3.11 --abi cp311 --implementation cp \
            -d "$PILLOW_FUSE_DIR" "Pillow==$PILLOW_VER" >/dev/null
        pip download --no-deps --only-binary=:all: \
            --platform macosx_10_10_x86_64 --python-version 3.11 --abi cp311 --implementation cp \
            -d "$PILLOW_FUSE_DIR" "Pillow==$PILLOW_VER" >/dev/null
        ARM_WHL=$(ls "$PILLOW_FUSE_DIR"/*arm64.whl)
        X86_WHL=$(ls "$PILLOW_FUSE_DIR"/*x86_64.whl)
        delocate-merge "$ARM_WHL" "$X86_WHL" >/dev/null
        UNIV_WHL=$(ls "$PILLOW_FUSE_DIR"/*universal2.whl)
        pip install --quiet --force-reinstall --no-deps "$UNIV_WHL"
        echo "Pillow 已替换为 universal2 版本"
    fi
fi

echo "依赖安装完成"

# ─── [3/7] 生成 AppIcon.icns ──────────────────────────────────────────────────
step 3 "生成 AppIcon.icns"

if [ -f "icons/AppIcon.icns" ]; then
    echo "icons/AppIcon.icns 已存在，跳过生成"
else
    python create_icns.py || warn "图标生成失败，将使用默认图标继续"
fi

# ─── [4/7] PyInstaller 打包 ───────────────────────────────────────────────────
step 4 "PyInstaller 打包应用"

rm -rf dist build

ICON_ARG=""
[ -f "icons/AppIcon.icns" ] && ICON_ARG="--icon=icons/AppIcon.icns"

pyinstaller \
    --name "${APP_NAME}" \
    --windowed \
    --noconfirm \
    --target-arch "$TARGET_ARCH" \
    $ICON_ARG \
    --add-data "icons:icons" \
    --add-data "core:core" \
    --add-data "ui:ui" \
    --add-data "utils:utils" \
    --add-data "plugins:plugins" \
    --add-data "i18n.py:." \
    --hidden-import "PySide6.QtCore" \
    --hidden-import "PySide6.QtGui" \
    --hidden-import "PySide6.QtWidgets" \
    --hidden-import "PIL" \
    --hidden-import "pymysql" \
    --osx-bundle-identifier "$BUNDLE_ID" \
    main.py

[ -d "$APP_BUNDLE" ] || fail "打包失败，未找到 ${APP_BUNDLE}"
echo "打包成功: ${APP_BUNDLE}"

# 修正 Info.plist（PyInstaller 生成的版本号不正确）
INFO_PLIST="${APP_BUNDLE}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_NUM" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $BUILD_NUM" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :LSApplicationCategoryType public.app-category.utilities" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :LSApplicationCategoryType string public.app-category.utilities" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion 12.0" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 12.0" "$INFO_PLIST"
echo "Info.plist 已更新: 版本 ${VER} (Build ${BUILD_NUM})"

# 嵌入 Provisioning Profile（用数组展开 glob，避免引号内 glob 不展开）
profiles=(*.provisionprofile)
if [ -e "${profiles[0]}" ]; then
    PROFILE="${profiles[0]}"
    cp "$PROFILE" "${APP_BUNDLE}/Contents/embedded.provisionprofile"
    echo "已嵌入 Provisioning Profile: $PROFILE"
elif [ -f "${APP_BUNDLE}/Contents/embedded.provisionprofile" ]; then
    echo "embedded.provisionprofile 已存在"
else
    warn "未找到 .provisionprofile 文件！App Store 上传将失败，请手动复制到 ${APP_BUNDLE}/Contents/embedded.provisionprofile"
fi

# 清除 quarantine 扩展属性（浏览器下载文件会自动带此属性，App Store 不允许）
xattr -cr "$APP_BUNDLE"
echo "已清除 quarantine 扩展属性"

# ─── [5/7] 深度代码签名 ───────────────────────────────────────────────────────
step 5 "代码签名（App Sandbox + Hardened Runtime）"

if [ "$TEAM_ID" = "YOUR_TEAM_ID" ]; then
    warn "TEAM_ID 未设置，使用 ad-hoc 签名（仅用于本地测试，无法上传 App Store）"
    codesign --force --deep --sign - "$APP_BUNDLE"
else
    # 对所有 .so 和 .dylib 单独签名（子库不能带 entitlements，仅主可执行带）
    find "$APP_BUNDLE" \( -name "*.so" -o -name "*.dylib" \) | while read lib; do
        codesign --force --sign "$APP_SIGN_CERT" \
            --options runtime "$lib" 2>/dev/null || true
    done

    # 签名主 App Bundle（子库已单独签过，这里不用 --deep）
    codesign --force \
        --sign "$APP_SIGN_CERT" \
        --entitlements "$ENTITLEMENTS" \
        --options runtime \
        "$APP_BUNDLE"

    # 验证签名
    codesign --verify --deep --strict "$APP_BUNDLE" \
        && echo "签名验证通过" \
        || fail "签名验证失败"
fi

# ─── [6/7] 创建 .pkg 安装包 ───────────────────────────────────────────────────
step 6 "创建 .pkg 安装包"

if [ "$TEAM_ID" = "YOUR_TEAM_ID" ]; then
    warn "跳过 .pkg 创建（需要有效的 Installer 证书）"
else
    productbuild \
        --component "$APP_BUNDLE" /Applications \
        --sign "$PKG_SIGN_CERT" \
        "$PKG_OUTPUT"

    pkgutil --check-signature "$PKG_OUTPUT" \
        && echo "pkg 签名验证通过: ${PKG_OUTPUT}" \
        || fail "pkg 签名验证失败"
fi

# ─── [7/7] 验证与提交提示 ─────────────────────────────────────────────────────
step 7 "完成"

echo ""
echo "构建产物:"
[ -d "$APP_BUNDLE" ] && echo "  App Bundle : ${APP_BUNDLE}"
[ -f "$PKG_OUTPUT" ] && echo "  安装包     : ${PKG_OUTPUT}"

echo ""
echo "下一步 — 提交到 App Store Connect:"
echo ""
echo "  方式一：Transporter（推荐，图形界面）"
echo "    从 Mac App Store 安装 Transporter，拖入 ${PKG_OUTPUT} 上传"
echo ""
echo "  方式二：命令行上传（altool --upload-app 已停用）"
echo "    # Mac App Store (.pkg) → 使用 altool --upload-package 或 Transporter"
echo "    xcrun altool --upload-package ${PKG_OUTPUT} \\"
echo "        --type macos --bundle-id ${BUNDLE_ID} \\"
echo "        --bundle-version ${BUILD_NUM} --bundle-short-version-string ${VER} \\"
echo "        --apple-id YOUR_APP_APPLE_ID \\"
echo "        --apiKey YOUR_API_KEY --apiIssuer YOUR_ISSUER_ID"
echo ""
echo "  DevID 分发版请改用 notarytool 公证（本脚本不产出 DevID 版）："
echo "    xcrun notarytool submit YourApp.zip --keychain-profile \"AC_PASSWORD\" --wait"
echo "    xcrun stapler staple YourApp.app"
echo ""
echo "  上传前请确认已在 App Store Connect 中完成："
echo "    1. 注册 Bundle ID: ${BUNDLE_ID}"
echo "    2. 创建 App 条目（分类: 实用工具）"
echo "    3. 准备截图（1280×800 或 2560×1600，至少 1 张）"
echo "    4. 填写应用描述、隐私政策 URL"

deactivate
