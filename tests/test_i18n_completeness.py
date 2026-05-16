"""i18n 完整性测试。

确认 Phase 4 拆分前后,所有 (lang, key) 对完整存在,且 t() 返回非空字符串。
基线 keys 列表保存在 tests/_i18n_keys_baseline.json。
"""

import json
from pathlib import Path

import i18n


def _load_strings_dict():
    """查找 i18n 内部翻译 dict,适配 shim 改造前后的命名。"""
    for name in ("TRANSLATIONS", "_strings", "STRINGS", "_translations", "_all_strings"):
        d = getattr(i18n, name, None)
        if isinstance(d, dict) and d and isinstance(next(iter(d.values())), dict):
            return d
    raise AssertionError("Could not find i18n strings dict on the module")


def test_all_baseline_keys_present():
    """每个语言下的基线 keys 必须全部存在。"""
    baseline_path = Path(__file__).parent / "_i18n_keys_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    strings = _load_strings_dict()
    for lang, expected_keys in baseline.items():
        assert lang in strings, f"language missing: {lang}"
        actual = set(strings[lang].keys())
        expected = set(expected_keys)
        missing = expected - actual
        assert not missing, f"{lang} 缺失 keys: {sorted(missing)[:20]}"


def test_t_returns_string_for_each_key():
    """t() 对每个 key 返回非空字符串。"""
    strings = _load_strings_dict()
    original_lang = i18n.get_language()
    try:
        for lang in strings:
            i18n.set_language(lang)
            for key in strings[lang]:
                value = i18n.t(key)
                assert isinstance(value, str), f"{lang}/{key} returned non-str"
                assert value != "", f"{lang}/{key} returned empty"
    finally:
        i18n.set_language(original_lang)
