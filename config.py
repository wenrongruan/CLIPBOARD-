import os
import re
import sys
import json
import stat
import uuid
import hashlib
import platform
from pathlib import Path


class Config:
    # 应用信息
    APP_NAME = "SharedClipboard"
    APP_VERSION = "2.0.0"

    # 平台检测
    IS_WINDOWS = platform.system() == "Windows"
    IS_MACOS = platform.system() == "Darwin"
    IS_LINUX = platform.system() == "Linux"

    # 数据库配置
    MAX_ITEMS = 10000

    # 同步配置
    SYNC_INTERVAL_MS = 1000  # 同步轮询间隔（毫秒）

    # UI配置 - macOS 上窗口可以稍大一些
    WINDOW_WIDTH = 380 if platform.system() == "Darwin" else 350
    WINDOW_HEIGHT = 650 if platform.system() == "Darwin" else 600
    HIDDEN_MARGIN = 3  # 隐藏时露出的像素
    TRIGGER_ZONE = 10  # 触发区域宽度
    ANIMATION_DURATION = 250 if platform.system() == "Darwin" else 200  # macOS 动画稍慢更流畅
    PAGE_SIZE = 10  # 每页显示条数

    # 缩略图配置
    THUMBNAIL_SIZE = (100, 100)

    # 配置文件路径
    _config_dir = None
    _config_file = None
    _settings = None

    @classmethod
    def get_config_dir(cls) -> Path:
        if cls._config_dir is None:
            if platform.system() == "Windows":
                base = Path(os.environ.get("APPDATA", Path.home()))
            elif platform.system() == "Darwin":
                base = Path.home() / "Library" / "Application Support"
            else:  # Linux
                base = Path.home() / ".config"
            cls._config_dir = base / cls.APP_NAME
            cls._config_dir.mkdir(parents=True, exist_ok=True)
        return cls._config_dir

    @classmethod
    def get_config_file(cls) -> Path:
        if cls._config_file is None:
            cls._config_file = cls.get_config_dir() / "settings.json"
        return cls._config_file

    @classmethod
    def load_settings(cls) -> dict:
        if cls._settings is None:
            config_file = cls.get_config_file()
            if config_file.exists():
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        cls._settings = json.load(f)
                except (json.JSONDecodeError, IOError):
                    cls._settings = {}
            else:
                cls._settings = {}
        return cls._settings

    @classmethod
    def save_settings(cls, settings: dict):
        cls._settings = settings
        config_file = cls.get_config_file()
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        # 限制配置文件权限，仅所有者可读写
        try:
            if not cls.IS_WINDOWS:
                os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    @classmethod
    def get_setting(cls, key: str, default=None):
        settings = cls.load_settings()
        return settings.get(key, default)

    @classmethod
    def set_setting(cls, key: str, value):
        settings = cls.load_settings()
        settings[key] = value
        cls.save_settings(settings)

    @classmethod
    def get_database_path(cls) -> str:
        path = cls.get_setting("database_path")
        if path:
            return path
        # 默认路径：放在配置目录，符合 App Sandbox 要求
        return str(cls.get_config_dir() / "clipboard.db")

    @classmethod
    def set_database_path(cls, path: str):
        cls.set_setting("database_path", path)

    @classmethod
    def get_dock_edge(cls) -> str:
        return cls.get_setting("dock_edge", "right")

    @classmethod
    def set_dock_edge(cls, edge: str):
        if edge in ("left", "right", "top", "bottom"):
            cls.set_setting("dock_edge", edge)

    @classmethod
    def get_device_id(cls) -> str:
        device_id = cls.get_setting("device_id")
        if not device_id:
            # 使用随机 UUID，避免 MAC 地址泄露隐私
            device_id = uuid.uuid4().hex[:16]
            cls.set_setting("device_id", device_id)
        return device_id

    @classmethod
    def get_device_name(cls) -> str:
        name = cls.get_setting("device_name")
        if not name:
            name = f"{platform.node()} ({platform.system()})"
            cls.set_setting("device_name", name)
        return name

    @classmethod
    def get_last_sync_id(cls) -> int:
        return cls.get_setting("last_sync_id", 0)

    @classmethod
    def set_last_sync_id(cls, sync_id: int):
        cls.set_setting("last_sync_id", sync_id)

    # ========== 热键配置 ==========
    @classmethod
    def get_default_hotkey(cls) -> str:
        """获取默认热键"""
        if cls.IS_MACOS:
            return "<cmd>+v"
        else:
            return "<cmd>+v"  # pynput 中 <cmd> 在 Windows 上映射为 Win 键

    @classmethod
    def get_hotkey(cls) -> str:
        return cls.get_setting("hotkey", cls.get_default_hotkey())

    @classmethod
    def set_hotkey(cls, hotkey: str):
        cls.set_setting("hotkey", hotkey)

    # ========== 同步模式配置 ==========
    @classmethod
    def get_sync_mode(cls) -> str:
        """获取同步模式: local, mysql, cloud"""
        return cls.get_setting("sync_mode", "local")

    @classmethod
    def set_sync_mode(cls, mode: str):
        if mode in ("local", "mysql", "cloud"):
            cls.set_setting("sync_mode", mode)

    # ========== 云端配置 ==========

    # 允许的 API 域名白名单
    _ALLOWED_API_DOMAINS = {"www.jlike.com", "localhost", "127.0.0.1"}

    @classmethod
    def get_cloud_api_url(cls) -> str:
        """获取云端 API 地址"""
        return cls.get_setting("cloud_api_url", "https://www.jlike.com")

    @classmethod
    def set_cloud_api_url(cls, url: str):
        cls.validate_cloud_api_url(url)
        cls.set_setting("cloud_api_url", url)

    @classmethod
    def validate_cloud_api_url(cls, url: str):
        """校验云端 API URL 的安全性"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        # 强制 HTTPS（localhost 开发环境除外）
        hostname = parsed.hostname or ""
        if parsed.scheme != "https" and hostname not in ("localhost", "127.0.0.1"):
            raise ValueError(f"云端 API 必须使用 HTTPS 协议: {url}")
        # 域名白名单校验
        if hostname not in cls._ALLOWED_API_DOMAINS:
            raise ValueError(f"不允许的 API 域名: {hostname}")

    @classmethod
    def get_cloud_access_token(cls) -> str:
        from utils.secure_store import retrieve_credential
        return retrieve_credential("cloud_access_token")

    @classmethod
    def set_cloud_access_token(cls, token: str):
        from utils.secure_store import store_credential
        store_credential("cloud_access_token", token)

    @classmethod
    def get_cloud_refresh_token(cls) -> str:
        from utils.secure_store import retrieve_credential
        return retrieve_credential("cloud_refresh_token")

    @classmethod
    def set_cloud_refresh_token(cls, token: str):
        from utils.secure_store import store_credential
        store_credential("cloud_refresh_token", token)

    @classmethod
    def get_cloud_user_email(cls) -> str:
        return cls.get_setting("cloud_user_email", "")

    @classmethod
    def set_cloud_user_email(cls, email: str):
        cls.set_setting("cloud_user_email", email)

    @classmethod
    def get_cloud_last_sync_id(cls) -> int:
        return cls.get_setting("cloud_last_sync_id", 0)

    @classmethod
    def set_cloud_last_sync_id(cls, sync_id: int):
        cls.set_setting("cloud_last_sync_id", sync_id)

    # ========== 数据库类型配置 ==========
    @classmethod
    def get_db_type(cls) -> str:
        """获取数据库类型: sqlite 或 mysql"""
        return cls.get_setting("db_type", "sqlite")

    @classmethod
    def set_db_type(cls, db_type: str):
        if db_type in ("sqlite", "mysql"):
            cls.set_setting("db_type", db_type)

    # ========== MySQL 配置 ==========
    # 数据库名白名单：仅允许字母、数字、下划线
    _DB_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+$')

    @classmethod
    def get_mysql_config(cls) -> dict:
        from utils.secure_store import retrieve_credential
        return {
            "host": cls.get_setting("mysql_host", "localhost"),
            "port": cls.get_setting("mysql_port", 3306),
            "user": cls.get_setting("mysql_user", ""),
            "password": retrieve_credential("mysql_password"),
            "database": cls.get_setting("mysql_database", "clipboard"),
        }

    @classmethod
    def set_mysql_config(cls, host: str, port: int, user: str, password: str, database: str):
        from utils.secure_store import store_credential
        # 校验数据库名安全性
        if database and not cls._DB_NAME_PATTERN.match(database):
            raise ValueError(f"不安全的数据库名（仅允许字母、数字、下划线）: {database}")
        cls.set_setting("mysql_host", host)
        cls.set_setting("mysql_port", port)
        cls.set_setting("mysql_user", user)
        store_credential("mysql_password", password)
        cls.set_setting("mysql_database", database)

    @classmethod
    def validate_mysql_database_name(cls, name: str) -> bool:
        """校验 MySQL 数据库名是否安全"""
        return bool(cls._DB_NAME_PATTERN.match(name))

    # ========== 数据库 Profiles ==========
    @classmethod
    def _ensure_default_profile(cls):
        """确保至少有一个 Default profile（从现有设置自动生成）"""
        settings = cls.load_settings()
        if "db_profiles" not in settings:
            default_profile = {
                "db_type": settings.get("db_type", "sqlite"),
                "database_path": settings.get("database_path", ""),
                "mysql_host": settings.get("mysql_host", "localhost"),
                "mysql_port": settings.get("mysql_port", 3306),
                "mysql_user": settings.get("mysql_user", ""),
                "mysql_password": "",  # 密码已迁移到安全存储，不再存入 profile
                "mysql_database": settings.get("mysql_database", "clipboard"),
            }
            settings["db_profiles"] = {"Default": default_profile}
            settings["active_profile"] = "Default"
            cls.save_settings(settings)

    @classmethod
    def get_db_profiles(cls) -> dict:
        cls._ensure_default_profile()
        return cls.get_setting("db_profiles", {})

    @classmethod
    def set_db_profiles(cls, profiles: dict):
        cls.set_setting("db_profiles", profiles)

    @classmethod
    def get_active_profile(cls) -> str:
        cls._ensure_default_profile()
        return cls.get_setting("active_profile", "Default")

    @classmethod
    def set_active_profile(cls, name: str):
        cls.set_setting("active_profile", name)

    @classmethod
    def apply_profile(cls, name: str):
        """将指定 profile 的配置写入顶级设置"""
        profiles = cls.get_db_profiles()
        profile = profiles.get(name)
        if not profile:
            return
        settings = cls.load_settings()
        for key in ("db_type", "database_path", "mysql_host", "mysql_port",
                     "mysql_user", "mysql_password", "mysql_database"):
            if key in profile:
                settings[key] = profile[key]
        settings["active_profile"] = name
        cls.save_settings(settings)

    # ========== 过滤与存储配置 ==========
    @classmethod
    def get_save_text(cls) -> bool:
        return cls.get_setting("save_text", True)

    @classmethod
    def get_save_images(cls) -> bool:
        return cls.get_setting("save_images", True)

    @classmethod
    def get_max_text_length(cls) -> int:
        """最大文本长度（字符），0=不限"""
        return cls.get_setting("max_text_length", 0)

    @classmethod
    def get_max_image_size_kb(cls) -> int:
        """最大图片大小（KB），0=不限"""
        return cls.get_setting("max_image_size_kb", 0)

    @classmethod
    def get_max_items(cls) -> int:
        return cls.get_setting("max_items", 10000)

    @classmethod
    def get_retention_days(cls) -> int:
        """自动清理天数，0=永不清理"""
        return cls.get_setting("retention_days", 0)

    @classmethod
    def get_poll_interval_ms(cls) -> int:
        return cls.get_setting("poll_interval_ms", 500)

    # ========== 语言配置 ==========
    @classmethod
    def get_language(cls) -> str:
        """获取当前语言设置"""
        return cls.get_setting("language", "zh_CN")

    @classmethod
    def set_language(cls, language: str):
        """设置语言"""
        cls.set_setting("language", language)

    # ========== 插件配置 ==========
    @classmethod
    def get_user_plugins_dir(cls) -> Path:
        """获取用户插件目录"""
        plugins_dir = cls.get_config_dir() / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        return plugins_dir

    @classmethod
    def is_plugin_enabled(cls, plugin_id: str) -> bool:
        """检查插件是否启用（默认启用）"""
        disabled = cls.get_setting("disabled_plugins", [])
        return plugin_id not in disabled

    @classmethod
    def set_plugin_enabled(cls, plugin_id: str, enabled: bool):
        """设置插件启用/禁用"""
        disabled = cls.get_setting("disabled_plugins", [])
        if enabled and plugin_id in disabled:
            disabled.remove(plugin_id)
        elif not enabled and plugin_id not in disabled:
            disabled.append(plugin_id)
        cls.set_setting("disabled_plugins", disabled)
