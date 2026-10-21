#!/usr/bin/env python3
"""
生成 macOS App Store 所需的 .icns 图标文件。

用法（在 macOS 上运行）:
    python create_icns.py

输出: icons/AppIcon.icns

需求: Pillow（pip install Pillow）、macOS 系统工具 iconutil
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("错误: 需要安装 Pillow，请运行: pip install Pillow")
    sys.exit(1)

# 源图标路径（优先使用高分辨率版本）
SCRIPT_DIR = Path(__file__).parent
ICON_CANDIDATES = [
    SCRIPT_DIR / "icons" / "icon_macos.png",
    SCRIPT_DIR / "icons" / "app.png",
    SCRIPT_DIR / "icons" / "icon.png",
]

# App Store 要求的 iconset 尺寸规格
# 格式: (文件名后缀, 实际像素尺寸)
ICONSET_SIZES = [
    ("icon_16x16",       16),
    ("icon_16x16@2x",    32),
    ("icon_32x32",       32),
    ("icon_32x32@2x",    64),
    ("icon_128x128",    128),
    ("icon_128x128@2x", 256),
    ("icon_256x256",    256),
    ("icon_256x256@2x", 512),
    ("icon_512x512",    512),
    ("icon_512x512@2x", 1024),
]

ICONSET_DIR = SCRIPT_DIR / "AppIcon.iconset"
OUTPUT_ICNS = SCRIPT_DIR / "icons" / "AppIcon.icns"


def find_source_icon() -> Path:
    for candidate in ICON_CANDIDATES:
        if candidate.exists():
            return candidate
    print("错误: 找不到源图标文件，已查找以下路径:")
    for c in ICON_CANDIDATES:
        print(f"  {c}")
    sys.exit(1)


def generate_iconset(source: Path):
    """用 Pillow 生成 iconset 目录中的所有尺寸"""
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir()

    img = Image.open(source).convert("RGBA")
    src_w, src_h = img.size
    print(f"源图标: {source} ({src_w}×{src_h})")

    for name, size in ICONSET_SIZES:
        resized = img.resize((size, size), Image.LANCZOS)
        out_path = ICONSET_DIR / f"{name}.png"
        resized.save(out_path, "PNG")
        print(f"  生成 {name}.png ({size}×{size})")

    print(f"\niconset 目录已生成: {ICONSET_DIR}")


def run_iconutil():
    """调用 macOS iconutil 将 iconset 转换为 icns"""
    if not shutil.which("iconutil"):
        print("错误: 未找到 iconutil，此脚本必须在 macOS 上运行")
        sys.exit(1)

    OUTPUT_ICNS.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(OUTPUT_ICNS)],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"错误: iconutil 失败\n{result.stderr}")
        sys.exit(1)

    print(f"AppIcon.icns 已生成: {OUTPUT_ICNS}")
    print(f"文件大小: {OUTPUT_ICNS.stat().st_size / 1024:.1f} KB")


def cleanup():
    """删除临时 iconset 目录"""
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
        print(f"已清理临时目录: {ICONSET_DIR}")


def main():
    print("=== SharedClipboard AppIcon.icns 生成器 ===\n")
    source = find_source_icon()
    generate_iconset(source)
    run_iconutil()
    cleanup()
    print("\n完成！请将 icons/AppIcon.icns 包含在构建中。")


if __name__ == "__main__":
    main()
