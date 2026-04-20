"""EntitlementService 单元测试（mock CloudAPIClient）"""

from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.database import DatabaseManager
from core.repository import ClipboardRepository
from core.entitlement_service import (
    EntitlementService, Plan, MAX_SINGLE_FILE_BYTES, reset_entitlement_service,
    get_entitlement_service,
)


class _FakeCloudAPI:
    """最小化的 cloud_api 桩：仅实现 is_authenticated + get_subscription。"""

    def __init__(self, sub):
        self._sub = sub
        self.is_authenticated = True

    def get_subscription(self):
        if isinstance(self._sub, Exception):
            raise self._sub
        return self._sub


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_entitlement_service()
    yield
    reset_entitlement_service()


@pytest.fixture
def repo(tmp_path):
    db = DatabaseManager(str(tmp_path / "e.db"))
    r = ClipboardRepository(db)
    yield r
    db.close()


def _wait_for(cond, timeout=3.0):
    """等待条件成立（用于异步 refresh 完成）。"""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_free_user_cannot_use_files(repo):
    svc = EntitlementService(
        cloud_api=_FakeCloudAPI({"plan": "free", "status": "active"}),
        repository=repo,
    )
    svc.refresh_async()
    assert _wait_for(lambda: svc.current().plan == Plan.FREE)
    ok, reason = svc.can_use_files()
    assert not ok
    assert "付费" in reason or "升级" in reason or "Basic" in reason


def test_basic_user_can_use_and_upload(repo):
    svc = EntitlementService(
        cloud_api=_FakeCloudAPI({
            "plan": "basic",
            "status": "active",
            "files": {
                "quota_bytes": 5 * (1 << 30),
                "used_bytes": 0,
                "max_file_size_bytes": 1 << 30,
            },
        }),
        repository=repo,
    )
    svc.refresh_async()
    assert _wait_for(lambda: svc.current().files_enabled)
    ok, _ = svc.can_use_files()
    assert ok
    ok2, _ = svc.can_upload(100 * (1 << 20))  # 100 MB
    assert ok2


def test_single_file_1gb_limit(repo):
    svc = EntitlementService(
        cloud_api=_FakeCloudAPI({
            "plan": "ultimate", "status": "active",
            "files": {"quota_bytes": 200 * (1 << 30), "used_bytes": 0},
        }),
        repository=repo,
    )
    svc.refresh_async()
    assert _wait_for(lambda: svc.current().files_enabled)
    too_big = MAX_SINGLE_FILE_BYTES + 1
    ok, reason = svc.can_upload(too_big)
    assert not ok
    assert "1 GB" in reason


def test_quota_exceeded_rejected(repo):
    svc = EntitlementService(
        cloud_api=_FakeCloudAPI({
            "plan": "basic", "status": "active",
            "files": {"quota_bytes": 100 * (1 << 20), "used_bytes": 80 * (1 << 20)},
        }),
        repository=repo,
    )
    svc.refresh_async()
    assert _wait_for(lambda: svc.current().files_enabled)
    # 剩余 20 MB，尝试 50 MB
    ok, reason = svc.can_upload(50 * (1 << 20))
    assert not ok
    assert "空间" in reason or "不足" in reason


def test_cache_persists_across_instances(repo):
    cloud = _FakeCloudAPI({
        "plan": "super", "status": "active",
        "files": {"quota_bytes": 50 * (1 << 30), "used_bytes": 0},
    })
    svc = EntitlementService(cloud_api=cloud, repository=repo)
    svc.refresh_async()
    assert _wait_for(lambda: svc.current().files_enabled)

    # 新开一个 EntitlementService，应该从 app_meta 读出 super
    svc2 = EntitlementService(cloud_api=None, repository=repo)
    assert svc2.current().plan == Plan.SUPER
    assert svc2.current().files_enabled


def test_invalidate_clears_cache(repo):
    svc = EntitlementService(
        cloud_api=_FakeCloudAPI({
            "plan": "basic", "status": "active",
            "files": {"quota_bytes": 5 * (1 << 30), "used_bytes": 0},
        }),
        repository=repo,
    )
    svc.refresh_async()
    assert _wait_for(lambda: svc.current().files_enabled)
    svc.invalidate()
    assert svc.current().plan == Plan.FREE
    assert not svc.current().files_enabled


def test_singleton_is_stable():
    a = get_entitlement_service()
    b = get_entitlement_service()
    assert a is b
