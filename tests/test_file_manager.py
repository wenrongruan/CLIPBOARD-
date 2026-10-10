"""我的文件：可见删除入口、失败恢复与团队账号边界。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox

from core.database import DatabaseManager
from core.entitlement_service import Plan
from core.file_models import CloudFile, FileSyncState
from core.file_repository import CloudFileRepository
from core.file_storage import materialize_for_open, sandbox_path_for
from ui.file_list_widget import FileListWidget


class _Sync(QObject):
    file_added = Signal(object)
    file_updated = Signal(object)
    file_deleted = Signal(int)
    upload_progress = Signal(int, int, int)
    download_progress = Signal(int, int, int)
    upload_finished = Signal(int, bool, str)
    download_finished = Signal(int, bool, str)
    delete_finished = Signal(int, bool, str)
    inventory_finished = Signal(int, bool, str)
    sync_error = Signal(str, int)

    def __init__(self):
        super().__init__()
        self.deleted = []

    def enqueue_delete(self, local_id):
        self.deleted.append(local_id)

    def refresh_inventory(self):
        return True


class _Entitlement(QObject):
    entitlement_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.refreshes = 0

    def current(self):
        return SimpleNamespace(
            plan=Plan.TEAM,
            team_spaces=5,
            files_quota_bytes=50 * (1 << 30),
            files_used_bytes=100,
        )

    def can_use_files(self):
        return True, ""

    def refresh_state(self):
        return False, False

    def refresh_async(self):
        self.refreshes += 1


def test_team_file_delete_keeps_local_copy_until_cloud_confirms(qapp, tmp_path, monkeypatch):
    root = tmp_path / "files"
    monkeypatch.setattr("config.get_files_local_dir", lambda: str(root))
    content = b"safe-to-delete-after-confirmation"
    sha = hashlib.sha256(content).hexdigest()
    local_path = sandbox_path_for(sha)
    local_path.write_bytes(content)

    db = DatabaseManager(str(tmp_path / "files.db"))
    repo = CloudFileRepository(db)
    local_id = repo.add_file(CloudFile(
        cloud_id=42, name="my-file.txt", local_path=str(local_path),
        size_bytes=len(content), content_sha256=sha, device_id="me",
        created_at=1, mtime=1, sync_state=FileSyncState.SYNCED.value,
    ))
    sync = _Sync()
    ent = _Entitlement()
    widget = FileListWidget(repo, sync, ent, SimpleNamespace(is_authenticated=True))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)
    try:
        assert "团队成员文件不在此列表" in widget.scope_label.text()
        widget.table.selectRow(0)
        assert widget.delete_btn.isEnabled()
        widget.delete_btn.click()

        assert sync.deleted == [local_id]
        assert repo.get_by_id(local_id).is_deleted
        assert local_path.exists()
        assert widget.model.data(widget.model.index(0, 3), Qt.DisplayRole) == "删除中"

        repo.set_sync_state(local_id, FileSyncState.ERROR.value, "无权限")
        sync.delete_finished.emit(local_id, False, "无权限")
        assert local_path.exists()
        assert widget.model.data(widget.model.index(0, 3), Qt.DisplayRole) == "删除失败"

        widget._retry_delete(widget.model.file_at(0))
        assert sync.deleted == [local_id, local_id]
        repo.set_sync_state(local_id, FileSyncState.SYNCED.value)
        sync.delete_finished.emit(local_id, True, "")
        assert widget.model.rowCount() == 0
        assert not local_path.exists()
        assert ent.refreshes == 1
    finally:
        widget.close()
        widget.deleteLater()
        db.close()


def test_switching_accounts_clears_previous_file_index_and_caches(tmp_path, monkeypatch):
    root = tmp_path / "files"
    monkeypatch.setattr("config.get_files_local_dir", lambda: str(root))
    content = b"private-account-file"
    sha = hashlib.sha256(content).hexdigest()
    local_path = sandbox_path_for(sha)
    local_path.write_bytes(content)
    opened_path = materialize_for_open(str(local_path), "private.txt")

    db = DatabaseManager(str(tmp_path / "account-scope.db"))
    try:
        owner_repo = CloudFileRepository(db, account_identifier="owner@example.com")
        owner_repo.add_file(CloudFile(
            cloud_id=9, name="private.txt", local_path=str(local_path),
            size_bytes=len(content), content_sha256=sha, device_id="owner",
            created_at=1, mtime=1, sync_state=FileSyncState.SYNCED.value,
        ))

        same_account_repo = CloudFileRepository(
            db, account_identifier="OWNER@example.com"
        )
        assert not same_account_repo.bind_account("owner@example.com")
        assert owner_repo.list_files()

        teammate_repo = CloudFileRepository(
            db, account_identifier="teammate@example.com"
        )
        assert teammate_repo.list_files() == []
        assert not local_path.exists()
        assert not Path(opened_path).exists()

        def read_scope(conn):
            return db.fetch_scalar(
                conn,
                "SELECT value FROM app_meta WHERE key = ?",
                (CloudFileRepository._ACCOUNT_SCOPE_META_KEY,),
                "",
            )

        scope = db.execute_read(read_scope)
        assert len(scope) == 64
        assert scope != "teammate@example.com"
    finally:
        db.close()
