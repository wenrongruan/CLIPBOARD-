import os
import sys
import json
import uuid
import hashlib
import platform
from pathlib import Path


class Config:
    # 应用信息
    APP_NAME = "SharedClipboard"
    APP_VERSION = "1.0.0"

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
            else:  # macOS / Linux
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
        # 默认路径（项目文件夹）
        project_dir = Path(__file__).parent
        return str(project_dir / "clipboard.db")

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
            # 基于MAC地址生成稳定的设备ID
            mac = uuid.getnode()
            device_id = hashlib.md5(str(mac).encode()).hexdigest()[:16]
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
    @classmethod
    def get_mysql_config(cls) -> dict:
        return {
            "host": cls.get_setting("mysql_host", "localhost"),
            "port": cls.get_setting("mysql_port", 3306),
            "user": cls.get_setting("mysql_user", ""),
            "password": cls.get_setting("mysql_password", ""),
            "database": cls.get_setting("mysql_database", "clipboard"),
        }

    @classmethod
    def set_mysql_config(cls, host: str, port: int, user: str, password: str, database: str):
        cls.set_setting("mysql_host", host)
        cls.set_setting("mysql_port", port)
        cls.set_setting("mysql_user", user)
        cls.set_setting("mysql_password", password)
        cls.set_setting("mysql_database", database)

    # ========== 语言配置 ==========
    @classmethod
    def get_language(cls) -> str:
        """获取当前语言设置"""
        return cls.get_setting("language", "zh_CN")

    @classmethod
    def set_language(cls, language: str):
        """设置语言"""
        cls.set_setting("language", language)
