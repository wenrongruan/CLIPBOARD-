"""ClipboardItem 数据模型测试"""

import sys
import os
import time

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import ClipboardItem, ContentType


class TestContentType:
    def test_text_value(self):
        assert ContentType.TEXT.value == "text"

    def test_image_value(self):
        assert ContentType.IMAGE.value == "image"

    def test_from_string(self):
        assert ContentType("text") == ContentType.TEXT
        assert ContentType("image") == ContentType.IMAGE


class TestClipboardItem:
    def test_default_creation(self):
        item = ClipboardItem()
        assert item.id is None
        assert item.content_type == ContentType.TEXT
        assert item.text_content is None
        assert item.is_starred is False
        assert item.cloud_id is None

    def test_text_item(self):
        item = ClipboardItem(
            content_type=ContentType.TEXT,
            text_content="hello",
            content_hash="abc123",
        )
        assert item.is_text is True
        assert item.is_image is False
        assert item.get_display_preview() == "hello"

    def test_image_item(self):
        item = ClipboardItem(
            content_type=ContentType.IMAGE,
            image_data=b"\x89PNG\r\n",
            content_hash="img_hash",
        )
        assert item.is_image is True
        assert item.is_text is False
        assert item.get_display_preview() == "[图片]"

    def test_cloud_synced(self):
        item = ClipboardItem(cloud_id=42)
        assert item.is_cloud_synced is True

        item2 = ClipboardItem(cloud_id=None)
        assert item2.is_cloud_synced is False

    def test_display_preview_truncation(self):
        long_text = "a" * 200
        item = ClipboardItem(content_type=ContentType.TEXT, text_content=long_text)
        preview = item.get_display_preview(max_length=100)
        assert len(preview) == 103  # 100 + "..."
        assert preview.endswith("...")

    def test_display_preview_newlines(self):
        item = ClipboardItem(
            content_type=ContentType.TEXT,
            text_content="line1\nline2\nline3",
        )
        preview = item.get_display_preview()
        assert "\n" not in preview

    def test_to_db_tuple(self):
        item = ClipboardItem(
            content_type=ContentType.TEXT,
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
        assert t[9] == 1  # is_starred as int

    def test_from_db_row_dict(self):
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
        assert item.id == 1
        assert item.content_type == ContentType.TEXT
        assert item.text_content == "hello"
        assert item.is_starred is True
        assert item.cloud_id == 5

    def test_created_at_default(self):
        before = int(time.time() * 1000)
        item = ClipboardItem()
        after = int(time.time() * 1000)
        assert before <= item.created_at <= after
