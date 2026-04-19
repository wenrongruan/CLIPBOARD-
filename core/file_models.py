"""云端文件数据模型 — 与剪贴板 ClipboardItem 平行的独立域。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class FileSyncState(str, Enum):
    """本地条目的同步状态机。
    - pending: 新增或本地发生变更，尚未向云端推送
    - syncing: 当前正在上传 / 下载
    - synced:  最近一次操作已成功
    - error:   上次失败，等待重试
    - remote_only: 从云端拉取到元数据，但本地还没下载正文
    """
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"
    REMOTE_ONLY = "remote_only"


@dataclass
class CloudFile:
    """云端文件条目。`sync_state` 是字符串以便直接塞进 SQL。"""

    id: Optional[int] = None
    cloud_id: Optional[int] = None
    name: str = ""
    original_path: str = ""
    local_path: str = ""
    size_bytes: int = 0
    mime_type: str = ""
    content_sha256: str = ""
    mtime: int = field(default_factory=lambda: int(time.time() * 1000))
    device_id: str = ""
    device_name: str = ""
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    is_deleted: bool = False
    sync_state: str = FileSyncState.PENDING.value
    last_error: str = ""
    bookmark: Optional[bytes] = None

    @property
    def is_cloud_synced(self) -> bool:
        return self.cloud_id is not None

    def to_db_tuple(self) -> tuple:
        """顺序对应 INSERT INTO cloud_files (cloud_id, name, original_path, local_path,
        size_bytes, mime_type, content_sha256, mtime, device_id, device_name,
        created_at, is_deleted, sync_state, last_error, bookmark)."""
        return (
            self.cloud_id,
            self.name,
            self.original_path or None,
            self.local_path or None,
            int(self.size_bytes),
            self.mime_type or None,
            self.content_sha256,
            int(self.mtime),
            self.device_id,
            self.device_name or None,
            int(self.created_at),
            1 if self.is_deleted else 0,
            self.sync_state,
            self.last_error or None,
            self.bookmark,
        )

    @classmethod
    def from_db_row(cls, row) -> "CloudFile":
        return cls(
            id=row["id"],
            cloud_id=row["cloud_id"],
            name=row["name"] or "",
            original_path=row["original_path"] or "",
            local_path=row["local_path"] or "",
            size_bytes=int(row["size_bytes"] or 0),
            mime_type=row["mime_type"] or "",
            content_sha256=row["content_sha256"] or "",
            mtime=int(row["mtime"] or 0),
            device_id=row["device_id"] or "",
            device_name=row["device_name"] or "",
            created_at=int(row["created_at"] or 0),
            is_deleted=bool(row["is_deleted"]),
            sync_state=row["sync_state"] or FileSyncState.PENDING.value,
            last_error=row["last_error"] or "",
            bookmark=row["bookmark"],
        )
