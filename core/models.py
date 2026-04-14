from dataclasses import dataclass, field
from typing import Optional
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
        # 不变式校验：类型与载荷一致
        if self.content_type == ContentType.TEXT and self.text_content is None and self.id is None:
            logger.debug("创建文本条目但 text_content 为 None")
        if self.content_type == ContentType.IMAGE and self.image_data is None and self.image_thumbnail is None and self.id is None:
            logger.debug("创建图片条目但缺少 image_data 与 image_thumbnail")

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
    def from_db_row(cls, row) -> "ClipboardItem":
        # SQLite 的 sqlite3.Row 与 PyMySQL 的 DictCursor 都支持键下标访问
        # Repository 的 _SELECT_FIELDS 统一包含全部列，可直接索引
        return cls(
            id=row["id"],
            content_type=ContentType(row["content_type"]),
            text_content=row["text_content"],
            image_data=row["image_data"],
            image_thumbnail=row["image_thumbnail"],
            content_hash=row["content_hash"] or "",
            preview=row["preview"] or "",
            device_id=row["device_id"] or "",
            device_name=row["device_name"] or "",
            created_at=row["created_at"] or 0,
            is_starred=bool(row["is_starred"]),
            cloud_id=row["cloud_id"],
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
