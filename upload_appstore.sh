#!/bin/bash
# SharedClipboard — Mac App Store 上传脚本

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_PATH="${1:-$SCRIPT_DIR/SharedClipboard_appstore.pkg}"
APP_BUNDLE="${APP_BUNDLE:-$SCRIPT_DIR/dist/共享剪贴板.app}"
BUNDLE_ID="${BUNDLE_ID:-com.wenrongruan.sharedclipboard}"
APPLE_ID="${APPLE_ID:-6756561246}"
APPLE_USERNAME="${APPLE_USERNAME:-rwr@qq.com}"
APPLE_APP_PASSWORD="${APPLE_APP_PASSWORD:-}"
ASC_PROVIDER_ID="${ASC_PROVIDER_ID:-}"
ASC_API_KEY="${ASC_API_KEY:-${ASC_KEY_ID:-}}"
ASC_API_ISSUER="${ASC_API_ISSUER:-${ASC_ISSUER_ID:-}}"
ALTOOL_BIN="${ALTOOL_BIN:-/Applications/Xcode.app/Contents/SharedFrameworks/ContentDelivery.framework/Versions/A/Resources/altool}"
TRANSPORTER_BIN="${TRANSPORTER_BIN:-/Applications/Transporter.app/Contents/itms/bin/iTMSTransporter}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
warn() { echo -e "${YELLOW}警告: $*${NC}"; }
fail() { echo -e "${RED}错误: $*${NC}"; exit 1; }
pass() { echo -e "${GREEN}$*${NC}"; }

[ "$(uname)" = "Darwin" ] || fail "此脚本只能在 macOS 上运行"
[ -f "$PKG_PATH" ] || fail "找不到安装包: $PKG_PATH"

if [ -f "$APP_BUNDLE/Contents/Info.plist" ]; then
    INFO_PLIST="$APP_BUNDLE/Contents/Info.plist"
    BUNDLE_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$INFO_PLIST" 2>/dev/null || true)
    SHORT_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$INFO_PLIST" 2>/dev/null || true)
else
    BUNDLE_VERSION="${BUNDLE_VERSION:-}"
    SHORT_VERSION="${SHORT_VERSION:-}"
fi

echo "安装包: $PKG_PATH"
echo "App Apple ID: $APPLE_ID"
echo "Bundle ID: $BUNDLE_ID"
[ -n "${SHORT_VERSION:-}" ] && echo "版本号: $SHORT_VERSION"
[ -n "${BUNDLE_VERSION:-}" ] && echo "构建号: $BUNDLE_VERSION"

if [ -x "$ALTOOL_BIN" ]; then
    if [ -n "$ASC_API_KEY" ] && [ -n "$ASC_API_ISSUER" ]; then
        CMD=(
            "$ALTOOL_BIN"
            --upload-package "$PKG_PATH"
            --apple-id "$APPLE_ID"
            --bundle-id "$BUNDLE_ID"
            --bundle-version "${BUNDLE_VERSION:-}"
            --bundle-short-version-string "${SHORT_VERSION:-}"
            --api-key "$ASC_API_KEY"
            --api-issuer "$ASC_API_ISSUER"
            --output-format json
            --wait
        )
        pass "使用 App Store Connect API Key 上传..."
        "${CMD[@]}"
        exit 0
    fi

    if [ -n "$APPLE_APP_PASSWORD" ]; then
        CMD=(
            "$ALTOOL_BIN"
            --upload-package "$PKG_PATH"
            --apple-id "$APPLE_ID"
            --bundle-id "$BUNDLE_ID"
            --bundle-version "${BUNDLE_VERSION:-}"
            --bundle-short-version-string "${SHORT_VERSION:-}"
            --username "$APPLE_USERNAME"
            --password "@env:APPLE_APP_PASSWORD"
            --output-format json
            --wait
        )
        if [ -n "$ASC_PROVIDER_ID" ]; then
            CMD+=(--provider-public-id "$ASC_PROVIDER_ID")
        fi
        pass "使用 Apple 账号密码上传..."
        APPLE_APP_PASSWORD="$APPLE_APP_PASSWORD" "${CMD[@]}"
        exit 0
    fi
fi

warn "未满足 altool 命令行上传条件。"
echo "可用的下一步："
echo "1. 设置 APPLE_APP_PASSWORD 后执行："
echo "   APPLE_APP_PASSWORD='xxxx-xxxx-xxxx-xxxx' ./upload_appstore.sh"
echo "2. 或设置 ASC_API_KEY / ASC_API_ISSUER 后执行："
echo "   ASC_API_KEY='xxx' ASC_API_ISSUER='xxx' ./upload_appstore.sh"
if [ -x "$TRANSPORTER_BIN" ]; then
    echo "3. 或打开 Transporter 图形界面上传："
    echo "   open -a Transporter \"$PKG_PATH\""
else
    warn "Transporter.app 未安装或命令行入口缺失。"
fi
exit 1
