# CLAUDE.md

本文件只给仓库内的 agent 使用。

## 工作约定

- 始终使用中文和用户沟通。
- 只修改本仓库内需要修订的 Markdown 文档，避免碰无关文件。
- 不回退其他 agent 或主线程已经做出的改动。
- 以代码为准，文档只写当前实现，不写推测或过期愿景。

## 当前仓库事实

- 应用入口是 `main.py`。
- 配置与密钥处理集中在 `config.py` 和 `utils/secure_store.py`。
- 核心逻辑在 `core/`，UI 在 `ui/`，内置插件在 `plugins/`，测试在 `tests/`。
- 当前内置插件是 `smart_text` 和 `ai_image_gen`；App Store 构建（`IS_APPSTORE_BUILD`）仅打包 `smart_text`。
- `PluginManager` 会加载内置插件、用户插件和冻结包同级 `plugins/` 目录；App Store 模式下只信任内置插件。
- 插件配置文件位于 `<config_dir>/plugins/<plugin_id>/config.json`。
- `settings.json`、`clipboard.db` 和 `logs/` 都在系统配置目录下的 `SharedClipboard/` 子目录中。
- 文件云同步（付费功能）由 `core/file_sync_service.py` + `core/file_repository.py` + `core/file_storage.py` 实现，付费闸在 `core/entitlement_service.py`。

## 文档维护优先级

1. `README.md`
2. `PLUGIN_SYSTEM_DESIGN.md`
3. `PRODUCT_STRATEGY.md`
4. `TEST_REVIEW_REPORT_2026-04-17.md`

## 验证建议

- 文档改动完成后，至少检查 `git status`。
- 如果文档涉及测试结论，优先用 `pytest -q` 的实际结果更新。
