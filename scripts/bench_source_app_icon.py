#!/usr/bin/env python3
"""对比 macOS 取 App 图标（NSImage → PNG）的几种实现，找出最省时且不失真的做法。

背景：ui/source_app_icons.py 的 `_resolve_macos` 在真机上每个来源 App 要 300~500ms，
几乎全部耗在「把 NSImage 的 TIFFRepresentation 转成 NSBitmapImageRep 再 PNG 编码」，
而调用方（ui/clipboard_item.py::_make_source_icon_label）只需要一个 16x16 的图标。
App 的 .icns 里带 1024x1024，于是为了 32 物理像素编码了一张 1024x1024 的 PNG。

用法：
    ./.venv_appstore/bin/python scripts/bench_source_app_icon.py
产物：/tmp/sc_icon_bench/*.png（可直接肉眼比对四种实现是否一致）
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 调用方要的是 16x16 逻辑像素，Retina 下需要 32x32 物理像素
TARGET = 32

BUNDLES = [
    "com.google.Chrome",
    "com.apple.Terminal",
    "com.tencent.xinWeChat",
    "com.apple.finder",
    "com.openai.codex",
]

OUT_DIR = "/tmp/sc_icon_bench"


def ms(t0: float) -> float:
    return (time.time() - t0) * 1000.0


# ---- A: 现状 ----------------------------------------------------------------


def impl_current(ns_image):
    from Cocoa import NSBitmapImageRep, NSPNGFileType

    tiff = ns_image.TIFFRepresentation()
    rep = NSBitmapImageRep.imageRepWithData_(tiff)
    png = rep.representationUsingType_properties_(NSPNGFileType, None)
    return bytes(png) if png is not None else None


# ---- B: 让 NSImage 自己挑一块合适的 representataion --------------------------


def impl_best_rep(ns_image):
    from AppKit import NSMakeRect
    from Cocoa import NSPNGFileType

    rect = NSMakeRect(0.0, 0.0, float(TARGET), float(TARGET))
    rep = ns_image.bestRepresentationForRect_context_hints_(rect, None, None)
    if rep is None:
        return None
    png = rep.representationUsingType_properties_(NSPNGFileType, None)
    return bytes(png) if png is not None else None


# ---- C: 自己开一块 TARGET x TARGET 的画布，把图标画进去 -----------------------


def impl_draw_small(ns_image):
    from AppKit import (
        NSBitmapImageRep,
        NSCompositingOperationCopy,
        NSDeviceRGBColorSpace,
        NSGraphicsContext,
        NSZeroRect,
    )
    from Cocoa import NSPNGFileType

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, TARGET, TARGET, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    if rep is None:
        return None
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    if ctx is None:
        return None
    NSGraphicsContext.saveGraphicsState()
    try:
        NSGraphicsContext.setCurrentContext_(ctx)
        ns_image.drawInRect_fromRect_operation_fraction_(
            ((0.0, 0.0), (float(TARGET), float(TARGET))),
            NSZeroRect,
            NSCompositingOperationCopy,
            1.0,
        )
    finally:
        NSGraphicsContext.restoreGraphicsState()
    png = rep.representationUsingType_properties_(NSPNGFileType, None)
    return bytes(png) if png is not None else None


# ---- D: 完全绕开 NSWorkspace，用 Qt 自己的图标提供者 --------------------------


def impl_qt_provider(app_path: str):
    from PySide6.QtCore import QBuffer, QFileInfo, QIODevice
    from PySide6.QtWidgets import QFileIconProvider

    global _provider
    try:
        _provider
    except NameError:
        _provider = QFileIconProvider()
    icon = _provider.icon(QFileInfo(app_path))
    if icon.isNull():
        return None
    pix = icon.pixmap(TARGET, TARGET)
    if pix.isNull():
        return None
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    os.makedirs(OUT_DIR, exist_ok=True)

    from AppKit import NSWorkspace

    ws = NSWorkspace.sharedWorkspace()

    impls = [
        ("A 现状(TIFF->rep->PNG)", impl_current),
        ("B bestRepresentation", impl_best_rep),
        ("C 画进小画布", impl_draw_small),
    ]

    totals = {name: 0.0 for name, _ in impls}
    totals["D Qt provider"] = 0.0

    for bid in BUNDLES:
        path = ws.absolutePathForAppBundleWithIdentifier_(bid)
        if not path:
            print(f"{bid}: 找不到 app 路径，跳过")
            continue
        ns_image = ws.iconForFile_(path)
        print(f"\n{bid}  ->  {path}")

        for name, fn in impls:
            # 预热一次（首次调用含 NSImage 内部惰性加载），计时取第二次
            try:
                fn(ns_image)
            except Exception as e:  # noqa: BLE001
                print(f"  {name:22}: 预热失败 {e}")
                continue
            t0 = time.time()
            data = fn(ns_image)
            cost = ms(t0)
            totals[name] += cost
            if not data:
                print(f"  {name:22}: 无输出")
                continue
            pix = QPixmap()
            pix.loadFromData(data)
            safe = bid.replace(".", "_")
            outp = os.path.join(OUT_DIR, f"{safe}__{name[0]}.png")
            with open(outp, "wb") as f:
                f.write(data)
            print(
                f"  {name:22}: {cost:7.1f}ms  png={len(data)/1024:8.1f}KB  "
                f"解码后={pix.width()}x{pix.height()}"
            )

        # D 只看一次（与 NSImage 无关）
        t0 = time.time()
        data = impl_qt_provider(path)
        cost = ms(t0)
        totals["D Qt provider"] += cost
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            safe = bid.replace(".", "_")
            with open(os.path.join(OUT_DIR, f"{safe}__D.png"), "wb") as f:
                f.write(data)
            print(
                f"  {'D Qt provider':22}: {cost:7.1f}ms  png={len(data)/1024:8.1f}KB  "
                f"解码后={pix.width()}x{pix.height()}"
            )

    print()
    print("=" * 62)
    for name, total in sorted(totals.items(), key=lambda kv: kv[1]):
        print(f"{name:24} 合计 {total:8.1f}ms   平均 {total/len(BUNDLES):7.1f}ms/app")
    print("=" * 62)
    print(f"产物目录: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
