from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import time


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

    @property
    def is_text(self) -> bool:
        return self.content_type == ContentType.TEXT

    @property
    def is_image(self) -> bool:
        return self.content_type == ContentType.IMAGE

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
    def from_db_row(cls, row: tuple) -> "ClipboardItem":
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
