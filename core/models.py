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
    # v3.4: 空间 / 来源 App / 标签
    # space_id: None 表示个人空间；非 None 为 UUID
    space_id: Optional[str] = None
    # source_app: 来源 App bundle id / exe 名
    source_app: str = ""
    # source_title: 窗口标题（隐私考虑默认不捕获，但字段保留）
    source_title: str = ""
    # tag_ids: 冗余展示字段；权威数据在 clipboard_tags 关联表
    # 由 Repository 在 SELECT 时 JOIN 填充，to_db_tuple 不包含它
    tag_ids: list = field(default_factory=list)

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
        # v3.4: 末尾追加 space_id / source_app / source_title（不含 tag_ids）
        return (
            self.content_type.value,
            *self._payload_db_fields(),
            self.content_hash,
            self.preview,
            self.device_id,
            self.device_name,
            self.created_at,
            int(self.is_starred),
            self.space_id,
            self.source_app,
            self.source_title,
        )

    @classmethod
    def from_db_row(cls, row) -> "ClipboardItem":
        """按 content_type 分派到具体子类。

        SQLite 的 sqlite3.Row 与 PyMySQL 的 DictCursor 都支持键下标访问。
        Repository._SELECT_FIELDS 统一包含全部列。
        """
        ct = ContentType(row["content_type"])

        # sqlite3.Row 不支持 .get()，用 try/except KeyError 兼容老库
        def _row_get(key, default=None):
            try:
                val = row[key]
            except (KeyError, IndexError):
                return default
            return val if val is not None else default

        common = dict(
            id=row["id"],
            content_hash=row["content_hash"] or "",
            preview=row["preview"] or "",
            device_id=row["device_id"] or "",
            device_name=row["device_name"] or "",
            created_at=row["created_at"] or 0,
            is_starred=bool(row["is_starred"]),
            cloud_id=row["cloud_id"],
            # v3.4 新字段，老库没有这些列时回落默认值
            space_id=_row_get("space_id", None),
            source_app=_row_get("source_app", "") or "",
            source_title=_row_get("source_title", "") or "",
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
