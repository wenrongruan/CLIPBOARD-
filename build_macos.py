# DEPRECATED: 推荐使用 build_mac.sh / build_appstore.sh (PyInstaller)
# 本 py2app 路径未与主构建流程同步，仅保留历史兼容
"""
macOS 打包脚本
使用 py2app 将应用打包为 macOS .app 文件

使用方法:
1. 确保在 macOS 上运行
2. pip install py2app
3. python build_macos.py py2app
"""

from setuptools import setup
import sys
import platform

print("[warn] build_macos.py 已弃用，建议改用 build_mac.sh / build_appstore.sh (PyInstaller)")

if platform.system() != "Darwin":
    print("此脚本只能在 macOS 上运行")
    sys.exit(1)

APP = ['main.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,  # 不需要命令行参数模拟
    'plist': {
        'CFBundleName': '共享剪贴板',
        'CFBundleDisplayName': '共享剪贴板',
        'CFBundleIdentifier': 'com.sharedclipboard.app',
        'CFBundleVersion': '3.2.7',
        'CFBundleShortVersionString': '3.2.7',
        'LSUIElement': True,  # 作为菜单栏应用运行，不显示在 Dock
        'NSHighResolutionCapable': True,  # 支持 Retina 显示
        'NSRequiresAquaSystemAppearance': False,  # 支持深色模式
    },
    'packages': ['PySide6', 'PIL'],
    'includes': [
        'core',
        'ui',
        'utils',
        'config',
    ],
    'excludes': [
        'tkinter',
        'unittest',
        'email',
        'http',
        'xml',
    ],
}

setup(
    app=APP,
    name='共享剪贴板',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
