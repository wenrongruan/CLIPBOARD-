"""Plugin ExtensionPointRegistry —— 插件向 UI 暴露能力的扩展点边界。

当前仅承载右键菜单（context_menu_actions）。`search_providers` /
`inline_actions` 是为未来扩展点预留的占位入口，本阶段固定返回空列表。

设计要点：
- 仅在 PluginManager 完成 `on_load()` 后由其调用 `register_context_menu`，
  `unload_all` 时清理；UI 侧只读不写。
- `context_menu_actions(item)` 的返回结构与 `PluginManager.get_plugin_actions_grouped`
  完全一致，便于 UI 控制器无差别替换调用方。
- 当 `item is None` 时跳过 `content_type` 过滤，便于单元测试或上层希望获取
  插件全部动作的场景。
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from config import is_plugin_enabled

logger = logging.getLogger(__name__)


class ExtensionPointRegistry:
    """插件扩展点注册表。"""

    def __init__(self) -> None:
        # plugin_id -> {"plugin_name": str, "actions": list, "get_actions": Optional[Callable]}
        self._context_menu: Dict[str, dict] = {}

    # ========== context menu ==========

    def register_context_menu(
        self,
        plugin_id: str,
        plugin_name: str,
        actions: list,
        get_actions: Optional[Callable[[], list]] = None,
    ) -> None:
        """注册插件静态动作列表（或动态获取回调）。

        如果同时提供 `get_actions`，则 `context_menu_actions` 优先调用回调，
        以便插件运行时动态切换可用动作。
        """
        self._context_menu[plugin_id] = {
            "plugin_name": plugin_name,
            "actions": list(actions or []),
            "get_actions": get_actions,
        }

    def unregister_plugin(self, plugin_id: str) -> None:
        """移除某个插件的全部注册项。未注册时静默忽略。"""
        self._context_menu.pop(plugin_id, None)

    def context_menu_actions(self, item) -> List[dict]:
        """返回按插件分组、并按 `item.content_type` 过滤后的动作列表。

        返回结构: [{"plugin_id", "plugin_name", "actions": [PluginAction, ...]}, ...]
        - 当 `item is None` 时跳过 content_type 过滤；
        - 若某个插件没有任何匹配动作，则该分组整体不返回（避免 UI 渲染空子菜单）。
        - 与 PluginManager.get_plugin_actions_grouped 保持一致：尊重 is_plugin_enabled 开关。
        """
        groups: List[dict] = []
        content_type = getattr(item, "content_type", None) if item is not None else None

        for plugin_id, entry in self._context_menu.items():
            if not is_plugin_enabled(plugin_id):
                continue
            try:
                if entry["get_actions"] is not None:
                    raw_actions = entry["get_actions"]() or []
                else:
                    raw_actions = entry["actions"]
                if item is None or content_type is None:
                    matching = list(raw_actions)
                else:
                    matching = [
                        a for a in raw_actions
                        if content_type in getattr(a, "supported_types", [])
                    ]
                if matching:
                    groups.append({
                        "plugin_id": plugin_id,
                        "plugin_name": entry["plugin_name"],
                        "actions": matching,
                    })
            except Exception:
                logger.exception(f"Error enumerating context actions from {plugin_id}")
        return groups

    # ========== 占位扩展点（未来阶段填充） ==========

    def search_providers(self) -> list:
        """命令面板 / 搜索面板的 provider 列表（暂未启用）。"""
        return []

    def inline_actions(self) -> list:
        """条目内联动作列表（暂未启用）。"""
        return []
