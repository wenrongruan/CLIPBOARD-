@echo off
setlocal EnableExtensions

rem SharedClipboard Windows 打包脚本。
rem 在 Windows 10/11 的命令提示符中双击或执行此文件即可生成 dist\SharedClipboard.exe。

cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [错误] 未找到 Python 3。请先从 https://www.python.org/downloads/windows/ 安装 Python 3.11+。
        exit /b 1
    )
    set "PYTHON=python"
)

%PYTHON% --version
if errorlevel 1 (
    echo [错误] 无法运行 Python 解释器。
    exit /b 1
)

set "VENV_DIR=.venv_windows"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/4] 创建 Windows 构建环境...
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b 1
)

set "VENV_PYTHON=%CD%\%VENV_DIR%\Scripts\python.exe"

echo [2/4] 安装运行时和打包依赖...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

echo [3/4] 生成单文件 Windows 程序...
"%VENV_PYTHON%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --noconfirm ^
    --clean ^
    --name "SharedClipboard" ^
    --icon "icons\app.ico" ^
    --add-data "icons;icons" ^
    --add-data "plugins;plugins" ^
    --add-data "sql;sql" ^
    --add-data "i18n_strings;i18n_strings" ^
    --hidden-import "PySide6.QtCore" ^
    --hidden-import "PySide6.QtGui" ^
    --hidden-import "PySide6.QtWidgets" ^
    --hidden-import "PIL" ^
    --hidden-import "pymysql" ^
    --hidden-import "httpx" ^
    --hidden-import "keyring.backends.Windows" ^
    --hidden-import "core.source_app.windows" ^
    --hidden-import "psutil" ^
    --hidden-import "win32gui" ^
    --hidden-import "win32process" ^
    --collect-submodules "keyring" ^
    main.py
if errorlevel 1 (
    echo [错误] 打包失败，请查看上方 PyInstaller 输出。
    exit /b 1
)

echo [4/4] 验证产物...
if not exist "dist\SharedClipboard.exe" (
    echo [错误] 未找到 dist\SharedClipboard.exe。
    exit /b 1
)

echo.
echo 打包完成：%CD%\dist\SharedClipboard.exe
echo 首次运行时，Windows 可能要求允许剪贴板访问或全局热键监听。
endlocal
