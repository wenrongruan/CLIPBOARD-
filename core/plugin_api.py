"""
插件 API 定义模块

提供插件开发所需的所有基类和数据结构:
- PluginBase: 插件基类
- PluginAction: 插件操作定义
- PluginResult: 插件执行结果
- PluginResultAction: 结果处理方式
- PluginTestHelper: 测试辅助工具
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

from .models import ClipboardItem, ContentType


class PluginResultAction(Enum):
    """插件执行结果的处理方式"""
    COPY = "copy"        # 将结果复制到系统剪贴板
    SAVE = "save"        # 将结果保存为新的剪贴板条目
    REPLACE = "replace"  # 替换原有条目的内容


@dataclass
class PluginAction:
    """插件提供的单个操作"""
    action_id: str                        # 操作标识，如 "translate_en"
    label: str                            # 显示名称，如 "翻译为英文"
    icon: str                             # 单个 emoji 或文本图标，如 "🌐"
    supported_types: List[ContentType]    # 支持的内容类型列表


@dataclass
class PluginResult:
    """插件执行结果"""
    success: bool
    content_type: ContentType = ContentType.TEXT
    text_content: Optional[str] = None
    image_data: Optional[bytes] = None
    action: PluginResultAction = PluginResultAction.COPY
    error_message: Optional[str] = None
    cancelled: bool = False

    def __post_init__(self):
        if self.success and self.text_content is None and self.image_data is None:
            raise ValueError("PluginResult: success=True requires text_content or image_data")


class PluginBase(ABC):
    """插件基类 - 所有插件必须继承此类

    抽象方法（必须实现）:
        get_id, get_name, get_actions, execute

    可选覆盖:
        get_description, on_load, on_unload, on_config_changed

    框架注入（可直接使用）:
        logger, get_config
    """

    # ========== 抽象方法 ==========

    @abstractmethod
    def get_id(self) -> str:
        """返回插件唯一标识（必须与 manifest.json 中的 id 一致）"""

    @abstractmethod
    def get_name(self) -> str:
        """返回插件显示名称"""

    @abstractmethod
    def get_actions(self) -> List[PluginAction]:
        """返回插件提供的所有操作列表"""

    @abstractmethod
    def execute(
        self,
        action_id: str,
        item: ClipboardItem,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> PluginResult:
        """
        执行插件操作（在工作线程中调用）。

        参数:
            action_id: 要执行的操作标识
            item: 剪贴板条目（包含完整内容）
            progress_callback: 进度回调 (percent: 0-100, message: str)
            cancel_check: 取消检查函数，返回 True 表示用户已取消

        返回:
            PluginResult 包含执行结果

        注意:
            - 禁止直接操作 Qt 控件
            - 长时间操作应定期调用 cancel_check() 检查取消状态
            - 使用 progress_callback 报告进度
        """

    # ========== 可选覆盖 ==========

    def get_description(self) -> str:
        """返回插件简短描述"""
        return ""

    def on_load(self) -> None:
        """插件加载时调用 — 用于初始化"""
        pass

    def on_unload(self) -> None:
        """插件卸载时调用 — 用于清理资源"""
        pass

    def on_config_changed(self, config: dict) -> None:
        """配置变更时调用 — 用于响应设置变化"""
        pass

    # ========== 框架注入 ==========

    @property
    def logger(self) -> logging.Logger:
        """插件专属 logger（由框架自动注入）"""
        return getattr(self, '_logger', logging.getLogger('plugin.unknown'))

    def get_config(self) -> dict:
        """获取插件配置（由框架自动从 config.json 加载）"""
        return getattr(self, '_config', {})


class PluginTestHelper:
    """插件开发者测试工具"""

    @staticmethod
    def create_test_item(
        text: str = "Hello World",
        content_type: ContentType = ContentType.TEXT,
        image_data: Optional[bytes] = None,
    ) -> ClipboardItem:
        """创建测试用 ClipboardItem"""
        return ClipboardItem(
            id=1,
            content_type=content_type,
            text_content=text if content_type == ContentType.TEXT else None,
            image_data=image_data,
            content_hash="test_hash_000000000000000000000000",
            preview=text[:50] if text else "[test image]",
            device_id="test_device",
            device_name="Test Device",
        )

    @staticmethod
    def run_plugin(
        plugin: PluginBase,
        action_id: str,
        text: str = "Hello World",
    ) -> PluginResult:
        """快速执行插件并返回结果"""
        item = PluginTestHelper.create_test_item(text)
        return plugin.execute(action_id, item)
