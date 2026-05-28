#!/bin/bash
# macOS 上架前最终冒烟脚本
#
# 自动覆盖 RELEASE_CHECKLIST.md 第 4 / 5 / 7 节里能自动的部分（包内静态校验、
# 干净 sandbox container 启动、降级路径），UI 类手动项以可勾选清单形式打印。
#
# 用法:
#   ./release_smoke_macos.sh                       # 默认验证 dist/共享剪贴板.app
#   ./release_smoke_macos.sh path/to/MyApp.app     # 验证指定 .app
#
# 退出码:
#   0  全部自动校验通过
#   1  有自动校验失败（不可上架）
#
# 注: 本脚本不替代真机 UI 冒烟，只是把能机器化的部分挡在 Transporter 前。

set -u  # 未定义变量即报错；不用 set -e，我们要把所有检查都跑完再汇总结果

APP_BUNDLE="${1:-dist/共享剪贴板.app}"
BUNDLE_ID="com.wenrongruan.sharedclipboard"
CONTAINER_PATH="$HOME/Library/Containers/${BUNDLE_ID}"
APP_SUPPORT_PATH="$HOME/Library/Application Support/SharedClipboard"
EXPECTED_VERSION="3.3.2"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS_COUNT=0; FAIL_COUNT=0; WARN_COUNT=0

pass() { echo -e "  ${GREEN}✓${NC} $*"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo -e "  ${RED}✗${NC} $*"; FAIL_COUNT=$((FAIL_COUNT+1)); }
warn() { echo -e "  ${YELLOW}!${NC} $*"; WARN_COUNT=$((WARN_COUNT+1)); }
info() { echo -e "  ${CYAN}·${NC} $*"; }
section() { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

[ "$(uname)" = "Darwin" ] || { echo "此脚本只能在 macOS 上运行"; exit 2; }

echo "目标 App: $APP_BUNDLE"
echo "Bundle ID: $BUNDLE_ID"
echo "期望版本: $EXPECTED_VERSION"

# ════════════════════════════════════════════════════════════════════════════
# A. 包内静态校验（不需要启动）
# ════════════════════════════════════════════════════════════════════════════
section "A. 包结构与签名"

if [ ! -d "$APP_BUNDLE" ]; then
    fail "找不到 .app: $APP_BUNDLE — 请先运行 ./build_appstore.sh"
    echo -e "\n${RED}前置失败，退出。${NC}"
    exit 1
fi
pass ".app 存在"

INFO_PLIST="$APP_BUNDLE/Contents/Info.plist"
[ -f "$INFO_PLIST" ] && pass "Info.plist 存在" || fail "Info.plist 缺失"

ver_short=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$INFO_PLIST" 2>/dev/null)
ver_build=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$INFO_PLIST" 2>/dev/null)
flavor=$(/usr/libexec/PlistBuddy -c "Print :SCBuildFlavor" "$INFO_PLIST" 2>/dev/null)
pasteboard_desc=$(/usr/libexec/PlistBuddy -c "Print :NSPasteboardUsageDescription" "$INFO_PLIST" 2>/dev/null)

[ "$ver_short" = "$EXPECTED_VERSION" ] \
    && pass "CFBundleShortVersionString = $ver_short" \
    || fail "CFBundleShortVersionString = $ver_short (期望 $EXPECTED_VERSION)"
[ -n "$ver_build" ] && pass "CFBundleVersion = $ver_build" || fail "CFBundleVersion 缺失"
[ "$flavor" = "appstore" ] \
    && pass "SCBuildFlavor = appstore" \
    || fail "SCBuildFlavor = '$flavor' (期望 appstore，否则运行时不会走 MAS 分支)"
[ -n "$pasteboard_desc" ] \
    && pass "NSPasteboardUsageDescription 已声明" \
    || fail "NSPasteboardUsageDescription 缺失"

PROFILE_PATH="$APP_BUNDLE/Contents/embedded.provisionprofile"
[ -f "$PROFILE_PATH" ] \
    && pass "embedded.provisionprofile 已嵌入" \
    || fail "embedded.provisionprofile 缺失 — Transporter 会拒收"

section "B. 代码签名 & 公证准备"

if codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE" 2>&1 | grep -q "valid on disk"; then
    pass "codesign --verify --deep --strict 通过"
else
    codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE" 2>&1 | sed 's/^/      /'
    fail "codesign 校验失败"
fi

if spctl -a -vv -t install "$APP_BUNDLE" 2>&1 | grep -qE "accepted"; then
    pass "spctl -a -t install 接受（开发者签名链有效）"
else
    spctl_out=$(spctl -a -vv -t install "$APP_BUNDLE" 2>&1 || true)
    echo "$spctl_out" | sed 's/^/      /'
    # spctl 对未公证 MAS 包会显示 rejected，这是预期；只要不是签名错就 warn
    # MAS 包用 Apple Distribution 签名，spctl 一律 rejected，且不会带 "not notarized"
    # 文案。只要 origin 行是 Apple Distribution / 3rd Party Mac Developer，就当 warn 处理。
    if echo "$spctl_out" | grep -qE "rejected.*not notarized|no usable signature"; then
        warn "spctl 拒绝但仅因未公证（MAS 包正常，Transporter 会处理）"
    elif echo "$spctl_out" | grep -qE "origin=(Apple Distribution|3rd Party Mac Developer)"; then
        warn "spctl 拒绝是因 Apple Distribution 签名（MAS 包预期行为，Transporter 会处理）"
    else
        fail "spctl 报签名问题"
    fi
fi

section "C. Entitlements 合规（MAS 禁用键）"

ENTITLEMENTS_DUMP=$(codesign -d --entitlements :- "$APP_BUNDLE" 2>/dev/null)
if [ -z "$ENTITLEMENTS_DUMP" ]; then
    fail "无法导出 entitlements"
else
    # MAS 禁用键
    forbidden_hit=0
    for key in \
        "com.apple.security.cs.disable-library-validation" \
        "com.apple.security.cs.allow-unsigned-executable-memory" \
        "com.apple.security.cs.allow-dyld-environment-variables" \
        "com.apple.security.cs.disable-executable-page-protection"
    do
        if echo "$ENTITLEMENTS_DUMP" | grep -q "$key"; then
            fail "包含 MAS 禁用键: $key — Transporter 会拒收"
            forbidden_hit=1
        fi
    done
    [ $forbidden_hit -eq 0 ] && pass "未包含任何 MAS 禁用键"

    # 必备键
    for key in \
        "com.apple.security.app-sandbox" \
        "com.apple.security.network.client"
    do
        if echo "$ENTITLEMENTS_DUMP" | grep -q "$key"; then
            pass "声明了 $key"
        else
            fail "缺少 $key"
        fi
    done
fi

section "D. 插件隔离（App Store 边界）"

PLUGIN_DIR="$APP_BUNDLE/Contents/Resources/plugins"
if [ ! -d "$PLUGIN_DIR" ]; then
    warn "$PLUGIN_DIR 不存在 — 若你期望打包内置插件，请检查 PyInstaller --add-data"
else
    plugin_count=$(find "$PLUGIN_DIR" -maxdepth 1 -type d ! -path "$PLUGIN_DIR" | wc -l | tr -d ' ')
    info "内置插件目录: $plugin_count 个"
    if [ -d "$PLUGIN_DIR/smart_text" ]; then
        pass "smart_text 已打包"
    else
        fail "smart_text 缺失"
    fi
    if [ -d "$PLUGIN_DIR/ai_image_gen" ]; then
        fail "ai_image_gen 不应进入 App Store 包（依赖外部 Python 解释器，沙盒禁止）"
    else
        pass "ai_image_gen 未打包（符合 App Store 边界）"
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# D2. 关键第三方依赖是否打进包（自动）
# ════════════════════════════════════════════════════════════════════════════
# Why: build_appstore.sh 早期手写依赖清单漏掉 httpx/keyring，PyInstaller 只警告不报错，
# 结果上架包一打开设置（CloudTab 导入 httpx）就崩。这里在包内静态搜这些模块，缺一即 fail，
# 把"漏装依赖"从用户点击时的崩溃提前到冒烟阶段拦下。
section "D2. 关键 Python 依赖打包校验"

for dep in httpx keyring; do
    if find "$APP_BUNDLE/Contents" \( -type d -name "$dep" -o -name "${dep}.py" -o -name "${dep}.pyc" \) 2>/dev/null | grep -q .; then
        pass "$dep 已打进包"
    else
        fail "$dep 未打进包 — 检查 build_appstore.sh 依赖安装是否跟随 requirements.txt"
    fi
done

# ════════════════════════════════════════════════════════════════════════════
# E. 干净 container 启动检查（自动）
# ════════════════════════════════════════════════════════════════════════════
section "E. 新装机模拟（清空 sandbox container）"

if [ -d "$CONTAINER_PATH" ]; then
    info "现有 container: $CONTAINER_PATH"
    echo -n "      是否清理以模拟新装机？[y/N] "
    read -r ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        rm -rf "$CONTAINER_PATH"
        pass "已清理 container"
    else
        warn "保留旧 container — 无法验证新装机默认行为"
    fi
else
    pass "无遗留 container（干净环境）"
fi

if [ -d "$APP_SUPPORT_PATH" ]; then
    warn "非沙盒 Application Support 仍存在: $APP_SUPPORT_PATH (沙盒包不会用，仅提示)"
fi

# ════════════════════════════════════════════════════════════════════════════
# F. 手动 UI 冒烟清单（按 RELEASE_CHECKLIST 第 4/5 节）
# ════════════════════════════════════════════════════════════════════════════
section "F. 手动 UI 冒烟清单"

cat <<'EOF'

  请打开 App，按顺序确认下列项（在本终端记录或在另一处打勾）:

  【主路径 - P0】
  [ ] 应用启动 < 3s 出现菜单栏图标 / 主窗口
  [ ] 复制一段文本 → 历史立即出现该条
  [ ] 全局热键 / 菜单栏点击都能呼出窗口
  [ ] 搜索关键词能命中该文本
  [ ] 点击历史项重新粘贴成功
  [ ] 再次复制相同文本 → 不产生重复行，原行置顶
  [ ] 收藏一条 → 退出应用 → 重启 → 收藏状态保留

  【新装机默认行为 - 重点验证本次 B1 修复】
  [ ] 设置 > 文件云同步 入口默认隐藏 / 关闭（files_sync_enabled 默认 False）
  [ ] 主界面不出现任何付费/上传相关 UI
  [ ] 启动后 20s 内不出现任何 OSS / api.jlike.com 网络请求
      （可用 Console.app 过滤 "jlike" 或 "oss" 观察）

  【降级 - P1】
  [ ] 未登录直接使用：本地剪贴板正常工作
  [ ] 切断网络（关 Wi-Fi）后再启动：本地捕获不受影响
  [ ] 拒绝辅助功能权限：仍可通过菜单栏图标呼出窗口
  [ ] 拒绝剪贴板访问（如系统弹框）：应用不崩溃，给出提示

  【macOS 平台行为】
  [ ] 菜单栏图标在浅色/深色模式下均可见
  [ ] Dock 不出现图标（LSUIElement=YES 生效）
  [ ] Cmd+Q 干净退出，无僵尸进程（Activity Monitor 检查）
  [ ] 退出后 ~/Library/Containers/com.wenrongruan.sharedclipboard 下数据保留
  [ ] auth.json 不应出现在 container 内（App Store 构建跳过写入）

  【离线日志巡检】
  [ ] 退出后查看 ~/Library/Containers/.../Data/Library/Logs (或 stderr)
      没有 "wrapped C/C++ object … has been deleted"
      没有 "QObject … from different thread"
      没有 "database disk image is malformed"
EOF

# ════════════════════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════════════════════
echo ""
section "结果汇总"
echo "  自动校验: ${GREEN}${PASS_COUNT} pass${NC}, ${YELLOW}${WARN_COUNT} warn${NC}, ${RED}${FAIL_COUNT} fail${NC}"

if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "\n${RED}❌ 自动校验未通过，不可上架。${NC}"
    exit 1
fi

echo -e "\n${GREEN}✅ 自动校验全部通过。${NC}"
echo "完成上面 F 节的手动清单后，即可走 Transporter 上传："
echo "  Transporter.app → 添加 SharedClipboard_appstore.pkg → 校验 → 交付"
exit 0
