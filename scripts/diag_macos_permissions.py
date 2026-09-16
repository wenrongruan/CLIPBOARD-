#!/usr/bin/env python3
"""macOS 权限诊断：屏幕录制 / 输入监控 / 辅助功能。

截图要「屏幕录制」（kTCCServiceScreenCapture），全局热键要「输入监控」
（kTCCServiceListenEvent）。两者都 fail-open —— 探测失败时程序会当成"有权限"
继续跑，所以「热键按了没反应 / 截图静默失败」的第一嫌疑往往是这里。

直接跑：
    ./.venv_appstore/bin/python scripts/diag_macos_permissions.py

注意 TCC 是按「负责进程」记账的：从终端里跑，授权对象是终端 App
（Terminal / iTerm），不是 Python 本身。要看应用自己的权限状态，
就用 run.sh 启动应用后从日志里看。
"""

from __future__ import annotations

import os
import subprocess
import sys

IS_MACOS = sys.platform == "darwin"


def _probe(symbol: str) -> str:
    """调用一个 CGPreflight* 符号，返回 'True' / 'False' / 'UNAVAILABLE' / 'ERROR: ...'. """
    try:
        import Quartz
    except Exception as e:  # noqa: BLE001
        return f"QUARTZ-MISSING ({e})"
    fn = getattr(Quartz, symbol, None)
    if fn is None:
        return "UNAVAILABLE"
    try:
        return str(bool(fn()))
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def _responsible_app() -> str:
    """谁在为这次探测"背锅"（TCC 的 responsible process）。"""
    try:
        out = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                'tell application "System Events" to get name of first '
                "application process whose frontmost is true",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        front = out.stdout.strip()
    except Exception:  # noqa: BLE001
        front = "?"
    parent = os.environ.get("TERM_PROGRAM") or os.environ.get("__CFBundleIdentifier") or "?"
    return f"前台 App={front!r} / 启动它的程序={parent!r}"


def main() -> int:
    print("=" * 62)
    print("macOS 权限诊断")
    print("=" * 62)
    print(f"python        : {sys.executable}")
    print(f"platform      : {sys.platform} {os.uname().release}")
    print(f"负责进程      : {_responsible_app()}")

    if not IS_MACOS:
        print("\n非 macOS，无 TCC 权限概念。")
        return 0

    checks = [
        ("CGPreflightScreenCaptureAccess", "屏幕录制", "截图（screencapture / 抓屏）"),
        ("CGPreflightListenEventAccess", "输入监控", "全局热键（NSEvent global monitor）"),
        ("CGPreflightPostEventAccess", "辅助功能", "向其他 App 发送按键（本程序不需要）"),
    ]
    print()
    for symbol, name, purpose in checks:
        print(f"{name:<6} ({purpose})")
        print(f"  {symbol}() -> {_probe(symbol)}")

    print()
    print("-" * 62)
    print("判读：")
    print("  True        = 已授权")
    print("  False       = 未授权，功能会静默失效（这是最坑的状态）")
    print("  UNAVAILABLE = 该 macOS 版本没有这个符号（<10.15 的旧系统）")
    print("  QUARTZ-MISSING = pyobjc-framework-Quartz 没装，程序会 fail-open 当成有权限")
    print()
    print("授权入口：系统设置 → 隐私与安全性 → 屏幕录制 / 输入监控")
    print("改完授权通常需要**重启该 App**（TCC 只在进程启动时读一次）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
