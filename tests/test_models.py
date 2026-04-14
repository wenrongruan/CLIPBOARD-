"""ClipboardItem 数据模型测试（sealed union 类型设计）

ClipboardItem 现为抽象基类，不能直接实例化；
通过 TextClipboardItem / ImageClipboardItem 两个子类实例化。
"""

import sys
import os
import time

import pytest

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import (
    ClipboardItem,
    TextClipboardItem,
    ImageClipboardItem,
    ContentType,
)


class TestContentType:
    def test_text_value(self):
        assert ContentType.TEXT.value == "text"

    def test_image_value(self):
        assert ContentType.IMAGE.value == "image"

    def test_from_string(self):
        assert ContentType("text") == ContentType.TEXT
        assert ContentType("image") == ContentType.IMAGE


class TestClipboardItemAbstract:
    """基类不可直接实例化"""

    def test_abstract_base_raises(self):
        with pytest.raises(TypeError):
            ClipboardItem()


class TestTextClipboardItem:
    def test_default_creation(self):
        item = TextClipboardItem()
        assert item.id is None
        assert item.content_type == ContentType.TEXT
        assert item.text_content == ""
        assert item.is_starred is False
        assert item.cloud_id is None
        assert item.is_text is True
        assert item.is_image is False

    def test_text_item(self):
        item = TextClipboardItem(
            text_content="hello",
            content_hash="abc123",
        )
        assert item.is_text is True
        assert item.is_image is False
        assert item.get_display_preview() == "hello"

    def test_display_preview_truncation(self):
        long_text = "a" * 200
        item = TextClipboardItem(text_content=long_text)
        preview = item.get_display_preview(max_length=100)
        assert len(preview) == 103  # 100 + "..."
        assert preview.endswith("...")

    def test_display_preview_newlines(self):
        item = TextClipboardItem(text_content="line1\nline2\nline3")
        preview = item.get_display_preview()
        assert "\n" not in preview

    def test_to_db_tuple(self):
        item = TextClipboardItem(
            text_content="test",
            content_hash="hash123",
            preview="test",
            device_id="dev1",
            device_name="PC",
            created_at=1000,
            is_starred=True,
        )
        t = item.to_db_tuple()
        assert t[0] == "text"
        assert t[1] == "test"
        assert t[2] is None  # image_data
        assert t[3] is None  # image_thumbnail
        assert t[9] == 1  # is_starred as int

    def test_created_at_default(self):
        before = int(time.time() * 1000)
        item = TextClipboardItem()
        after = int(time.time() * 1000)
        assert before <= item.created_at <= after


class TestImageClipboardItem:
    def test_default_creation(self):
        item = ImageClipboardItem()
        assert item.id is None
        assert item.content_type == ContentType.IMAGE
        assert item.image_data is None
        assert item.image_thumbnail is None
        assert item.is_image is True
        assert item.is_text is False

    def test_image_item(self):
        item = ImageClipboardItem(
            image_data=b"\x89PNG\r\n",
            content_hash="img_hash",
        )
        assert item.is_image is True
        assert item.is_text is False
        assert item.get_display_preview() == "[图片]"

    def test_to_db_tuple(self):
        item = ImageClipboardItem(
            image_data=b"\x89PNG",
            image_thumbnail=b"thumb",
            content_hash="img_hash",
            preview="[图片]",
            device_id="dev1",
            device_name="PC",
            created_at=2000,
            is_starred=False,
        )
        t = item.to_db_tuple()
        assert t[0] == "image"
        assert t[1] is None  # text_content
        assert t[2] == b"\x89PNG"  # image_data
        assert t[3] == b"thumb"  # image_thumbnail
        assert t[9] == 0

    def test_image_has_no_text_content_attr(self):
        """ImageClipboardItem 不应拥有 text_content 属性"""
        item = ImageClipboardItem()
        assert not hasattr(item, "text_content")

    def test_text_has_no_image_data_attr(self):
        """TextClipboardItem 不应拥有 image_data 属性"""
        item = TextClipboardItem()
        assert not hasattr(item, "image_data")
        assert not hasattr(item, "image_thumbnail")


class TestCloudSynced:
    def test_cloud_synced_true(self):
        item = TextClipboardItem(cloud_id=42)
        assert item.is_cloud_synced is True

    def test_cloud_synced_false(self):
        item = TextClipboardItem(cloud_id=None)
        assert item.is_cloud_synced is False

    def test_image_cloud_synced(self):
        item = ImageClipboardItem(cloud_id=7)
        assert item.is_cloud_synced is True


class TestFromDbRow:
    def test_from_db_row_text(self):
        row = {
            "id": 1,
            "content_type": "text",
            "text_content": "hello",
            "image_data": None,
            "image_thumbnail": None,
            "content_hash": "abc",
            "preview": "hello",
            "device_id": "dev1",
            "device_name": "PC",
            "created_at": 1000,
            "is_starred": 1,
            "cloud_id": 5,
        }
        item = ClipboardItem.from_db_row(row)
        assert isinstance(item, TextClipboardItem)
        assert item.id == 1
        assert item.content_type == ContentType.TEXT
        assert item.text_content == "hello"
        assert item.is_starred is True
        assert item.cloud_id == 5

    def test_from_db_row_image(self):
        row = {
            "id": 2,
            "content_type": "image",
            "text_content": None,
            "image_data": b"\x89PNG",
            "image_thumbnail": b"thumb",
            "content_hash": "img_hash",
            "preview": "[图片]",
            "device_id": "dev2",
            "device_name": "Mac",
            "created_at": 2000,
            "is_starred": 0,
            "cloud_id": None,
        }
        item = ClipboardItem.from_db_row(row)
        assert isinstance(item, ImageClipboardItem)
        assert item.id == 2
        assert item.content_type == ContentType.IMAGE
        assert item.image_data == b"\x89PNG"
        assert item.image_thumbnail == b"thumb"
        assert item.is_starred is False
        assert item.cloud_id is None
