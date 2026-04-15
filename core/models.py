"""剪贴板条目数据模型。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional, Union
import logging
import time

logger = logging.getLogger(__name__)


class ContentType(Enum):
    TEXT = "text"
    IMAGE = "image"


@dataclass
class ClipboardItem:
    """剪贴板条目抽象基类。不要直接实例化,使用子类。"""

    content_type: ClassVar[ContentType]  # 子类必须覆盖

    id: Optional[int] = None
    content_hash: str = ""
    preview: str = ""
    device_id: str = ""
    device_name: str = ""
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    is_starred: bool = False
    cloud_id: Optional[int] = None

    def __post_init__(self):
        if type(self) is ClipboardItem:
            raise TypeError(
                "ClipboardItem 是抽象基类,请使用 TextClipboardItem 或 ImageClipboardItem"
            )
        if self.id is not None and not self.content_hash:
            logger.warning(f"ClipboardItem(id={self.id}) 的 content_hash 为空")

    @property
    def is_text(self) -> bool:
        return isinstance(self, TextClipboardItem)

    @property
    def is_image(self) -> bool:
        return isinstance(self, ImageClipboardItem)

    @property
    def is_cloud_synced(self) -> bool:
        return self.cloud_id is not None

    def get_display_preview(self, max_length: int = 100) -> str:
        raise NotImplementedError

    def _payload_db_fields(self) -> tuple:
        """子类返回 (text_content, image_data, image_thumbnail)。"""
        raise NotImplementedError

    def to_db_tuple(self) -> tuple:
        return (
            self.content_type.value,
            *self._payload_db_fields(),
            self.content_hash,
            self.preview,
            self.device_id,
            self.device_name,
            self.created_at,
            int(self.is_starred),
        )

    @classmethod
    def from_db_row(cls, row) -> "ClipboardItem":
        """按 content_type 分派到具体子类。

        SQLite 的 sqlite3.Row 与 PyMySQL 的 DictCursor 都支持键下标访问。
        Repository._SELECT_FIELDS 统一包含全部列。
        """
        ct = ContentType(row["content_type"])
        common = dict(
            id=row["id"],
            content_hash=row["content_hash"] or "",
            preview=row["preview"] or "",
            device_id=row["device_id"] or "",
            device_name=row["device_name"] or "",
            created_at=row["created_at"] or 0,
            is_starred=bool(row["is_starred"]),
            cloud_id=row["cloud_id"],
        )
        if ct == ContentType.TEXT:
            return TextClipboardItem(**common, text_content=row["text_content"] or "")
        return ImageClipboardItem(
            **common,
            image_data=row["image_data"],
            image_thumbnail=row["image_thumbnail"],
        )


@dataclass
class TextClipboardItem(ClipboardItem):
    content_type: ClassVar[ContentType] = ContentType.TEXT

    text_content: str = ""

    def get_display_preview(self, max_length: int = 100) -> str:
        text = (self.text_content or "").replace("\n", " ").strip()
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    def _payload_db_fields(self) -> tuple:
        return (self.text_content, None, None)


@dataclass
class ImageClipboardItem(ClipboardItem):
    content_type: ClassVar[ContentType] = ContentType.IMAGE

    image_data: Optional[bytes] = None
    image_thumbnail: Optional[bytes] = None

    def get_display_preview(self, max_length: int = 100) -> str:
        return "[图片]"

    def _payload_db_fields(self) -> tuple:
        return (None, self.image_data, self.image_thumbnail)


AnyClipboardItem = Union[TextClipboardItem, ImageClipboardItem]
