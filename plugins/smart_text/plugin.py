"""
智能文本插件
提供文本格式转换、编码解码、JSON处理等实用工具
"""

import base64
import json
import re
import urllib.parse

from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ContentType, TextClipboardItem


class SmartTextPlugin(PluginBase):

    def get_id(self):
        return "smart_text"

    def get_name(self):
        return "智能文本"

    def get_description(self):
        return "文本格式转换、编码解码、JSON处理等实用工具集"

    def get_actions(self):
        T = ContentType.TEXT
        return [
            # ── 格式清理 ──
            PluginAction("clean_text", "清理格式", "🧹", [T]),
            # ── 大小写 ──
            PluginAction("to_upper", "转大写", "🔠", [T]),
            PluginAction("to_lower", "转小写", "🔡", [T]),
            PluginAction("to_title", "首字母大写", "Aa", [T]),
            # ── 命名风格 ──
            PluginAction("to_snake_case", "转 snake_case", "🐍", [T]),
            PluginAction("to_camel_case", "转 camelCase", "🐫", [T]),
            # ── 编码转换 ──
            PluginAction("url_encode", "URL 编码", "🔗", [T]),
            PluginAction("url_decode", "URL 解码", "🔓", [T]),
            PluginAction("base64_encode", "Base64 编码", "📦", [T]),
            PluginAction("base64_decode", "Base64 解码", "📭", [T]),
            # ── JSON ──
            PluginAction("json_format", "JSON 格式化", "📋", [T]),
            PluginAction("json_compact", "JSON 压缩", "📎", [T]),
            # ── 行处理 ──
            PluginAction("dedup_lines", "去除重复行", "✂️", [T]),
            PluginAction("sort_lines", "按行排序", "📊", [T]),
            # ── 统计 ──
            PluginAction("text_stats", "文本统计", "📏", [T]),
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        if not isinstance(item, TextClipboardItem) or not item.text_content:
            return PluginResult(success=False, error_message="无文本内容")

        text = item.text_content
        handlers = {
            "clean_text": self._clean_text,
            "to_upper": self._to_upper,
            "to_lower": self._to_lower,
            "to_title": self._to_title,
            "to_snake_case": self._to_snake_case,
            "to_camel_case": self._to_camel_case,
            "url_encode": self._url_encode,
            "url_decode": self._url_decode,
            "base64_encode": self._base64_encode,
            "base64_decode": self._base64_decode,
            "json_format": self._json_format,
            "json_compact": self._json_compact,
            "dedup_lines": self._dedup_lines,
            "sort_lines": self._sort_lines,
            "text_stats": self._text_stats,
        }

        handler = handlers.get(action_id)
        if not handler:
            return PluginResult(success=False, error_message="未知操作")

        if progress_callback:
            progress_callback(50, "处理中...")

        try:
            result_text = handler(text)
        except Exception as e:
            self.logger.exception("执行 %s 失败", action_id)
            return PluginResult(success=False, error_message=f"处理失败: {e}")

        if progress_callback:
            progress_callback(100, "完成")

        return PluginResult(
            success=True,
            content_type=ContentType.TEXT,
            text_content=result_text,
            action=PluginResultAction.COPY,
        )

    # ── 格式清理 ──────────────────────────────────────────────

    @staticmethod
    def _clean_text(text):
        """去除每行尾部空白，合并连续空行，去除首尾空行"""
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned = []
        prev_blank = False
        for line in lines:
            is_blank = not line
            if is_blank and prev_blank:
                continue
            cleaned.append(line)
            prev_blank = is_blank
        return "\n".join(cleaned).strip()

    # ── 大小写 ────────────────────────────────────────────────

    @staticmethod
    def _to_upper(text):
        return text.upper()

    @staticmethod
    def _to_lower(text):
        return text.lower()

    @staticmethod
    def _to_title(text):
        return text.title()

    # ── 命名风格转换 ──────────────────────────────────────────

    @staticmethod
    def _to_snake_case(text):
        """camelCase / PascalCase / kebab-case / 空格分隔 → snake_case"""
        s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
        s = re.sub(r"[\s\-]+", "_", s)
        # 合并连续下划线
        s = re.sub(r"_+", "_", s)
        return s.lower().strip("_")

    @staticmethod
    def _to_camel_case(text):
        """snake_case / kebab-case / 空格分隔 → camelCase"""
        words = re.split(r"[_\-\s]+", text.strip())
        if not words:
            return text
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])

    # ── 编码转换 ──────────────────────────────────────────────

    @staticmethod
    def _url_encode(text):
        return urllib.parse.quote(text, safe="")

    @staticmethod
    def _url_decode(text):
        return urllib.parse.unquote(text)

    @staticmethod
    def _base64_encode(text):
        return base64.b64encode(text.encode("utf-8")).decode("ascii")

    @staticmethod
    def _base64_decode(text):
        raw = text.strip()
        decoded = base64.b64decode(raw)
        try:
            return decoded.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("解码结果不是有效的 UTF-8 文本，可能是二进制数据")

    # ── JSON ──────────────────────────────────────────────────

    @staticmethod
    def _json_format(text):
        """格式化 JSON（美化缩进）"""
        obj = json.loads(text.strip())
        return json.dumps(obj, indent=2, ensure_ascii=False)

    @staticmethod
    def _json_compact(text):
        """压缩 JSON（去除空白）"""
        obj = json.loads(text.strip())
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    # ── 行处理 ────────────────────────────────────────────────

    @staticmethod
    def _dedup_lines(text):
        """去除重复行（保持首次出现的顺序）"""
        seen = set()
        result = []
        for line in text.splitlines():
            if line not in seen:
                seen.add(line)
                result.append(line)
        return "\n".join(result)

    @staticmethod
    def _sort_lines(text):
        """按行排序（字典序）"""
        return "\n".join(sorted(text.splitlines()))

    # ── 统计 ──────────────────────────────────────────────────

    @staticmethod
    def _text_stats(text):
        """统计字符数、单词数、行数、中文字符数"""
        chars = len(text)
        chars_no_space = len(re.sub(r"\s", "", text))
        words = len(text.split())
        lines = len(text.splitlines()) or 1
        chinese = len(re.findall(r"[\u4e00-\u9fff]", text))

        parts = [
            f"字符数: {chars}",
            f"字符数(不含空白): {chars_no_space}",
            f"单词/词数: {words}",
            f"行数: {lines}",
        ]
        if chinese:
            parts.append(f"中文字符: {chinese}")
        return "\n".join(parts)
