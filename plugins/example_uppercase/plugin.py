from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ClipboardItem, TextClipboardItem, ContentType


class UppercasePlugin(PluginBase):
    def get_id(self):
        return "example_uppercase"

    def get_name(self):
        return "文本转大写"

    def get_actions(self):
        return [
            PluginAction(
                action_id="to_upper",
                label="转换为大写",
                icon="Aa",
                supported_types=[ContentType.TEXT],
            )
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        if action_id == "to_upper" and isinstance(item, TextClipboardItem) and item.text_content:
            if progress_callback:
                progress_callback(50, "转换中...")
            result_text = item.text_content.upper()
            if progress_callback:
                progress_callback(100, "完成")
            return PluginResult(
                success=True,
                content_type=ContentType.TEXT,
                text_content=result_text,
                action=PluginResultAction.COPY,
            )
        return PluginResult(success=False, error_message="无文本内容")
