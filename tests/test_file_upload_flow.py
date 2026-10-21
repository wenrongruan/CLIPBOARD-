"""文件上传链路的回归测试。"""

from __future__ import annotations

import hashlib
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cloud_api import CloudAPIClient
from core.database import DatabaseManager
from core.file_models import CloudFile, FileSyncState
from core.file_repository import CloudFileRepository
from core.file_sync_service import _FileSyncWorker
from core.file_storage import guess_mime


class _FakeEntitlement:
    def __init__(self):
        self.recorded_sizes: list[int] = []

    def can_upload(self, size: int):
        return True, ""

    def record_local_upload(self, size: int) -> None:
        self.recorded_sizes.append(size)


def test_mime_guess_does_not_read_system_mime_database(monkeypatch):
    from core import file_storage

    def denied(_name):
        raise PermissionError(1, "Operation not permitted", "/etc/apache2/mime.types")

    monkeypatch.setattr(file_storage.mimetypes, "guess_type", denied)
    monkeypatch.setattr(file_storage.mimetypes, "init", lambda *args, **kwargs: denied("init"))
    assert guess_mime("report.pdf") == "application/pdf"
    assert guess_mime("budget.xlsx") == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert guess_mime("archive.unknownsuffix") == "application/octet-stream"


def test_inventory_recovers_cloud_file_missing_from_local_database(repo):
    class API:
        def files_list_page(self, page, per_page=100):
            assert page == 1
            assert per_page == 100
            return {"total": 1, "items": [{
                "id": 765,
                "name": "cloud-only.pdf",
                "sha256": "a" * 64,
                "size_bytes": 24,
                "upload_status": 2,
                "created_at": 1,
                "mtime": 1,
            }]}

    worker = _FileSyncWorker(API(), repo, _FakeEntitlement())
    completed = []
    worker.inventory_done.connect(lambda files, skipped: completed.append((files, skipped)))
    worker.do_inventory()

    assert len(completed) == 1
    files, skipped = completed[0]
    assert skipped == 0
    assert len(files) == 1
    assert files[0].cloud_id == 765
    assert files[0].sync_state == FileSyncState.REMOTE_ONLY.value
    assert repo.get_by_cloud_id(765).name == "cloud-only.pdf"


def test_inventory_reads_all_pages(repo):
    class API:
        def __init__(self):
            self.pages = []

        def files_list_page(self, page, per_page=100):
            self.pages.append(page)
            ids = range(1, 101) if page == 1 else range(101, 102)
            return {"total": 101, "items": [
                {"id": i, "name": f"f{i}.txt", "sha256": f"{i:064x}",
                 "size_bytes": 1, "upload_status": 2, "created_at": i, "mtime": i}
                for i in ids
            ]}

    api = API()
    worker = _FileSyncWorker(api, repo, _FakeEntitlement())
    worker.do_inventory()

    assert api.pages == [1, 2]
    assert len(repo.list_files()) == 101


class _ExistsCloudAPI:
    def __init__(self, cloud_id: int = 123):
        self.cloud_id = cloud_id

    def files_request_upload(self, meta: dict) -> dict:
        return {
            "upload_mode": "exists",
            "cloud_id": self.cloud_id,
        }

    def upload_file_to_url(self, *args, **kwargs):
        raise AssertionError("exists 模式不应再次上传文件")

    def files_complete_upload(self, *args, **kwargs):
        raise AssertionError("exists 模式不应调用 complete")


class _SingleCloudAPI:
    def __init__(self, cloud_id: int = 321):
        self.cloud_id = cloud_id
        self.upload_calls: list[dict] = []
        self.complete_calls: list[tuple[int, list]] = []

    def files_request_upload(self, meta: dict) -> dict:
        return {
            "upload_mode": "single",
            "cloud_id": self.cloud_id,
            "upload_url": "https://oss-cn-shanghai.aliyuncs.com/sharedclipboard/test.bin?sig=1",
            "complete_url": f"/api/v1/files/{self.cloud_id}/complete",
        }

    def upload_file_to_url(
        self,
        url: str,
        file_path: str,
        part_offset: int = 0,
        part_size: int | None = None,
        progress_cb=None,
        extra_headers: dict | None = None,
    ) -> str:
        self.upload_calls.append({
            "url": url,
            "file_path": file_path,
            "part_offset": part_offset,
            "part_size": part_size,
            "extra_headers": extra_headers,
        })
        if progress_cb is not None:
            size = os.path.getsize(file_path)
            progress_cb(size, size)
        return "etag-1"

    def files_complete_upload(self, cloud_id: int, parts: list) -> dict:
        self.complete_calls.append((cloud_id, parts))
        return {}


class _DeleteCloudAPI:
    def __init__(self, result: bool):
        self.result = result
        self.deleted_ids: list[int] = []

    def files_delete(self, cloud_id: int) -> bool:
        self.deleted_ids.append(cloud_id)
        return self.result


class _PullCloudAPI:
    def __init__(self, items: list[dict]):
        self.items = items

    def files_list(self, device_id: str, since_change_id: int = 0) -> dict:
        items = [
            {**item, "change_id": item.get("change_id", item["id"])}
            for item in self.items
        ]
        return {
            "items": items,
            "has_more": False,
            "next_since_change_id": max(
                [since_change_id] + [item["change_id"] for item in items]
            ),
        }


class _LegacyPullCloudAPI:
    def __init__(self, items: list[dict]):
        self.items = items
        self.calls: list[tuple[str, int]] = []

    def files_list(
        self,
        since_id: int = 0,
        device_id: str = "",
        limit: int = 100,
        *,
        since_change_id: int | None = None,
    ) -> dict:
        # 旧服务忽略 since_change_id，第一次总是从文件 id 0 返回。
        legacy_cursor = since_id if since_change_id is None else 0
        self.calls.append(("legacy" if since_change_id is None else "probe", legacy_cursor))
        remaining = [item for item in self.items if item["id"] > legacy_cursor]
        page = remaining[:1]
        next_id = page[-1]["id"] if page else legacy_cursor
        return {
            "items": page,
            "has_more": len(remaining) > 1,
            "next_since_id": next_id,
        }


@pytest.fixture
def repo(tmp_path):
    db = DatabaseManager(str(tmp_path / "upload.db"))
    r = CloudFileRepository(db)
    yield r
    db.close()


def _make_file(repo: CloudFileRepository, tmp_path, name: str, content: bytes) -> int:
    path = tmp_path / name
    path.write_bytes(content)
    f = CloudFile(
        name=name,
        local_path=str(path),
        size_bytes=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
        device_id="dev-1",
        device_name="device",
        created_at=1,
        mtime=1,
    )
    return repo.add_file(f)


def test_upload_file_to_url_sends_extra_headers(tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.read()
        return httpx.Response(200, headers={"ETag": '"etag-123"'})

    client = CloudAPIClient("https://www.jlike.com")
    client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    path = tmp_path / "a.bin"
    path.write_bytes(b"hello")

    etag = client.upload_file_to_url(
        "https://oss-cn-shanghai.aliyuncs.com/sharedclipboard/a.bin?sig=1",
        str(path),
        extra_headers={"x-oss-object-acl": "private"},
    )

    assert etag == "etag-123"
    assert seen["body"] == b"hello"
    headers = httpx.Headers(seen["headers"])
    assert headers["content-type"] == "application/octet-stream"
    assert headers["x-oss-object-acl"] == "private"

    client.close()


def test_worker_marks_exists_upload_as_synced(repo, tmp_path):
    entitlement = _FakeEntitlement()
    cloud_api = _ExistsCloudAPI(cloud_id=456)
    local_id = _make_file(repo, tmp_path, "exists.txt", b"same-bytes")

    worker = _FileSyncWorker(cloud_api, repo, entitlement)
    worker.do_upload(local_id)

    saved = repo.get_by_id(local_id)
    assert saved is not None
    assert saved.cloud_id == 456
    assert saved.sync_state == FileSyncState.SYNCED.value
    assert saved.last_error == ""
    assert entitlement.recorded_sizes == []


def test_worker_single_upload_adds_private_acl_header(repo, tmp_path):
    entitlement = _FakeEntitlement()
    cloud_api = _SingleCloudAPI(cloud_id=789)
    local_id = _make_file(repo, tmp_path, "single.txt", b"single-upload")

    worker = _FileSyncWorker(cloud_api, repo, entitlement)
    worker.do_upload(local_id)

    saved = repo.get_by_id(local_id)
    assert saved is not None
    assert saved.cloud_id == 789
    assert saved.sync_state == FileSyncState.SYNCED.value
    assert cloud_api.upload_calls[0]["extra_headers"] == {"x-oss-object-acl": "private"}
    assert cloud_api.complete_calls == [
        (789, [{"part_number": 1, "etag": "etag-1"}]),
    ]
    assert entitlement.recorded_sizes == [len(b"single-upload")]


def test_worker_delete_persists_success(repo, tmp_path):
    local_id = _make_file(repo, tmp_path, "delete.txt", b"delete-me")
    repo.update_meta(local_id, cloud_id=901)
    repo.mark_deleted(local_id)
    cloud_api = _DeleteCloudAPI(result=True)

    worker = _FileSyncWorker(cloud_api, repo, _FakeEntitlement())
    worker.do_delete(local_id)

    saved = repo.get_by_id(local_id)
    assert saved is not None
    assert saved.is_deleted is True
    assert saved.sync_state == FileSyncState.SYNCED.value
    assert saved.last_error == ""
    assert cloud_api.deleted_ids == [901]


def test_worker_delete_persists_failure_for_retry(repo, tmp_path):
    local_id = _make_file(repo, tmp_path, "delete-fail.txt", b"delete-me-later")
    repo.update_meta(local_id, cloud_id=902)
    repo.mark_deleted(local_id)
    cloud_api = _DeleteCloudAPI(result=False)

    worker = _FileSyncWorker(cloud_api, repo, _FakeEntitlement())
    worker.do_delete(local_id)

    saved = repo.get_by_id(local_id)
    assert saved is not None
    assert saved.is_deleted is True
    assert saved.sync_state == FileSyncState.ERROR.value
    assert "删除" in saved.last_error
    assert cloud_api.deleted_ids == [902]
    assert (tmp_path / "delete-fail.txt").exists()


def test_pull_normalizes_uppercase_sha(repo):
    uppercase_sha = "ABCDEF" * 10 + "ABCD"
    cloud_api = _PullCloudAPI([{
        "id": 903,
        "name": "upper.bin",
        "content_sha256": uppercase_sha,
        "size_bytes": 10,
    }])

    worker = _FileSyncWorker(cloud_api, repo, _FakeEntitlement())
    worker.do_pull(0)

    saved = repo.get_by_cloud_id(903)
    assert saved is not None
    assert saved.content_sha256 == uppercase_sha.lower()


def test_pull_applies_delete_tombstone_without_sha(repo, tmp_path):
    local_id = _make_file(repo, tmp_path, "remote-delete.txt", b"delete-remotely")
    repo.update_meta(
        local_id,
        cloud_id=904,
        sync_state=FileSyncState.SYNCED.value,
    )
    cloud_api = _PullCloudAPI([{
        "id": 904,
        "is_deleted": True,
    }])

    worker = _FileSyncWorker(cloud_api, repo, _FakeEntitlement())
    pulled = []
    worker.pull_done.connect(lambda items, _cursor: pulled.extend(items))
    worker.do_pull(0)

    saved = repo.get_by_id(local_id)
    assert saved is not None
    assert saved.is_deleted is True
    assert saved.sync_state == FileSyncState.SYNCED.value
    assert [item.id for item in pulled] == [local_id]


def test_pull_falls_back_to_legacy_since_id_without_advancing_event_cursor(repo):
    api = _LegacyPullCloudAPI([
        {
            "id": 11,
            "name": "old-server-a.txt",
            "content_sha256": "a" * 64,
            "size_bytes": 1,
        },
        {
            "id": 12,
            "name": "old-server-b.txt",
            "content_sha256": "b" * 64,
            "size_bytes": 2,
        },
    ])
    worker = _FileSyncWorker(api, repo, _FakeEntitlement())
    completed = []
    errors = []
    worker.pull_done.connect(lambda items, cursor: completed.append((items, cursor)))
    worker.pull_error.connect(lambda message, status: errors.append((message, status)))

    worker.do_pull(0)

    assert errors == []
    assert sorted(f.cloud_id for f in repo.list_files()) == [11, 12]
    assert [call for call in api.calls] == [("probe", 0), ("legacy", 11)]
    assert completed[-1][1] == 0

    worker.do_pull(0)
    assert api.calls[-1] == ("legacy", 12)
    assert completed[-1][1] == 0
