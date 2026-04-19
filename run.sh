#!/usr/bin/env bash
# 共享剪贴板开发态快捷启动: ./run.sh [--appstore]
#   不带参数 → 正常调试模式
#   --appstore → 模拟 App Store 沙盒环境 (IS_APPSTORE_BUILD=True)

set -e
cd "$(dirname "$0")"

if [[ ! -d .venv_appstore ]]; then
  echo "未找到 .venv_appstore, 先运行: python3 -m venv .venv_appstore && .venv_appstore/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ "$1" == "--appstore" ]]; then
  export APP_SANDBOX_CONTAINER_ID=test
fi

exec ./.venv_appstore/bin/python main.py
