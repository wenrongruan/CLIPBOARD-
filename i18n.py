"""i18n shim。

字符串数据按领域拆到 i18n_strings/ 包内,运行时由 load_all() 合并。
对外保持原有 t / set_language / get_language / get_languages 接口,
以及 TRANSLATIONS / SUPPORTED_LANGUAGES / I18n 三个模块级符号 (向后兼容)。

支持语言:zh_CN / en_US / ja_JP / ko_KR / es_ES / fr_FR / de_DE / ru_RU。
"""

import logging
from typing import Dict, Optional

from i18n_strings import load_all

logger = logging.getLogger(__name__)

# 支持的语言列表
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "zh_CN": "简体中文",
    "en_US": "English",
    "ja_JP": "日本語",
    "ko_KR": "한국어",
    "es_ES": "Español",
    "fr_FR": "Français",
    "de_DE": "Deutsch",
    "ru_RU": "Русский",
}

# 完整翻译字典 (由 i18n_strings 各领域文件合并而来)
TRANSLATIONS: Dict[str, Dict[str, str]] = load_all()


class I18n:
    """国际化管理类 (单例,保持原 API 兼容)。"""

    _current_language: str = "zh_CN"
    _instance: Optional["I18n"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def set_language(cls, language: str) -> bool:
        """设置当前语言。

        Returns:
            是否成功。非法语言（配置里残留旧代码值如 zh-CN / en）会回退
            zh_CN 并记日志 —— 旧实现静默忽略，用户表现为"选了没反应"。
        """
        if language in SUPPORTED_LANGUAGES:
            cls._current_language = language
            return True
        # 常见历史别名归一化（旧版本用 '-' 分隔 / 只有语言段）
        normalized = (language or "").replace("-", "_")
        if normalized in SUPPORTED_LANGUAGES:
            cls._current_language = normalized
            return True
        if normalized.split("_")[0] in {k.split("_")[0] for k in SUPPORTED_LANGUAGES}:
            candidates = [
                k for k in SUPPORTED_LANGUAGES
                if k.split("_")[0] == normalized.split("_")[0]
            ]
            cls._current_language = candidates[0]
            logger.warning(f"语言 '{language}' 未被支持，已回退到 '{candidates[0]}'")
            return True
        logger.warning(f"语言 '{language}' 未被支持，回退默认 zh_CN")
        cls._current_language = "zh_CN"
        return False

    @classmethod
    def get_language(cls) -> str:
        """获取当前语言。"""
        return cls._current_language

    @classmethod
    def get_languages(cls) -> Dict[str, str]:
        """获取所有支持的语言。"""
        return SUPPORTED_LANGUAGES.copy()

    @classmethod
    def t(cls, key: str, **kwargs) -> str:
        """获取翻译文本。当前语言找不到时回退到英语,仍找不到则返回 key。"""
        translations = TRANSLATIONS.get(cls._current_language, {})
        text = translations.get(key, key)
        if text == key and cls._current_language != "en_US":
            text = TRANSLATIONS.get("en_US", {}).get(key, key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass
        return text


# 便捷函数
def t(key: str, **kwargs) -> str:
    """翻译便捷函数。"""
    return I18n.t(key, **kwargs)


def set_language(language: str) -> bool:
    """设置语言便捷函数。返回是否成功。"""
    return I18n.set_language(language)


def get_language() -> str:
    """获取当前语言。"""
    return I18n.get_language()


def get_languages() -> Dict[str, str]:
    """获取所有支持的语言。"""
    return I18n.get_languages()
