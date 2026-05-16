"""CloudAPIClient facade public 方法完整性回归。

Phase 3 起 cloud_api 拆成 facade + 4 个 domain client；为防止后续重构
"漏方法",这里把重构前的 public 方法清单 (tests/_cloud_api_public_methods.txt)
作为 ground truth,确保 facade 上每一个都仍可访问。
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.cloud_api import CloudAPIClient


def test_no_public_method_dropped():
    baseline_file = Path(__file__).parent / "_cloud_api_public_methods.txt"
    expected = {m.strip() for m in baseline_file.read_text().splitlines() if m.strip()}
    actual = {
        n for n, _ in inspect.getmembers(CloudAPIClient, predicate=inspect.isfunction)
        if not n.startswith("_")
    }
    missing = expected - actual
    assert not missing, f"CloudAPIClient facade 漏方法: {sorted(missing)}"
