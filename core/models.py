from dataclasses import dataclass, field
from typing import Optional, Union
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


class ContentType(Enum):
    TEXT = "text"
    IMAGE = "image"


@dataclass
class ClipboardItem:
    id: Optional[int] = None
    content_type: ContentType = ContentType.TEXT
    text_content: Optional[str] = None
    image_data: Optional[bytes] = None
    image_thumbnail: Optional[bytes] = None
    content_hash: str = ""
    preview: str = ""
    device_id: str = ""
    device_name: str = ""
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    is_starred: bool = False
    cloud_id: Optional[int] = None

    def __post_init__(self):
        if self.id is not None and not self.content_hash:
            logger.warning(f"ClipboardItem(id={self.id}) 的 content_hash 为空")

    @property
    def is_text(self) -> bool:
        return self.content_type == ContentType.TEXT

    @property
    def is_image(self) -> bool:
        return self.content_type == ContentType.IMAGE

    @property
    def is_cloud_synced(self) -> bool:
        return self.cloud_id is not None

    def get_display_preview(self, max_length: int = 100) -> str:
        if self.is_text and self.text_content:
            text = self.text_content.replace("\n", " ").strip()
            if len(text) > max_length:
                return text[:max_length] + "..."
            return text
        elif self.is_image:
            return "[图片]"
        return ""

    @classmethod
    def from_db_row(cls, row: Union[dict, tuple]) -> "ClipboardItem":
        if isinstance(row, dict):
            return cls(
                id=row["id"],
                content_type=ContentType(row["content_type"]),
                text_content=row.get("text_content"),
                image_data=row.get("image_data"),
                image_thumbnail=row.get("image_thumbnail"),
                content_hash=row.get("content_hash", ""),
                preview=row.get("preview", ""),
                device_id=row.get("device_id", ""),
                device_name=row.get("device_name", ""),
                created_at=row.get("created_at", 0),
                is_starred=bool(row.get("is_starred", False)),
                cloud_id=row.get("cloud_id"),
            )
        # tuple 兼容路径（向后兼容）
        return cls(
            id=row[0],
            content_type=ContentType(row[1]),
            text_content=row[2],
            image_data=row[3],
            image_thumbnail=row[4],
            content_hash=row[5],
            preview=row[6],
            device_id=row[7],
            device_name=row[8],
            created_at=row[9],
            is_starred=bool(row[10]),
            cloud_id=row[11] if len(row) > 11 else None,
        )

    def to_db_tuple(self) -> tuple:
        return (
            self.content_type.value,
            self.text_content,
            self.image_data,
            self.image_thumbnail,
            self.content_hash,
            self.preview,
            self.device_id,
            self.device_name,
            self.created_at,
            int(self.is_starred),
        )
