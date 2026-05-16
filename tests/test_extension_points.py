"""ExtensionPointRegistry 单元测试（Phase 7）。"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.plugin_extension_points import ExtensionPointRegistry


@dataclass
class FakeAction:
    action_id: str
    label: str
    supported_types: List[str] = field(default_factory=list)


@dataclass
class FakeItem:
    content_type: str


def test_register_and_enumerate_context_menu():
    reg = ExtensionPointRegistry()
    reg.register_context_menu("plugin_a", "Plugin A", [FakeAction("a1", "Do A")])
    reg.register_context_menu("plugin_b", "Plugin B", [FakeAction("b1", "Do B")])

    groups = reg.context_menu_actions(item=None)
    ids = [g["plugin_id"] for g in groups]
    assert "plugin_a" in ids
    assert "plugin_b" in ids

    by_id = {g["plugin_id"]: g for g in groups}
    assert by_id["plugin_a"]["plugin_name"] == "Plugin A"
    assert by_id["plugin_a"]["actions"][0].action_id == "a1"
    assert by_id["plugin_b"]["plugin_name"] == "Plugin B"
    assert by_id["plugin_b"]["actions"][0].action_id == "b1"


def test_unregister_plugin_clears_actions():
    reg = ExtensionPointRegistry()
    reg.register_context_menu("plugin_a", "Plugin A", [FakeAction("a1", "Do A")])
    reg.unregister_plugin("plugin_a")

    assert reg.context_menu_actions(item=None) == []
    # 再次取消注册不应抛错
    reg.unregister_plugin("plugin_a")


def test_per_plugin_isolation():
    reg = ExtensionPointRegistry()
    reg.register_context_menu("plugin_a", "Plugin A", [FakeAction("a1", "Do A")])
    reg.register_context_menu("plugin_b", "Plugin B", [FakeAction("b1", "Do B")])
    reg.unregister_plugin("plugin_a")

    groups = reg.context_menu_actions(item=None)
    assert len(groups) == 1
    assert groups[0]["plugin_id"] == "plugin_b"


def test_content_type_filter():
    """register 一个仅支持 text 的动作；当 item 是 image 时该分组整体不返回。"""
    reg = ExtensionPointRegistry()
    reg.register_context_menu(
        "plugin_text_only",
        "TextOnly",
        [FakeAction("t1", "Translate", supported_types=["text"])],
    )

    # 不匹配：image 类型 → 分组被丢弃（不渲染空子菜单）。
    image_item = FakeItem(content_type="image")
    assert reg.context_menu_actions(image_item) == []

    # 匹配：text 类型 → 分组返回。
    text_item = FakeItem(content_type="text")
    groups = reg.context_menu_actions(text_item)
    assert len(groups) == 1
    assert groups[0]["plugin_id"] == "plugin_text_only"
    assert groups[0]["actions"][0].action_id == "t1"


def test_search_providers_and_inline_actions_empty_by_default():
    reg = ExtensionPointRegistry()
    reg.register_context_menu("plugin_a", "Plugin A", [FakeAction("a1", "Do A")])

    assert reg.search_providers() == []
    assert reg.inline_actions() == []
