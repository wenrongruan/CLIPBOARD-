"""
多语言支持模块 (Internationalization)
支持的语言: 中文、英文、日语、韩语、西班牙语、法语、德语、俄语
"""

from typing import Dict, Optional

# 支持的语言列表
SUPPORTED_LANGUAGES = {
    "zh_CN": "简体中文",
    "en_US": "English",
    "ja_JP": "日本語",
    "ko_KR": "한국어",
    "es_ES": "Español",
    "fr_FR": "Français",
    "de_DE": "Deutsch",
    "ru_RU": "Русский",
}

# 翻译字典
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # ========== 简体中文 ==========
    "zh_CN": {
        # 通用
        "app_name": "共享剪贴板",
        "settings": "设置",
        "ok": "确定",
        "cancel": "取消",
        "yes": "是",
        "no": "否",
        "confirm": "确认",
        "error": "错误",
        "warning": "警告",
        "info": "信息",
        "success": "成功",

        # 主窗口
        "search_placeholder": "搜索剪贴板...",
        "pin_window": "固定窗口",
        "unpin_window": "取消固定",
        "minimize": "最小化",
        "quit_app": "退出应用",
        "prev_page": "◀ 上一页",
        "next_page": "下一页 ▶",
        "page_info": "{current} / {total}",

        # 设置对话框
        "general": "通用",
        "database": "数据库",
        "dock_position": "停靠位置:",
        "dock_right": "右侧",
        "dock_left": "左侧",
        "dock_top": "顶部",
        "dock_bottom": "底部",
        "global_hotkey": "全局热键:",
        "hotkey_placeholder": "例如: <cmd>+v",
        "hotkey_help": "热键格式说明:\n• <cmd> = Win键(Windows) / Cmd键(macOS)\n• <ctrl> = Ctrl键\n• <alt> = Alt键\n• <shift> = Shift键\n• 示例: <cmd>+v, <ctrl>+<shift>+c",
        "language": "语言:",

        # 数据库设置
        "db_type": "数据库类型:",
        "db_sqlite": "SQLite (本地文件)",
        "db_mysql": "MySQL (网络数据库)",
        "sqlite_config": "SQLite 配置",
        "mysql_config": "MySQL 配置",
        "db_path": "数据库路径:",
        "path_placeholder": "输入路径或点击浏览...",
        "browse": "浏览...",
        "select_db_file": "选择数据库文件位置",
        "host": "主机:",
        "port": "端口:",
        "username": "用户名:",
        "password": "密码:",
        "db_name": "数据库名:",
        "test_connection": "测试连接",
        "connection_success": "连接成功",
        "connection_failed": "连接失败",
        "missing_dependency": "缺少依赖",
        "pymysql_required": "pymysql 未安装，请运行:\npip install pymysql",
        "save_anyway": "{message}\n\n是否仍要保存设置？",

        # 剪贴板项
        "confirm_delete": "确认删除",
        "delete_confirm_msg": "确定要删除这条记录吗？",
        "image": "[图片]",
        "from_device": "来自: {device}",

        # 图片保存
        "save_image": "保存图片",
        "image_load_failed": "无法加载图片数据",
        "save_failed": "保存失败: {error}",

        # 数据迁移
        "migrate_data": "迁移数据",
        "migrate_data_confirm": "是否将现有数据迁移到新数据库？",
        "migrating": "正在迁移数据...",
        "migration_complete": "数据迁移完成，共迁移 {count} 条记录。",
        "migration_failed": "数据迁移失败: {error}",

        # 数据库配置文件
        "db_profile": "数据库配置:",
        "add_profile": "添加",
        "delete_profile": "删除",
        "profile_name": "配置名称",
        "enter_profile_name": "请输入新配置名称:",
        "profile_exists": "配置名称已存在",
        "cannot_delete_active": "不能删除当前使用的配置",
        "confirm_delete_profile": "确定要删除配置 \"{name}\" 吗？",

        # 提示消息
        "need_restart": "需要重启",
        "restart_msg": "设置已更改，请重启应用程序以生效。",

        # 过滤与存储
        "filter_storage": "过滤与存储",
        "content_filter": "内容过滤",
        "save_text": "保存文本",
        "save_images": "保存图片",
        "max_text_length": "最大文本长度:",
        "max_image_size": "最大图片大小:",
        "unlimited": "不限",
        "characters": "字符",
        "storage_management": "存储管理",
        "max_items": "最大条目数:",
        "retention_days": "自动清理天数:",
        "never_cleanup": "永不清理",
        "days": "天",
        "poll_interval": "轮询间隔:",

        # 托盘菜单
        "show_window": "显示窗口",
        "quit": "退出",

        # 复制反馈
        "copied_to_clipboard": "已复制到剪贴板 ✓",
        "copy_failed": "复制失败",

        # 收藏筛选
        "show_starred_only": "只看收藏",

        # 关于
        "about": "关于",
        "about_description": "一款跨设备剪贴板历史管理与同步工具",
        "official_website": "官方网站:",
        "github_repo": "GitHub 仓库:",
        "download_page": "软件下载:",

        # 插件系统
        "plugins": "插件",
        "installed_plugins": "已安装插件",
        "open_plugins_dir": "打开插件目录",
        "reload_plugins": "重新加载",
        "view_plugin_logs": "查看日志",
        "plugin_dev_docs": "开发文档",
        "plugin_settings": "设置",
        "plugin_enabled": "已启用",
        "plugin_disabled": "已禁用",
        "plugin_missing_deps": "缺少依赖: {deps}",
        "plugin_incompatible": "版本不兼容",
        "plugin_error": "加载失败",
        "plugin_executing": "{name} 执行中... {percent}%",
        "plugin_timeout": "插件执行超时",
        "plugin_busy": "有插件正在执行，请等待完成",
        "plugin_not_loaded": "插件未加载: {id}",
        "plugin_exec_failed": "执行失败",
        "plugin_config_title": "{name} - 设置",
        "plugin_config_required": "请填写必填项",
        "plugin_save": "保存",
        "plugin_cancel": "取消",
        "plugin_saved_entry": "已保存为新条目",
        "plugin_replaced_entry": "已替换原内容",
        "plugin_perm_network": "网络访问",
        "plugin_perm_file_read": "读取文件",
        "plugin_perm_file_write": "写入文件",
        "plugin_store": "插件商店",
        "plugin_install": "安装",
        "plugin_uninstall": "卸载",
        "plugin_installing": "安装中...",
        "plugin_installed_tag": "已安装",
        "plugin_install_failed": "安装失败",
        "plugin_uninstall_confirm_title": "确认卸载",
        "plugin_uninstall_confirm": "确定要卸载插件「{name}」吗？",
        "plugin_uninstall_failed": "卸载失败",
        "plugin_store_loading": "正在加载插件列表...",
        "plugin_store_empty": "暂无可用插件",
        "plugin_store_error": "获取插件列表失败",
        "plugin_no_installed": "暂无已安装插件",
        "refresh": "刷新",
        "ctx_copy": "复制",
        "ctx_star": "收藏",
        "ctx_unstar": "取消收藏",
        "ctx_delete": "删除",
    },

    # ========== English ==========
    "en_US": {
        # General
        "app_name": "Shared Clipboard",
        "settings": "Settings",
        "ok": "OK",
        "cancel": "Cancel",
        "yes": "Yes",
        "no": "No",
        "confirm": "Confirm",
        "error": "Error",
        "warning": "Warning",
        "info": "Information",
        "success": "Success",

        # Main window
        "search_placeholder": "Search clipboard...",
        "pin_window": "Pin window",
        "unpin_window": "Unpin window",
        "minimize": "Minimize",
        "quit_app": "Quit",
        "prev_page": "◀ Previous",
        "next_page": "Next ▶",
        "page_info": "{current} / {total}",

        # Settings dialog
        "general": "General",
        "database": "Database",
        "dock_position": "Dock position:",
        "dock_right": "Right",
        "dock_left": "Left",
        "dock_top": "Top",
        "dock_bottom": "Bottom",
        "global_hotkey": "Global hotkey:",
        "hotkey_placeholder": "e.g.: <cmd>+v",
        "hotkey_help": "Hotkey format:\n• <cmd> = Win key (Windows) / Cmd key (macOS)\n• <ctrl> = Ctrl key\n• <alt> = Alt key\n• <shift> = Shift key\n• Examples: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Language:",

        # Database settings
        "db_type": "Database type:",
        "db_sqlite": "SQLite (Local file)",
        "db_mysql": "MySQL (Network database)",
        "sqlite_config": "SQLite Configuration",
        "mysql_config": "MySQL Configuration",
        "db_path": "Database path:",
        "path_placeholder": "Enter path or click Browse...",
        "browse": "Browse...",
        "select_db_file": "Select database file location",
        "host": "Host:",
        "port": "Port:",
        "username": "Username:",
        "password": "Password:",
        "db_name": "Database name:",
        "test_connection": "Test Connection",
        "connection_success": "Connection Successful",
        "connection_failed": "Connection Failed",
        "missing_dependency": "Missing Dependency",
        "pymysql_required": "pymysql is not installed. Please run:\npip install pymysql",
        "save_anyway": "{message}\n\nSave settings anyway?",

        # Clipboard items
        "confirm_delete": "Confirm Delete",
        "delete_confirm_msg": "Are you sure you want to delete this item?",
        "image": "[Image]",
        "from_device": "From: {device}",

        # Image save
        "save_image": "Save Image",
        "image_load_failed": "Failed to load image data",
        "save_failed": "Save failed: {error}",

        # Data migration
        "migrate_data": "Migrate Data",
        "migrate_data_confirm": "Migrate existing data to the new database?",
        "migrating": "Migrating data...",
        "migration_complete": "Migration complete. {count} items migrated.",
        "migration_failed": "Migration failed: {error}",

        # Database profiles
        "db_profile": "Database profile:",
        "add_profile": "Add",
        "delete_profile": "Delete",
        "profile_name": "Profile name",
        "enter_profile_name": "Enter new profile name:",
        "profile_exists": "Profile name already exists",
        "cannot_delete_active": "Cannot delete the active profile",
        "confirm_delete_profile": "Delete profile \"{name}\"?",

        # Messages
        "need_restart": "Restart Required",
        "restart_msg": "Settings have changed. Please restart the application for changes to take effect.",

        # Filter & Storage
        "filter_storage": "Filter & Storage",
        "content_filter": "Content Filter",
        "save_text": "Save text",
        "save_images": "Save images",
        "max_text_length": "Max text length:",
        "max_image_size": "Max image size:",
        "unlimited": "Unlimited",
        "characters": "chars",
        "storage_management": "Storage Management",
        "max_items": "Max items:",
        "retention_days": "Auto-cleanup days:",
        "never_cleanup": "Never",
        "days": "days",
        "poll_interval": "Poll interval:",

        # Tray menu
        "show_window": "Show Window",
        "quit": "Quit",

        # Copy feedback
        "copied_to_clipboard": "Copied to clipboard ✓",
        "copy_failed": "Copy failed",

        # Star filter
        "show_starred_only": "Starred only",

        # About
        "about": "About",
        "about_description": "A cross-device clipboard history management and sync tool",
        "official_website": "Official Website:",
        "github_repo": "GitHub Repository:",
        "download_page": "Download:",

        # Plugin system
        "plugins": "Plugins",
        "installed_plugins": "Installed Plugins",
        "open_plugins_dir": "Open Plugins Folder",
        "reload_plugins": "Reload",
        "view_plugin_logs": "View Logs",
        "plugin_dev_docs": "Dev Docs",
        "plugin_settings": "Settings",
        "plugin_enabled": "Enabled",
        "plugin_disabled": "Disabled",
        "plugin_missing_deps": "Missing dependencies: {deps}",
        "plugin_incompatible": "Incompatible version",
        "plugin_error": "Load failed",
        "plugin_executing": "{name} running... {percent}%",
        "plugin_timeout": "Plugin execution timed out",
        "plugin_busy": "A plugin is already running, please wait",
        "plugin_not_loaded": "Plugin not loaded: {id}",
        "plugin_exec_failed": "Execution failed",
        "plugin_config_title": "{name} - Settings",
        "plugin_config_required": "Please fill in required fields",
        "plugin_save": "Save",
        "plugin_cancel": "Cancel",
        "plugin_saved_entry": "Saved as new entry",
        "plugin_replaced_entry": "Content replaced",
        "plugin_perm_network": "Network access",
        "plugin_perm_file_read": "File read",
        "plugin_perm_file_write": "File write",
        "plugin_store": "Plugin Store",
        "plugin_install": "Install",
        "plugin_uninstall": "Uninstall",
        "plugin_installing": "Installing...",
        "plugin_installed_tag": "Installed",
        "plugin_install_failed": "Installation Failed",
        "plugin_uninstall_confirm_title": "Confirm Uninstall",
        "plugin_uninstall_confirm": "Are you sure you want to uninstall \"{name}\"?",
        "plugin_uninstall_failed": "Uninstall failed",
        "plugin_store_loading": "Loading plugin list...",
        "plugin_store_empty": "No plugins available",
        "plugin_store_error": "Failed to load plugin list",
        "plugin_no_installed": "No plugins installed",
        "refresh": "Refresh",
        "ctx_copy": "Copy",
        "ctx_star": "Star",
        "ctx_unstar": "Unstar",
        "ctx_delete": "Delete",
    },

    # ========== 日本語 ==========
    "ja_JP": {
        # 一般
        "app_name": "共有クリップボード",
        "settings": "設定",
        "ok": "OK",
        "cancel": "キャンセル",
        "yes": "はい",
        "no": "いいえ",
        "confirm": "確認",
        "error": "エラー",
        "warning": "警告",
        "info": "情報",
        "success": "成功",

        # メインウィンドウ
        "search_placeholder": "クリップボードを検索...",
        "pin_window": "ウィンドウを固定",
        "unpin_window": "固定を解除",
        "minimize": "最小化",
        "quit_app": "終了",
        "prev_page": "◀ 前へ",
        "next_page": "次へ ▶",
        "page_info": "{current} / {total}",

        # 設定ダイアログ
        "general": "一般",
        "database": "データベース",
        "dock_position": "ドック位置:",
        "dock_right": "右",
        "dock_left": "左",
        "dock_top": "上",
        "dock_bottom": "下",
        "global_hotkey": "グローバルホットキー:",
        "hotkey_placeholder": "例: <cmd>+v",
        "hotkey_help": "ホットキーの形式:\n• <cmd> = Winキー(Windows) / Cmdキー(macOS)\n• <ctrl> = Ctrlキー\n• <alt> = Altキー\n• <shift> = Shiftキー\n• 例: <cmd>+v, <ctrl>+<shift>+c",
        "language": "言語:",

        # データベース設定
        "db_type": "データベースタイプ:",
        "db_sqlite": "SQLite (ローカルファイル)",
        "db_mysql": "MySQL (ネットワークデータベース)",
        "sqlite_config": "SQLite 設定",
        "mysql_config": "MySQL 設定",
        "db_path": "データベースパス:",
        "path_placeholder": "パスを入力または参照...",
        "browse": "参照...",
        "select_db_file": "データベースファイルの場所を選択",
        "host": "ホスト:",
        "port": "ポート:",
        "username": "ユーザー名:",
        "password": "パスワード:",
        "db_name": "データベース名:",
        "test_connection": "接続テスト",
        "connection_success": "接続成功",
        "connection_failed": "接続失敗",
        "missing_dependency": "依存関係が不足",
        "pymysql_required": "pymysqlがインストールされていません。\n実行してください: pip install pymysql",
        "save_anyway": "{message}\n\n設定を保存しますか？",

        # クリップボードアイテム
        "confirm_delete": "削除の確認",
        "delete_confirm_msg": "このアイテムを削除してもよろしいですか？",
        "image": "[画像]",
        "from_device": "送信元: {device}",

        # 画像保存
        "save_image": "画像を保存",
        "image_load_failed": "画像データの読み込みに失敗しました",
        "save_failed": "保存に失敗しました: {error}",

        # データ移行
        "migrate_data": "データ移行",
        "migrate_data_confirm": "既存のデータを新しいデータベースに移行しますか？",
        "migrating": "データを移行中...",
        "migration_complete": "移行完了。{count} 件のアイテムを移行しました。",
        "migration_failed": "移行に失敗しました: {error}",

        # データベースプロファイル
        "db_profile": "データベースプロファイル:",
        "add_profile": "追加",
        "delete_profile": "削除",
        "profile_name": "プロファイル名",
        "enter_profile_name": "新しいプロファイル名を入力してください:",
        "profile_exists": "プロファイル名は既に存在します",
        "cannot_delete_active": "使用中のプロファイルは削除できません",
        "confirm_delete_profile": "プロファイル \"{name}\" を削除しますか？",

        # メッセージ
        "need_restart": "再起動が必要",
        "restart_msg": "設定が変更されました。変更を反映するにはアプリケーションを再起動してください。",

        # フィルタとストレージ
        "filter_storage": "フィルタとストレージ",
        "content_filter": "コンテンツフィルタ",
        "save_text": "テキストを保存",
        "save_images": "画像を保存",
        "max_text_length": "最大テキスト長:",
        "max_image_size": "最大画像サイズ:",
        "unlimited": "無制限",
        "characters": "文字",
        "storage_management": "ストレージ管理",
        "max_items": "最大アイテム数:",
        "retention_days": "自動クリーンアップ日数:",
        "never_cleanup": "クリーンアップしない",
        "days": "日",
        "poll_interval": "ポーリング間隔:",

        # トレイメニュー
        "show_window": "ウィンドウを表示",
        "quit": "終了",

        # コピーフィードバック
        "copied_to_clipboard": "クリップボードにコピーしました ✓",
        "copy_failed": "コピーに失敗しました",

        # スターフィルター
        "show_starred_only": "スター付きのみ",

        # アバウト
        "about": "について",
        "about_description": "クロスデバイスのクリップボード履歴管理と同期ツール",
        "official_website": "公式サイト:",
        "github_repo": "GitHub リポジトリ:",
        "download_page": "ダウンロード:",

        # プラグインシステム
        "plugins": "プラグイン",
        "installed_plugins": "インストール済みプラグイン",
        "open_plugins_dir": "プラグインフォルダを開く",
        "reload_plugins": "再読み込み",
        "view_plugin_logs": "ログを見る",
        "plugin_dev_docs": "開発ドキュメント",
        "plugin_settings": "設定",
        "plugin_enabled": "有効",
        "plugin_disabled": "無効",
        "plugin_missing_deps": "依存関係不足: {deps}",
        "plugin_incompatible": "バージョン非互換",
        "plugin_error": "読み込み失敗",
        "plugin_executing": "{name} 実行中... {percent}%",
        "plugin_timeout": "プラグインがタイムアウトしました",
        "plugin_busy": "プラグインが実行中です。お待ちください",
        "plugin_not_loaded": "プラグインが読み込まれていません: {id}",
        "plugin_exec_failed": "実行に失敗しました",
        "plugin_config_title": "{name} - 設定",
        "plugin_config_required": "必須項目を入力してください",
        "plugin_save": "保存",
        "plugin_cancel": "キャンセル",
        "plugin_saved_entry": "新しいエントリとして保存しました",
        "plugin_replaced_entry": "内容を置換しました",
        "plugin_perm_network": "ネットワークアクセス",
        "plugin_perm_file_read": "ファイル読み取り",
        "plugin_perm_file_write": "ファイル書き込み",
        "plugin_store": "プラグインストア",
        "plugin_install": "インストール",
        "plugin_uninstall": "アンインストール",
        "plugin_installing": "インストール中...",
        "plugin_installed_tag": "インストール済み",
        "plugin_install_failed": "インストール失敗",
        "plugin_uninstall_confirm_title": "アンインストールの確認",
        "plugin_uninstall_confirm": "プラグイン「{name}」をアンインストールしますか？",
        "plugin_uninstall_failed": "アンインストール失敗",
        "plugin_store_loading": "プラグインリストを読み込み中...",
        "plugin_store_empty": "利用可能なプラグインはありません",
        "plugin_store_error": "プラグインリストの読み込みに失敗しました",
        "plugin_no_installed": "インストール済みプラグインはありません",
        "refresh": "更新",
        "ctx_copy": "コピー",
        "ctx_star": "お気に入り",
        "ctx_unstar": "お気に入り解除",
        "ctx_delete": "削除",
    },

    # ========== 한국어 ==========
    "ko_KR": {
        # 일반
        "app_name": "공유 클립보드",
        "settings": "설정",
        "ok": "확인",
        "cancel": "취소",
        "yes": "예",
        "no": "아니오",
        "confirm": "확인",
        "error": "오류",
        "warning": "경고",
        "info": "정보",
        "success": "성공",

        # 메인 윈도우
        "search_placeholder": "클립보드 검색...",
        "pin_window": "창 고정",
        "unpin_window": "고정 해제",
        "minimize": "최소화",
        "quit_app": "종료",
        "prev_page": "◀ 이전",
        "next_page": "다음 ▶",
        "page_info": "{current} / {total}",

        # 설정 대화상자
        "general": "일반",
        "database": "데이터베이스",
        "dock_position": "도킹 위치:",
        "dock_right": "오른쪽",
        "dock_left": "왼쪽",
        "dock_top": "위",
        "dock_bottom": "아래",
        "global_hotkey": "전역 단축키:",
        "hotkey_placeholder": "예: <cmd>+v",
        "hotkey_help": "단축키 형식:\n• <cmd> = Win키(Windows) / Cmd키(macOS)\n• <ctrl> = Ctrl키\n• <alt> = Alt키\n• <shift> = Shift키\n• 예: <cmd>+v, <ctrl>+<shift>+c",
        "language": "언어:",

        # 데이터베이스 설정
        "db_type": "데이터베이스 유형:",
        "db_sqlite": "SQLite (로컬 파일)",
        "db_mysql": "MySQL (네트워크 데이터베이스)",
        "sqlite_config": "SQLite 설정",
        "mysql_config": "MySQL 설정",
        "db_path": "데이터베이스 경로:",
        "path_placeholder": "경로 입력 또는 찾아보기...",
        "browse": "찾아보기...",
        "select_db_file": "데이터베이스 파일 위치 선택",
        "host": "호스트:",
        "port": "포트:",
        "username": "사용자 이름:",
        "password": "비밀번호:",
        "db_name": "데이터베이스 이름:",
        "test_connection": "연결 테스트",
        "connection_success": "연결 성공",
        "connection_failed": "연결 실패",
        "missing_dependency": "종속성 누락",
        "pymysql_required": "pymysql이 설치되지 않았습니다.\n실행하세요: pip install pymysql",
        "save_anyway": "{message}\n\n설정을 저장하시겠습니까?",

        # 클립보드 항목
        "confirm_delete": "삭제 확인",
        "delete_confirm_msg": "이 항목을 삭제하시겠습니까?",
        "image": "[이미지]",
        "from_device": "보낸 기기: {device}",

        # 이미지 저장
        "save_image": "이미지 저장",
        "image_load_failed": "이미지 데이터를 불러올 수 없습니다",
        "save_failed": "저장 실패: {error}",

        # 데이터 마이그레이션
        "migrate_data": "데이터 마이그레이션",
        "migrate_data_confirm": "기존 데이터를 새 데이터베이스로 마이그레이션하시겠습니까?",
        "migrating": "데이터 마이그레이션 중...",
        "migration_complete": "마이그레이션 완료. {count}개 항목이 마이그레이션되었습니다.",
        "migration_failed": "마이그레이션 실패: {error}",

        # 데이터베이스 프로필
        "db_profile": "데이터베이스 프로필:",
        "add_profile": "추가",
        "delete_profile": "삭제",
        "profile_name": "프로필 이름",
        "enter_profile_name": "새 프로필 이름을 입력하세요:",
        "profile_exists": "프로필 이름이 이미 존재합니다",
        "cannot_delete_active": "사용 중인 프로필은 삭제할 수 없습니다",
        "confirm_delete_profile": "프로필 \"{name}\"을(를) 삭제하시겠습니까?",

        # 메시지
        "need_restart": "재시작 필요",
        "restart_msg": "설정이 변경되었습니다. 변경 사항을 적용하려면 응용 프로그램을 다시 시작하세요.",

        # 필터 및 저장소
        "filter_storage": "필터 및 저장소",
        "content_filter": "콘텐츠 필터",
        "save_text": "텍스트 저장",
        "save_images": "이미지 저장",
        "max_text_length": "최대 텍스트 길이:",
        "max_image_size": "최대 이미지 크기:",
        "unlimited": "무제한",
        "characters": "자",
        "storage_management": "저장소 관리",
        "max_items": "최대 항목 수:",
        "retention_days": "자동 정리 일수:",
        "never_cleanup": "정리 안 함",
        "days": "일",
        "poll_interval": "폴링 간격:",

        # 트레이 메뉴
        "show_window": "창 표시",
        "quit": "종료",

        # 복사 피드백
        "copied_to_clipboard": "클립보드에 복사됨 ✓",
        "copy_failed": "복사 실패",

        # 즐겨찾기 필터
        "show_starred_only": "즐겨찾기만",

        # 정보
        "about": "정보",
        "about_description": "크로스 디바이스 클립보드 기록 관리 및 동기화 도구",
        "official_website": "공식 웹사이트:",
        "github_repo": "GitHub 저장소:",
        "download_page": "다운로드:",

        # 플러그인 시스템
        "plugins": "플러그인",
        "installed_plugins": "설치된 플러그인",
        "open_plugins_dir": "플러그인 폴더 열기",
        "reload_plugins": "다시 로드",
        "view_plugin_logs": "로그 보기",
        "plugin_dev_docs": "개발 문서",
        "plugin_settings": "설정",
        "plugin_enabled": "활성화됨",
        "plugin_disabled": "비활성화됨",
        "plugin_missing_deps": "누락된 종속성: {deps}",
        "plugin_incompatible": "호환되지 않는 버전",
        "plugin_error": "로드 실패",
        "plugin_executing": "{name} 실행 중... {percent}%",
        "plugin_timeout": "플러그인 실행 시간 초과",
        "plugin_busy": "플러그인이 실행 중입니다. 기다려 주세요",
        "plugin_not_loaded": "플러그인이 로드되지 않았습니다: {id}",
        "plugin_exec_failed": "실행 실패",
        "plugin_config_title": "{name} - 설정",
        "plugin_config_required": "필수 항목을 입력하세요",
        "plugin_save": "저장",
        "plugin_cancel": "취소",
        "plugin_saved_entry": "새 항목으로 저장됨",
        "plugin_replaced_entry": "내용이 교체됨",
        "plugin_perm_network": "네트워크 액세스",
        "plugin_perm_file_read": "파일 읽기",
        "plugin_perm_file_write": "파일 쓰기",
        "plugin_store": "플러그인 스토어",
        "plugin_install": "설치",
        "plugin_uninstall": "제거",
        "plugin_installing": "설치 중...",
        "plugin_installed_tag": "설치됨",
        "plugin_install_failed": "설치 실패",
        "plugin_uninstall_confirm_title": "제거 확인",
        "plugin_uninstall_confirm": "플러그인 \"{name}\"을(를) 제거하시겠습니까?",
        "plugin_uninstall_failed": "제거 실패",
        "plugin_store_loading": "플러그인 목록 로딩 중...",
        "plugin_store_empty": "사용 가능한 플러그인이 없습니다",
        "plugin_store_error": "플러그인 목록을 불러오지 못했습니다",
        "plugin_no_installed": "설치된 플러그인이 없습니다",
        "refresh": "새로고침",
        "ctx_copy": "복사",
        "ctx_star": "즐겨찾기",
        "ctx_unstar": "즐겨찾기 해제",
        "ctx_delete": "삭제",
    },

    # ========== Español ==========
    "es_ES": {
        # General
        "app_name": "Portapapeles Compartido",
        "settings": "Configuración",
        "ok": "Aceptar",
        "cancel": "Cancelar",
        "yes": "Sí",
        "no": "No",
        "confirm": "Confirmar",
        "error": "Error",
        "warning": "Advertencia",
        "info": "Información",
        "success": "Éxito",

        # Ventana principal
        "search_placeholder": "Buscar en portapapeles...",
        "pin_window": "Fijar ventana",
        "unpin_window": "Desfijar ventana",
        "minimize": "Minimizar",
        "quit_app": "Salir",
        "prev_page": "◀ Anterior",
        "next_page": "Siguiente ▶",
        "page_info": "{current} / {total}",

        # Diálogo de configuración
        "general": "General",
        "database": "Base de datos",
        "dock_position": "Posición de acoplamiento:",
        "dock_right": "Derecha",
        "dock_left": "Izquierda",
        "dock_top": "Arriba",
        "dock_bottom": "Abajo",
        "global_hotkey": "Tecla de acceso rápido:",
        "hotkey_placeholder": "ej.: <cmd>+v",
        "hotkey_help": "Formato de teclas:\n• <cmd> = Win (Windows) / Cmd (macOS)\n• <ctrl> = Ctrl\n• <alt> = Alt\n• <shift> = Shift\n• Ejemplos: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Idioma:",

        # Configuración de base de datos
        "db_type": "Tipo de base de datos:",
        "db_sqlite": "SQLite (Archivo local)",
        "db_mysql": "MySQL (Base de datos en red)",
        "sqlite_config": "Configuración SQLite",
        "mysql_config": "Configuración MySQL",
        "db_path": "Ruta de base de datos:",
        "path_placeholder": "Ingrese ruta o haga clic en Examinar...",
        "browse": "Examinar...",
        "select_db_file": "Seleccionar ubicación del archivo de base de datos",
        "host": "Host:",
        "port": "Puerto:",
        "username": "Usuario:",
        "password": "Contraseña:",
        "db_name": "Nombre de base de datos:",
        "test_connection": "Probar conexión",
        "connection_success": "Conexión exitosa",
        "connection_failed": "Conexión fallida",
        "missing_dependency": "Dependencia faltante",
        "pymysql_required": "pymysql no está instalado.\nEjecute: pip install pymysql",
        "save_anyway": "{message}\n\n¿Guardar configuración de todos modos?",

        # Elementos del portapapeles
        "confirm_delete": "Confirmar eliminación",
        "delete_confirm_msg": "¿Está seguro de que desea eliminar este elemento?",
        "image": "[Imagen]",
        "from_device": "Desde: {device}",

        # Guardar imagen
        "save_image": "Guardar imagen",
        "image_load_failed": "No se pudieron cargar los datos de la imagen",
        "save_failed": "Error al guardar: {error}",

        # Migración de datos
        "migrate_data": "Migrar datos",
        "migrate_data_confirm": "¿Migrar los datos existentes a la nueva base de datos?",
        "migrating": "Migrando datos...",
        "migration_complete": "Migración completada. {count} elementos migrados.",
        "migration_failed": "Error en la migración: {error}",

        # Perfiles de base de datos
        "db_profile": "Perfil de base de datos:",
        "add_profile": "Agregar",
        "delete_profile": "Eliminar",
        "profile_name": "Nombre del perfil",
        "enter_profile_name": "Ingrese el nombre del nuevo perfil:",
        "profile_exists": "El nombre del perfil ya existe",
        "cannot_delete_active": "No se puede eliminar el perfil activo",
        "confirm_delete_profile": "¿Eliminar el perfil \"{name}\"?",

        # Mensajes
        "need_restart": "Reinicio requerido",
        "restart_msg": "La configuración ha cambiado. Reinicie la aplicación para que los cambios surtan efecto.",

        # Filtro y almacenamiento
        "filter_storage": "Filtro y almacenamiento",
        "content_filter": "Filtro de contenido",
        "save_text": "Guardar texto",
        "save_images": "Guardar imágenes",
        "max_text_length": "Longitud máx. de texto:",
        "max_image_size": "Tamaño máx. de imagen:",
        "unlimited": "Sin límite",
        "characters": "caracteres",
        "storage_management": "Gestión de almacenamiento",
        "max_items": "Máx. elementos:",
        "retention_days": "Días de limpieza automática:",
        "never_cleanup": "Nunca",
        "days": "días",
        "poll_interval": "Intervalo de sondeo:",

        # Menú de bandeja
        "show_window": "Mostrar ventana",
        "quit": "Salir",

        # Retroalimentación de copia
        "copied_to_clipboard": "Copiado al portapapeles ✓",
        "copy_failed": "Error al copiar",

        # Filtro de favoritos
        "show_starred_only": "Solo favoritos",

        # Acerca de
        "about": "Acerca de",
        "about_description": "Herramienta de gestión y sincronización del historial del portapapeles entre dispositivos",
        "official_website": "Sitio web oficial:",
        "github_repo": "Repositorio GitHub:",
        "download_page": "Descargar:",

        # Sistema de plugins
        "plugins": "Plugins",
        "installed_plugins": "Plugins instalados",
        "open_plugins_dir": "Abrir carpeta de plugins",
        "reload_plugins": "Recargar",
        "view_plugin_logs": "Ver registros",
        "plugin_dev_docs": "Docs de desarrollo",
        "plugin_settings": "Configuración",
        "plugin_enabled": "Habilitado",
        "plugin_disabled": "Deshabilitado",
        "plugin_missing_deps": "Dependencias faltantes: {deps}",
        "plugin_incompatible": "Versión incompatible",
        "plugin_error": "Error de carga",
        "plugin_executing": "{name} ejecutando... {percent}%",
        "plugin_timeout": "Tiempo de espera del plugin agotado",
        "plugin_busy": "Un plugin se está ejecutando, por favor espere",
        "plugin_not_loaded": "Plugin no cargado: {id}",
        "plugin_exec_failed": "Error de ejecución",
        "plugin_config_title": "{name} - Configuración",
        "plugin_config_required": "Complete los campos obligatorios",
        "plugin_save": "Guardar",
        "plugin_cancel": "Cancelar",
        "plugin_saved_entry": "Guardado como nueva entrada",
        "plugin_replaced_entry": "Contenido reemplazado",
        "plugin_perm_network": "Acceso a red",
        "plugin_perm_file_read": "Lectura de archivos",
        "plugin_perm_file_write": "Escritura de archivos",
        "plugin_store": "Tienda de plugins",
        "plugin_install": "Instalar",
        "plugin_uninstall": "Desinstalar",
        "plugin_installing": "Instalando...",
        "plugin_installed_tag": "Instalado",
        "plugin_install_failed": "Error de instalación",
        "plugin_uninstall_confirm_title": "Confirmar desinstalación",
        "plugin_uninstall_confirm": "¿Está seguro de que desea desinstalar \"{name}\"?",
        "plugin_uninstall_failed": "Error al desinstalar",
        "plugin_store_loading": "Cargando lista de plugins...",
        "plugin_store_empty": "No hay plugins disponibles",
        "plugin_store_error": "Error al cargar la lista de plugins",
        "plugin_no_installed": "No hay plugins instalados",
        "refresh": "Actualizar",
        "ctx_copy": "Copiar",
        "ctx_star": "Favorito",
        "ctx_unstar": "Quitar favorito",
        "ctx_delete": "Eliminar",
    },

    # ========== Français ==========
    "fr_FR": {
        # Général
        "app_name": "Presse-papiers Partagé",
        "settings": "Paramètres",
        "ok": "OK",
        "cancel": "Annuler",
        "yes": "Oui",
        "no": "Non",
        "confirm": "Confirmer",
        "error": "Erreur",
        "warning": "Avertissement",
        "info": "Information",
        "success": "Succès",

        # Fenêtre principale
        "search_placeholder": "Rechercher dans le presse-papiers...",
        "pin_window": "Épingler la fenêtre",
        "unpin_window": "Désépingler la fenêtre",
        "minimize": "Réduire",
        "quit_app": "Quitter",
        "prev_page": "◀ Précédent",
        "next_page": "Suivant ▶",
        "page_info": "{current} / {total}",

        # Dialogue des paramètres
        "general": "Général",
        "database": "Base de données",
        "dock_position": "Position d'ancrage:",
        "dock_right": "Droite",
        "dock_left": "Gauche",
        "dock_top": "Haut",
        "dock_bottom": "Bas",
        "global_hotkey": "Raccourci global:",
        "hotkey_placeholder": "ex: <cmd>+v",
        "hotkey_help": "Format des raccourcis:\n• <cmd> = Win (Windows) / Cmd (macOS)\n• <ctrl> = Ctrl\n• <alt> = Alt\n• <shift> = Shift\n• Exemples: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Langue:",

        # Paramètres de base de données
        "db_type": "Type de base de données:",
        "db_sqlite": "SQLite (Fichier local)",
        "db_mysql": "MySQL (Base de données réseau)",
        "sqlite_config": "Configuration SQLite",
        "mysql_config": "Configuration MySQL",
        "db_path": "Chemin de la base de données:",
        "path_placeholder": "Entrez le chemin ou cliquez sur Parcourir...",
        "browse": "Parcourir...",
        "select_db_file": "Sélectionner l'emplacement du fichier de base de données",
        "host": "Hôte:",
        "port": "Port:",
        "username": "Utilisateur:",
        "password": "Mot de passe:",
        "db_name": "Nom de la base de données:",
        "test_connection": "Tester la connexion",
        "connection_success": "Connexion réussie",
        "connection_failed": "Connexion échouée",
        "missing_dependency": "Dépendance manquante",
        "pymysql_required": "pymysql n'est pas installé.\nExécutez: pip install pymysql",
        "save_anyway": "{message}\n\nEnregistrer les paramètres quand même?",

        # Éléments du presse-papiers
        "confirm_delete": "Confirmer la suppression",
        "delete_confirm_msg": "Êtes-vous sûr de vouloir supprimer cet élément?",
        "image": "[Image]",
        "from_device": "De: {device}",

        # Sauvegarde d'image
        "save_image": "Enregistrer l'image",
        "image_load_failed": "Impossible de charger les données de l'image",
        "save_failed": "Échec de l'enregistrement: {error}",

        # Migration de données
        "migrate_data": "Migrer les données",
        "migrate_data_confirm": "Migrer les données existantes vers la nouvelle base de données?",
        "migrating": "Migration des données en cours...",
        "migration_complete": "Migration terminée. {count} éléments migrés.",
        "migration_failed": "Échec de la migration: {error}",

        # Profils de base de données
        "db_profile": "Profil de base de données:",
        "add_profile": "Ajouter",
        "delete_profile": "Supprimer",
        "profile_name": "Nom du profil",
        "enter_profile_name": "Entrez le nom du nouveau profil:",
        "profile_exists": "Le nom du profil existe déjà",
        "cannot_delete_active": "Impossible de supprimer le profil actif",
        "confirm_delete_profile": "Supprimer le profil \"{name}\"?",

        # Messages
        "need_restart": "Redémarrage requis",
        "restart_msg": "Les paramètres ont été modifiés. Veuillez redémarrer l'application pour que les modifications prennent effet.",

        # Filtre et stockage
        "filter_storage": "Filtre et stockage",
        "content_filter": "Filtre de contenu",
        "save_text": "Enregistrer le texte",
        "save_images": "Enregistrer les images",
        "max_text_length": "Longueur max. du texte:",
        "max_image_size": "Taille max. de l'image:",
        "unlimited": "Illimité",
        "characters": "caractères",
        "storage_management": "Gestion du stockage",
        "max_items": "Nombre max. d'éléments:",
        "retention_days": "Jours de nettoyage auto:",
        "never_cleanup": "Jamais",
        "days": "jours",
        "poll_interval": "Intervalle de sondage:",

        # Menu de la barre d'état
        "show_window": "Afficher la fenêtre",
        "quit": "Quitter",

        # Retour de copie
        "copied_to_clipboard": "Copié dans le presse-papiers ✓",
        "copy_failed": "Échec de la copie",

        # Filtre favoris
        "show_starred_only": "Favoris uniquement",

        # À propos
        "about": "À propos",
        "about_description": "Outil de gestion et de synchronisation de l'historique du presse-papiers entre appareils",
        "official_website": "Site officiel:",
        "github_repo": "Dépôt GitHub:",
        "download_page": "Télécharger:",

        # Système de plugins
        "plugins": "Plugins",
        "installed_plugins": "Plugins installés",
        "open_plugins_dir": "Ouvrir le dossier des plugins",
        "reload_plugins": "Recharger",
        "view_plugin_logs": "Voir les journaux",
        "plugin_dev_docs": "Docs de développement",
        "plugin_settings": "Paramètres",
        "plugin_enabled": "Activé",
        "plugin_disabled": "Désactivé",
        "plugin_missing_deps": "Dépendances manquantes : {deps}",
        "plugin_incompatible": "Version incompatible",
        "plugin_error": "Échec du chargement",
        "plugin_executing": "{name} en cours... {percent}%",
        "plugin_timeout": "Délai d'exécution du plugin dépassé",
        "plugin_busy": "Un plugin est en cours d'exécution, veuillez patienter",
        "plugin_not_loaded": "Plugin non chargé : {id}",
        "plugin_exec_failed": "Échec de l'exécution",
        "plugin_config_title": "{name} - Paramètres",
        "plugin_config_required": "Veuillez remplir les champs obligatoires",
        "plugin_save": "Enregistrer",
        "plugin_cancel": "Annuler",
        "plugin_saved_entry": "Enregistré comme nouvelle entrée",
        "plugin_replaced_entry": "Contenu remplacé",
        "plugin_perm_network": "Accès réseau",
        "plugin_perm_file_read": "Lecture de fichiers",
        "plugin_perm_file_write": "Écriture de fichiers",
        "plugin_store": "Boutique de plugins",
        "plugin_install": "Installer",
        "plugin_uninstall": "Désinstaller",
        "plugin_installing": "Installation...",
        "plugin_installed_tag": "Installé",
        "plugin_install_failed": "Échec de l'installation",
        "plugin_uninstall_confirm_title": "Confirmer la désinstallation",
        "plugin_uninstall_confirm": "Êtes-vous sûr de vouloir désinstaller \"{name}\" ?",
        "plugin_uninstall_failed": "Échec de la désinstallation",
        "plugin_store_loading": "Chargement de la liste des plugins...",
        "plugin_store_empty": "Aucun plugin disponible",
        "plugin_store_error": "Impossible de charger la liste des plugins",
        "plugin_no_installed": "Aucun plugin installé",
        "refresh": "Actualiser",
        "ctx_copy": "Copier",
        "ctx_star": "Favori",
        "ctx_unstar": "Retirer des favoris",
        "ctx_delete": "Supprimer",
    },

    # ========== Deutsch ==========
    "de_DE": {
        # Allgemein
        "app_name": "Geteilte Zwischenablage",
        "settings": "Einstellungen",
        "ok": "OK",
        "cancel": "Abbrechen",
        "yes": "Ja",
        "no": "Nein",
        "confirm": "Bestätigen",
        "error": "Fehler",
        "warning": "Warnung",
        "info": "Information",
        "success": "Erfolg",

        # Hauptfenster
        "search_placeholder": "Zwischenablage durchsuchen...",
        "pin_window": "Fenster anheften",
        "unpin_window": "Fenster lösen",
        "minimize": "Minimieren",
        "quit_app": "Beenden",
        "prev_page": "◀ Zurück",
        "next_page": "Weiter ▶",
        "page_info": "{current} / {total}",

        # Einstellungsdialog
        "general": "Allgemein",
        "database": "Datenbank",
        "dock_position": "Andockposition:",
        "dock_right": "Rechts",
        "dock_left": "Links",
        "dock_top": "Oben",
        "dock_bottom": "Unten",
        "global_hotkey": "Globale Tastenkombination:",
        "hotkey_placeholder": "z.B.: <cmd>+v",
        "hotkey_help": "Tastenkombinationsformat:\n• <cmd> = Win-Taste (Windows) / Cmd-Taste (macOS)\n• <ctrl> = Strg-Taste\n• <alt> = Alt-Taste\n• <shift> = Umschalt-Taste\n• Beispiele: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Sprache:",

        # Datenbankeinstellungen
        "db_type": "Datenbanktyp:",
        "db_sqlite": "SQLite (Lokale Datei)",
        "db_mysql": "MySQL (Netzwerkdatenbank)",
        "sqlite_config": "SQLite-Konfiguration",
        "mysql_config": "MySQL-Konfiguration",
        "db_path": "Datenbankpfad:",
        "path_placeholder": "Pfad eingeben oder auf Durchsuchen klicken...",
        "browse": "Durchsuchen...",
        "select_db_file": "Datenbankdatei-Speicherort auswählen",
        "host": "Host:",
        "port": "Port:",
        "username": "Benutzername:",
        "password": "Passwort:",
        "db_name": "Datenbankname:",
        "test_connection": "Verbindung testen",
        "connection_success": "Verbindung erfolgreich",
        "connection_failed": "Verbindung fehlgeschlagen",
        "missing_dependency": "Fehlende Abhängigkeit",
        "pymysql_required": "pymysql ist nicht installiert.\nFühren Sie aus: pip install pymysql",
        "save_anyway": "{message}\n\nEinstellungen trotzdem speichern?",

        # Zwischenablage-Elemente
        "confirm_delete": "Löschen bestätigen",
        "delete_confirm_msg": "Sind Sie sicher, dass Sie dieses Element löschen möchten?",
        "image": "[Bild]",
        "from_device": "Von: {device}",

        # Bild speichern
        "save_image": "Bild speichern",
        "image_load_failed": "Bilddaten konnten nicht geladen werden",
        "save_failed": "Speichern fehlgeschlagen: {error}",

        # Datenmigration
        "migrate_data": "Daten migrieren",
        "migrate_data_confirm": "Bestehende Daten in die neue Datenbank migrieren?",
        "migrating": "Daten werden migriert...",
        "migration_complete": "Migration abgeschlossen. {count} Elemente migriert.",
        "migration_failed": "Migration fehlgeschlagen: {error}",

        # Datenbankprofile
        "db_profile": "Datenbankprofil:",
        "add_profile": "Hinzufügen",
        "delete_profile": "Löschen",
        "profile_name": "Profilname",
        "enter_profile_name": "Neuen Profilnamen eingeben:",
        "profile_exists": "Profilname existiert bereits",
        "cannot_delete_active": "Das aktive Profil kann nicht gelöscht werden",
        "confirm_delete_profile": "Profil \"{name}\" löschen?",

        # Nachrichten
        "need_restart": "Neustart erforderlich",
        "restart_msg": "Die Einstellungen wurden geändert. Bitte starten Sie die Anwendung neu, damit die Änderungen wirksam werden.",

        # Filter und Speicher
        "filter_storage": "Filter und Speicher",
        "content_filter": "Inhaltsfilter",
        "save_text": "Text speichern",
        "save_images": "Bilder speichern",
        "max_text_length": "Max. Textlänge:",
        "max_image_size": "Max. Bildgröße:",
        "unlimited": "Unbegrenzt",
        "characters": "Zeichen",
        "storage_management": "Speicherverwaltung",
        "max_items": "Max. Einträge:",
        "retention_days": "Auto-Bereinigung Tage:",
        "never_cleanup": "Nie",
        "days": "Tage",
        "poll_interval": "Abfrageintervall:",

        # Taskleistenmenü
        "show_window": "Fenster anzeigen",
        "quit": "Beenden",

        # Kopier-Feedback
        "copied_to_clipboard": "In Zwischenablage kopiert ✓",
        "copy_failed": "Kopieren fehlgeschlagen",

        # Favoriten-Filter
        "show_starred_only": "Nur Favoriten",

        # Über
        "about": "Über",
        "about_description": "Ein geräteübergreifendes Tool zur Verwaltung und Synchronisierung der Zwischenablage",
        "official_website": "Offizielle Website:",
        "github_repo": "GitHub-Repository:",
        "download_page": "Herunterladen:",

        # Plugin-System
        "plugins": "Plugins",
        "installed_plugins": "Installierte Plugins",
        "open_plugins_dir": "Plugin-Ordner öffnen",
        "reload_plugins": "Neu laden",
        "view_plugin_logs": "Protokolle anzeigen",
        "plugin_dev_docs": "Entwicklerdoku",
        "plugin_settings": "Einstellungen",
        "plugin_enabled": "Aktiviert",
        "plugin_disabled": "Deaktiviert",
        "plugin_missing_deps": "Fehlende Abhängigkeiten: {deps}",
        "plugin_incompatible": "Inkompatible Version",
        "plugin_error": "Laden fehlgeschlagen",
        "plugin_executing": "{name} wird ausgeführt... {percent}%",
        "plugin_timeout": "Plugin-Zeitüberschreitung",
        "plugin_busy": "Ein Plugin wird ausgeführt, bitte warten",
        "plugin_not_loaded": "Plugin nicht geladen: {id}",
        "plugin_exec_failed": "Ausführung fehlgeschlagen",
        "plugin_config_title": "{name} - Einstellungen",
        "plugin_config_required": "Bitte füllen Sie die Pflichtfelder aus",
        "plugin_save": "Speichern",
        "plugin_cancel": "Abbrechen",
        "plugin_saved_entry": "Als neuer Eintrag gespeichert",
        "plugin_replaced_entry": "Inhalt ersetzt",
        "plugin_perm_network": "Netzwerkzugriff",
        "plugin_perm_file_read": "Dateien lesen",
        "plugin_perm_file_write": "Dateien schreiben",
        "plugin_store": "Plugin-Store",
        "plugin_install": "Installieren",
        "plugin_uninstall": "Deinstallieren",
        "plugin_installing": "Wird installiert...",
        "plugin_installed_tag": "Installiert",
        "plugin_install_failed": "Installation fehlgeschlagen",
        "plugin_uninstall_confirm_title": "Deinstallation bestätigen",
        "plugin_uninstall_confirm": "Möchten Sie \"{name}\" wirklich deinstallieren?",
        "plugin_uninstall_failed": "Deinstallation fehlgeschlagen",
        "plugin_store_loading": "Plugin-Liste wird geladen...",
        "plugin_store_empty": "Keine Plugins verfügbar",
        "plugin_store_error": "Plugin-Liste konnte nicht geladen werden",
        "plugin_no_installed": "Keine Plugins installiert",
        "refresh": "Aktualisieren",
        "ctx_copy": "Kopieren",
        "ctx_star": "Favorit",
        "ctx_unstar": "Favorit entfernen",
        "ctx_delete": "Löschen",
    },

    # ========== Русский ==========
    "ru_RU": {
        # Общие
        "app_name": "Общий буфер обмена",
        "settings": "Настройки",
        "ok": "ОК",
        "cancel": "Отмена",
        "yes": "Да",
        "no": "Нет",
        "confirm": "Подтвердить",
        "error": "Ошибка",
        "warning": "Предупреждение",
        "info": "Информация",
        "success": "Успешно",

        # Главное окно
        "search_placeholder": "Поиск в буфере обмена...",
        "pin_window": "Закрепить окно",
        "unpin_window": "Открепить окно",
        "minimize": "Свернуть",
        "quit_app": "Выход",
        "prev_page": "◀ Назад",
        "next_page": "Далее ▶",
        "page_info": "{current} / {total}",

        # Диалог настроек
        "general": "Общие",
        "database": "База данных",
        "dock_position": "Позиция закрепления:",
        "dock_right": "Справа",
        "dock_left": "Слева",
        "dock_top": "Сверху",
        "dock_bottom": "Снизу",
        "global_hotkey": "Глобальная горячая клавиша:",
        "hotkey_placeholder": "напр.: <cmd>+v",
        "hotkey_help": "Формат горячих клавиш:\n• <cmd> = Win (Windows) / Cmd (macOS)\n• <ctrl> = Ctrl\n• <alt> = Alt\n• <shift> = Shift\n• Примеры: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Язык:",

        # Настройки базы данных
        "db_type": "Тип базы данных:",
        "db_sqlite": "SQLite (Локальный файл)",
        "db_mysql": "MySQL (Сетевая база данных)",
        "sqlite_config": "Настройки SQLite",
        "mysql_config": "Настройки MySQL",
        "db_path": "Путь к базе данных:",
        "path_placeholder": "Введите путь или нажмите Обзор...",
        "browse": "Обзор...",
        "select_db_file": "Выберите расположение файла базы данных",
        "host": "Хост:",
        "port": "Порт:",
        "username": "Имя пользователя:",
        "password": "Пароль:",
        "db_name": "Имя базы данных:",
        "test_connection": "Проверить соединение",
        "connection_success": "Соединение успешно",
        "connection_failed": "Соединение не удалось",
        "missing_dependency": "Отсутствует зависимость",
        "pymysql_required": "pymysql не установлен.\nВыполните: pip install pymysql",
        "save_anyway": "{message}\n\nСохранить настройки в любом случае?",

        # Элементы буфера обмена
        "confirm_delete": "Подтвердить удаление",
        "delete_confirm_msg": "Вы уверены, что хотите удалить этот элемент?",
        "image": "[Изображение]",
        "from_device": "От: {device}",

        # Сохранение изображения
        "save_image": "Сохранить изображение",
        "image_load_failed": "Не удалось загрузить данные изображения",
        "save_failed": "Ошибка сохранения: {error}",

        # Миграция данных
        "migrate_data": "Миграция данных",
        "migrate_data_confirm": "Перенести существующие данные в новую базу данных?",
        "migrating": "Миграция данных...",
        "migration_complete": "Миграция завершена. Перенесено элементов: {count}.",
        "migration_failed": "Ошибка миграции: {error}",

        # Профили базы данных
        "db_profile": "Профиль базы данных:",
        "add_profile": "Добавить",
        "delete_profile": "Удалить",
        "profile_name": "Имя профиля",
        "enter_profile_name": "Введите имя нового профиля:",
        "profile_exists": "Имя профиля уже существует",
        "cannot_delete_active": "Невозможно удалить активный профиль",
        "confirm_delete_profile": "Удалить профиль \"{name}\"?",

        # Сообщения
        "need_restart": "Требуется перезапуск",
        "restart_msg": "Настройки были изменены. Пожалуйста, перезапустите приложение для применения изменений.",

        # Фильтр и хранение
        "filter_storage": "Фильтр и хранение",
        "content_filter": "Фильтр содержимого",
        "save_text": "Сохранять текст",
        "save_images": "Сохранять изображения",
        "max_text_length": "Макс. длина текста:",
        "max_image_size": "Макс. размер изображения:",
        "unlimited": "Без ограничений",
        "characters": "символов",
        "storage_management": "Управление хранилищем",
        "max_items": "Макс. записей:",
        "retention_days": "Авто-очистка дней:",
        "never_cleanup": "Никогда",
        "days": "дней",
        "poll_interval": "Интервал опроса:",

        # Меню в трее
        "show_window": "Показать окно",
        "quit": "Выход",

        # Обратная связь при копировании
        "copied_to_clipboard": "Скопировано в буфер обмена ✓",
        "copy_failed": "Ошибка копирования",

        # Фильтр избранного
        "show_starred_only": "Только избранное",

        # О программе
        "about": "О программе",
        "about_description": "Инструмент управления и синхронизации истории буфера обмена между устройствами",
        "official_website": "Официальный сайт:",
        "github_repo": "Репозиторий GitHub:",
        "download_page": "Скачать:",

        # Система плагинов
        "plugins": "Плагины",
        "installed_plugins": "Установленные плагины",
        "open_plugins_dir": "Открыть папку плагинов",
        "reload_plugins": "Перезагрузить",
        "view_plugin_logs": "Просмотр журналов",
        "plugin_dev_docs": "Документация",
        "plugin_settings": "Настройки",
        "plugin_enabled": "Включен",
        "plugin_disabled": "Отключен",
        "plugin_missing_deps": "Отсутствуют зависимости: {deps}",
        "plugin_incompatible": "Несовместимая версия",
        "plugin_error": "Ошибка загрузки",
        "plugin_executing": "{name} выполняется... {percent}%",
        "plugin_timeout": "Время выполнения плагина истекло",
        "plugin_busy": "Плагин уже выполняется, пожалуйста подождите",
        "plugin_not_loaded": "Плагин не загружен: {id}",
        "plugin_exec_failed": "Ошибка выполнения",
        "plugin_config_title": "{name} - Настройки",
        "plugin_config_required": "Пожалуйста, заполните обязательные поля",
        "plugin_save": "Сохранить",
        "plugin_cancel": "Отмена",
        "plugin_saved_entry": "Сохранено как новая запись",
        "plugin_replaced_entry": "Содержимое заменено",
        "plugin_perm_network": "Сетевой доступ",
        "plugin_perm_file_read": "Чтение файлов",
        "plugin_perm_file_write": "Запись файлов",
        "plugin_store": "Магазин плагинов",
        "plugin_install": "Установить",
        "plugin_uninstall": "Удалить",
        "plugin_installing": "Установка...",
        "plugin_installed_tag": "Установлен",
        "plugin_install_failed": "Ошибка установки",
        "plugin_uninstall_confirm_title": "Подтверждение удаления",
        "plugin_uninstall_confirm": "Вы уверены, что хотите удалить \"{name}\"?",
        "plugin_uninstall_failed": "Ошибка удаления",
        "plugin_store_loading": "Загрузка списка плагинов...",
        "plugin_store_empty": "Нет доступных плагинов",
        "plugin_store_error": "Не удалось загрузить список плагинов",
        "plugin_no_installed": "Нет установленных плагинов",
        "refresh": "Обновить",
        "ctx_copy": "Копировать",
        "ctx_star": "В избранное",
        "ctx_unstar": "Из избранного",
        "ctx_delete": "Удалить",
    },
}


class I18n:
    """国际化管理类"""

    _current_language: str = "zh_CN"
    _instance: Optional["I18n"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def set_language(cls, language: str):
        """设置当前语言"""
        if language in SUPPORTED_LANGUAGES:
            cls._current_language = language

    @classmethod
    def get_language(cls) -> str:
        """获取当前语言"""
        return cls._current_language

    @classmethod
    def get_languages(cls) -> Dict[str, str]:
        """获取所有支持的语言"""
        return SUPPORTED_LANGUAGES.copy()

    @classmethod
    def t(cls, key: str, **kwargs) -> str:
        """
        获取翻译文本

        Args:
            key: 翻译键
            **kwargs: 格式化参数

        Returns:
            翻译后的文本，如果找不到则返回键本身
        """
        translations = TRANSLATIONS.get(cls._current_language, {})
        text = translations.get(key, key)

        # 如果当前语言没有翻译，尝试使用英语
        if text == key and cls._current_language != "en_US":
            text = TRANSLATIONS.get("en_US", {}).get(key, key)

        # 格式化参数
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass

        return text


# 便捷函数
def t(key: str, **kwargs) -> str:
    """翻译便捷函数"""
    return I18n.t(key, **kwargs)


def set_language(language: str):
    """设置语言便捷函数"""
    I18n.set_language(language)


def get_language() -> str:
    """获取当前语言"""
    return I18n.get_language()


def get_languages() -> Dict[str, str]:
    """获取所有支持的语言"""
    return I18n.get_languages()
