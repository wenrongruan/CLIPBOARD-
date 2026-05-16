"""i18n 字符串包。

按领域拆分子文件,每个子文件导出 STRINGS = {lang_code: {key: value}}。
load_all() 合并所有子文件,返回最终的三层 dict:lang -> key -> value。

领域划分:
- main     主界面 / 通用 / 托盘 / 右键菜单
- settings 设置对话框 / 数据库 / 过滤存储
- cloud    云同步 / 登录 / 订阅 / 分享 (暂为占位)
- plugins  插件系统
- misc     其他 (剪贴板项 / 图片保存 / 数据迁移 / 关于)
"""

from i18n_strings import cloud, main, misc, plugins, settings


def load_all() -> dict:
    """合并所有领域文件的 STRINGS,返回 dict[lang][key] -> value。"""
    merged: dict = {}
    for module in (main, settings, cloud, plugins, misc):
        for lang, kv in module.STRINGS.items():
            merged.setdefault(lang, {}).update(kv)
    return merged
