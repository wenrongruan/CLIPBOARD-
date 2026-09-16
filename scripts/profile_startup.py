#!/usr/bin/env python3
"""主窗口构造期的耗时剖面。

Why 需要这个：`MainWindow.__init__` 在真机上要 7.5s（日志里
"[startup] MainWindow(__init__) 用时 ..."），是整个启动耗时的大头，
但 main.py 的 startup_metrics 只到"创建主窗口"这一层，看不出里面慢在哪。

用法：
    SC_DEBUG=1 ./.venv_appstore/bin/python scripts/profile_startup.py
    SC_DEBUG=1 ./.venv_appstore/bin/python scripts/profile_startup.py --top 30
"""

from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25, help="打印前 N 条")
    ap.add_argument("--sort", default="cumulative", help="pstats 排序键")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)

    from core.app_context import AppContext  # noqa: E402
    from ui.styles import MAIN_STYLE  # noqa: E402

    t0 = time.time()
    ctx = AppContext.bootstrap()
    t_boot = time.time() - t0

    from ui.main_window import MainWindow  # noqa: E402
    from ui.sidebar import Sidebar  # noqa: E402

    # 分段计时：把 __init__ 里的每一步单独测一遍
    marks = []

    def _mark(name, t_start):
        marks.append((name, time.time() - t_start))

    prof = cProfile.Profile()
    prof.enable()
    t = time.time()
    win = MainWindow(ctx=ctx)
    _mark("MainWindow(ctx=ctx) 合计", t)
    prof.disable()

    print()
    print("=" * 70)
    print(f"AppContext.bootstrap          : {t_boot:.3f}s")
    print(f"MainWindow.__init__           : {marks[0][1]:.3f}s")
    print("=" * 70)

    # 二次测量：单独重建 Sidebar，确认侧栏自己的成本
    t = time.time()
    sb = Sidebar(
        space_service=ctx.space_service,
        tag_service=ctx.tag_service,
        entitlement_service=ctx.entitlement_service,
    )
    side = time.time() - t
    sb.deleteLater()
    print(f"Sidebar(...)                  : {side:.3f}s")

    # 主窗口 setStyleSheet 的成本
    t = time.time()
    win.setStyleSheet(MAIN_STYLE)
    print(f"MainWindow.setStyleSheet      : {time.time()-t:.3f}s")

    print()
    print("-" * 70)
    print(f"cProfile 热点（按 {args.sort} 排序，前 {args.top} 条）")
    print("-" * 70)
    buf = io.StringIO()
    stats = pstats.Stats(prof, stream=buf).sort_stats(args.sort)
    stats.print_stats(args.top)
    # 只留最有信息量的几行，避免把 pstats 表头噪声全倒出来
    for line in buf.getvalue().splitlines():
        if line.strip():
            print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
