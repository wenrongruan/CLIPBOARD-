"""应用配置管理:frozen AppSettings snapshot + 线程安全 SettingsStore。

凭据(token、password)走 keyring (utils.secure_store),不在 AppSettings 里。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import stat
import threading
import uuid
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


# ============ 枚举 ============

class SyncMode(str, Enum):
    LOCAL = "local"
    MYSQL = "mysql"
    CLOUD = "cloud"

    @classmethod
    def parse(cls, value: str) -> "SyncMode":
        try:
            return cls(value)
        except ValueError:
            return cls.LOCAL


# ============ 模块级常量 ============

APP_NAME = "SharedClipboard"
APP_VERSION = "3.0.0"

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

MAX_ITEMS = 10000
SYNC_INTERVAL_MS = 1000  # 同步轮询间隔(毫秒)

# UI 尺寸 - macOS 上稍大
WINDOW_WIDTH = 380 if IS_MACOS else 350
WINDOW_HEIGHT = 650 if IS_MACOS else 600
HIDDEN_MARGIN = 3  # 隐藏时露出的像素
TRIGGER_ZONE = 10  # 触发区域宽度
ANIMATION_DURATION = 250 if IS_MACOS else 200
PAGE_SIZE = 10  # 每页显示条数
THUMBNAIL_SIZE = (100, 100)

# 云端 API 域名白名单
_ALLOWED_API_DOMAINS = {"www.jlike.com", "api.jlike.com", "localhost", "127.0.0.1"}
# 数据库名白名单:仅字母、数字、下划线
_DB_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


# ============ Frozen 数据结构 ============

@dataclass(frozen=True)
class MysqlConnection:
    """MySQL 连接参数(密码走 keyring,不在这里)。"""
    host: str = "localhost"
    port: int = 3306
    user: str = ""
    database: str = "clipboard"


@dataclass(frozen=True)
class AppSettings:
    """应用配置的 immutable snapshot。

    字段都是 JSON 可序列化的基本类型。
    凭据(token、password)走 utils.secure_store,不在此处。
    `db_profiles` 是 dict(嵌套结构复杂且只读消费),frozen 仅保证顶层属性不可重赋;
    调用端应通过 `update_settings(db_profiles=new_dict)` 替换,而不是 mutate。
    """

    # 设备
    device_id: str = ""
    device_name: str = ""

    # 数据库
    database_path: str = ""
    db_type: str = "sqlite"
    mysql: MysqlConnection = field(default_factory=MysqlConnection)

    # 同步
    sync_mode: str = "local"
    last_sync_id: int = 0
    cloud_last_sync_id: int = 0
    cloud_api_url: str = "https://www.jlike.com"
    cloud_user_email: str = ""

    # UI
    dock_edge: str = "right"
    hotkey: str = ""  # 空表示使用平台默认 — 用 get_effective_hotkey() 读取
    is_floating: bool = False
    floating_position: Optional[Tuple[int, int]] = None
    language: str = "zh_CN"

    # 过滤/存储
    save_text: bool = True
    save_images: bool = True
    max_text_length: int = 0
    max_image_size_kb: int = 0
    max_items: int = 10000
    retention_days: int = 0
    poll_interval_ms: int = 500

    # Profile
    active_profile: str = "Default"
    db_profiles: Mapping[str, dict] = field(default_factory=dict)

    # 插件
    disabled_plugins: Tuple[str, ...] = ()


# ============ 序列化 ============

# mysql 字段在 JSON 里扁平化为 mysql_<name>,在 AppSettings 里是 MysqlConnection 嵌套
_MYSQL_FLAT_KEYS = {f"mysql_{f.name}" for f in fields(MysqlConnection)}
_APP_FIELD_NAMES = {f.name for f in fields(AppSettings)} - {"mysql"} | _MYSQL_FLAT_KEYS


def _normalize_cloud_api_url(url: str) -> str:
    # Why: 历史版本默认值误填 api.jlike.com(未部署子域),导致新装机订阅/同步全部 ConnectError。
    # 读取 settings.json 时静默改写为 www.jlike.com,老用户升级后下次保存即自愈。
    if url == "https://api.jlike.com":
        return "https://www.jlike.com"
    return url


def _snapshot_from_dict(data: dict) -> Tuple[AppSettings, dict]:
    """返回 (AppSettings, raw_extras)。extras 包含未被 AppSettings schema 消费的键。"""
    extras = {k: v for k, v in data.items() if k not in _APP_FIELD_NAMES}

    floating = data.get("floating_position")
    if isinstance(floating, (list, tuple)) and len(floating) == 2:
        floating_pos: Optional[Tuple[int, int]] = (int(floating[0]), int(floating[1]))
    else:
        floating_pos = None

    snapshot = AppSettings(
        device_id=data.get("device_id", ""),
        device_name=data.get("device_name", ""),
        database_path=data.get("database_path", ""),
        db_type=data.get("db_type", "sqlite"),
        mysql=MysqlConnection(
            host=data.get("mysql_host", "localhost"),
            port=int(data.get("mysql_port", 3306)),
            user=data.get("mysql_user", ""),
            database=data.get("mysql_database", "clipboard"),
        ),
        sync_mode=data.get("sync_mode", "local"),
        last_sync_id=int(data.get("last_sync_id", 0)),
        cloud_last_sync_id=int(data.get("cloud_last_sync_id", 0)),
        cloud_api_url=_normalize_cloud_api_url(data.get("cloud_api_url", "https://www.jlike.com")),
        cloud_user_email=data.get("cloud_user_email", ""),
        dock_edge=data.get("dock_edge", "right"),
        hotkey=data.get("hotkey", ""),
        is_floating=bool(data.get("is_floating", False)),
        floating_position=floating_pos,
        language=data.get("language", "zh_CN"),
        save_text=bool(data.get("save_text", True)),
        save_images=bool(data.get("save_images", True)),
        max_text_length=int(data.get("max_text_length", 0)),
        max_image_size_kb=int(data.get("max_image_size_kb", 0)),
        max_items=int(data.get("max_items", 10000)),
        retention_days=int(data.get("retention_days", 0)),
        poll_interval_ms=int(data.get("poll_interval_ms", 500)),
        active_profile=data.get("active_profile", "Default"),
        db_profiles=dict(data.get("db_profiles", {})),
        disabled_plugins=tuple(data.get("disabled_plugins", [])),
    )
    return snapshot, extras


def _snapshot_to_dict(s: AppSettings, extras: dict) -> dict:
    """序列化为 JSON 友好字典。mysql 字段扁平化,extras 合并回去。"""
    d: dict = dict(extras)  # 先放 extras,再被已知字段覆盖
    d.update({
        "device_id": s.device_id,
        "device_name": s.device_name,
        "database_path": s.database_path,
        "db_type": s.db_type,
        "mysql_host": s.mysql.host,
        "mysql_port": s.mysql.port,
        "mysql_user": s.mysql.user,
        "mysql_database": s.mysql.database,
        "sync_mode": s.sync_mode,
        "last_sync_id": s.last_sync_id,
        "cloud_last_sync_id": s.cloud_last_sync_id,
        "cloud_api_url": s.cloud_api_url,
        "cloud_user_email": s.cloud_user_email,
        "dock_edge": s.dock_edge,
        "hotkey": s.hotkey,
        "is_floating": s.is_floating,
        "floating_position": list(s.floating_position) if s.floating_position else None,
        "language": s.language,
        "save_text": s.save_text,
        "save_images": s.save_images,
        "max_text_length": s.max_text_length,
        "max_image_size_kb": s.max_image_size_kb,
        "max_items": s.max_items,
        "retention_days": s.retention_days,
        "poll_interval_ms": s.poll_interval_ms,
        "active_profile": s.active_profile,
        "db_profiles": dict(s.db_profiles),
        "disabled_plugins": list(s.disabled_plugins),
    })
    return d


# ============ 路径 ============

def get_config_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif IS_MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_config_file() -> Path:
    return get_config_dir() / "settings.json"


def get_user_plugins_dir() -> Path:
    p = get_config_dir() / "plugins"
    p.mkdir(exist_ok=True)
    return p


# ============ SettingsStore ============

class SettingsStore:
    """线程安全的 AppSettings 运行时管理器。

    职责:
    - 首次 snapshot() 懒加载磁盘并生成 device_id/profile 等默认值
    - update() 原子生成新 snapshot 并排程落盘
    - 保留 extras dict 以兼容未知字段(secure_store base64 fallback)
    - 延迟落盘:主线程用 QTimer 合并 2s 写入;非主线程/无 Qt 直接同步落盘
    """

    _SAVE_DELAY_MS = 2000

    def __init__(self, path: Optional[Path] = None):
        self._path = path  # 惰性解析,避免模块导入时就创建目录
        self._lock = threading.RLock()
        self._snapshot: Optional[AppSettings] = None
        self._extras: dict = {}
        self._dirty = False
        self._save_timer = None

    def _resolve_path(self) -> Path:
        if self._path is None:
            self._path = get_config_file()
        return self._path

    def snapshot(self) -> AppSettings:
        with self._lock:
            if self._snapshot is None:
                self._load_locked()
                self._ensure_defaults_locked()
            return self._snapshot

    def _load_locked(self) -> None:
        path = self._resolve_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._snapshot, self._extras = _snapshot_from_dict(data)
                return
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"配置文件损坏或无法读取 ({path}): {e}")
        self._snapshot = AppSettings()
        self._extras = {}

    def _ensure_defaults_locked(self) -> None:
        """补全懒生成字段:device_id、device_name、首个 Default profile。"""
        s = self._snapshot
        changes: dict = {}
        if not s.device_id:
            changes["device_id"] = uuid.uuid4().hex[:16]
        if not s.device_name:
            changes["device_name"] = f"{platform.node()} ({platform.system()})"
        if not s.db_profiles:
            default_profile = {
                "db_type": s.db_type,
                "database_path": s.database_path,
                "mysql_host": s.mysql.host,
                "mysql_port": s.mysql.port,
                "mysql_user": s.mysql.user,
                "mysql_password": "",  # 密码走 keyring,不存 profile
                "mysql_database": s.mysql.database,
            }
            changes["db_profiles"] = {"Default": default_profile}
            if not s.active_profile:
                changes["active_profile"] = "Default"
        if changes:
            self._snapshot = replace(s, **changes)
            self._dirty = True
            # 启动路径懒加载期间, 不在此处同步 I/O; flush 交给调用者或 _schedule_save

    def update(self, **kwargs) -> AppSettings:
        """原子更新一或多个字段。返回新 snapshot。"""
        with self._lock:
            if self._snapshot is None:
                self._load_locked()
                self._ensure_defaults_locked()
            new = replace(self._snapshot, **kwargs)
            if new == self._snapshot:
                return self._snapshot
            self._snapshot = new
            self._dirty = True
        self._schedule_save()
        return self._snapshot

    def replace_snapshot(self, new_snapshot: AppSettings) -> AppSettings:
        """整体替换 snapshot。"""
        with self._lock:
            if self._snapshot is None:
                self._load_locked()
                self._ensure_defaults_locked()
            if new_snapshot == self._snapshot:
                return self._snapshot
            self._snapshot = new_snapshot
            self._dirty = True
        self._schedule_save()
        return self._snapshot

    def get_raw(self, key: str, default: Any = None) -> Any:
        """读取未被 AppSettings schema 覆盖的字段(供 secure_store fallback 使用)。"""
        with self._lock:
            if self._snapshot is None:
                self._load_locked()
                self._ensure_defaults_locked()
            return self._extras.get(key, default)

    def set_raw(self, key: str, value: Any) -> None:
        """写入未被 schema 覆盖的字段。仅限 secure_store 等基础设施使用。"""
        with self._lock:
            if self._snapshot is None:
                self._load_locked()
                self._ensure_defaults_locked()
            self._extras[key] = value
            self._dirty = True
        self._schedule_save()

    def export_dict(self) -> dict:
        """导出完整的 settings dict(含 extras)。供 settings_dialog 批量读写。"""
        with self._lock:
            if self._snapshot is None:
                self._load_locked()
                self._ensure_defaults_locked()
            return _snapshot_to_dict(self._snapshot, self._extras)

    def import_dict(self, data: dict) -> AppSettings:
        """导入完整 dict 并立即落盘。供 settings_dialog 批量写入。"""
        with self._lock:
            self._snapshot, self._extras = _snapshot_from_dict(data)
            self._dirty = False
            path, payload = self._capture_flush_payload_locked()
            snapshot = self._snapshot
        if payload is not None:
            self._write_payload(path, payload)
        return snapshot

    def flush(self) -> None:
        """手动触发落盘(应用退出时调用)。"""
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
            path, payload = self._capture_flush_payload_locked()
        if payload is not None:
            self._write_payload(path, payload)

    def _capture_flush_payload_locked(self):
        """锁内抓取 (path, serializable_dict) 快照。调用方持锁并负责写盘。"""
        if self._snapshot is None:
            return None, None
        return self._resolve_path(), _snapshot_to_dict(self._snapshot, self._extras)

    def _write_payload(self, path: Path, data: dict) -> None:
        """锁外 I/O：写文件失败仅记录日志并重置 dirty，让下次修改重新触发落盘。

        Why: 过去实现在 RLock 上手动 release/acquire，破坏重入语义；若持锁期间
        抛异常，还会导致 finally 尝试 acquire 未持有的锁。改为"锁内快照、锁外 I/O"
        的标准模式即可消除这类陷阱。
        """
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if not IS_WINDOWS:
                try:
                    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
        except IOError as e:
            logger.error(f"配置写入失败 ({path}): {e}")
            with self._lock:
                self._dirty = True

    def _schedule_save(self) -> None:
        """主线程用 QTimer 合并 2s 写入;非主线程/无 Qt 直接同步落盘。"""
        try:
            from PySide6.QtCore import QTimer, QThread, QCoreApplication
            app = QCoreApplication.instance()
            if app is None or QThread.currentThread() is not app.thread():
                self._sync_flush()
                return
            if self._save_timer is None:
                self._save_timer = QTimer()
                self._save_timer.setSingleShot(True)
                self._save_timer.timeout.connect(self._deferred_flush)
            if not self._save_timer.isActive():
                self._save_timer.start(self._SAVE_DELAY_MS)
        except (ImportError, RuntimeError):
            self._sync_flush()

    def _sync_flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
            path, payload = self._capture_flush_payload_locked()
        if payload is not None:
            self._write_payload(path, payload)

    def _deferred_flush(self) -> None:
        self._sync_flush()


# ============ 全局单例 + 便捷 API ============

_store = SettingsStore()


def get_store() -> SettingsStore:
    return _store


def settings() -> AppSettings:
    """获取当前 snapshot。调用可能触发首次磁盘加载。"""
    return _store.snapshot()


def update_settings(**kwargs) -> AppSettings:
    """原子更新一或多个字段,返回新 snapshot。"""
    return _store.update(**kwargs)


def replace_settings(new_snapshot: AppSettings) -> AppSettings:
    return _store.replace_snapshot(new_snapshot)


def flush_settings() -> None:
    _store.flush()


# settings_dialog 使用:整个 dict 的读/写
def load_settings_dict() -> dict:
    return _store.export_dict()


def save_settings_dict(data: dict) -> AppSettings:
    return _store.import_dict(data)


# secure_store 使用:任意 key-value(非 schema 字段)
def get_raw_setting(key: str, default: Any = None) -> Any:
    return _store.get_raw(key, default)


def set_raw_setting(key: str, value: Any) -> None:
    _store.set_raw(key, value)


# ============ 凭据(走 keyring,与 settings 分离) ============

def _retrieve_credential_safe(key: str) -> str:
    """读取凭据;解密失败时返回空串并告警(调用方视同未登录)。"""
    from utils.secure_store import retrieve_credential, CredentialDecryptError
    try:
        return retrieve_credential(key)
    except CredentialDecryptError as e:
        logger.error(f"凭据 '{key}' 存在但无法解密,视同未登录: {e}")
        return ""


def get_cloud_access_token() -> str:
    return _retrieve_credential_safe("cloud_access_token")


def set_cloud_access_token(token: str) -> None:
    from utils.secure_store import store_credential
    store_credential("cloud_access_token", token)


def get_cloud_refresh_token() -> str:
    return _retrieve_credential_safe("cloud_refresh_token")


def set_cloud_refresh_token(token: str) -> None:
    from utils.secure_store import store_credential
    store_credential("cloud_refresh_token", token)


def get_mysql_password() -> str:
    return _retrieve_credential_safe("mysql_password")


def set_mysql_password(password: str) -> None:
    from utils.secure_store import store_credential
    store_credential("mysql_password", password)


# ============ 校验 ============

def validate_cloud_api_url(url: str) -> None:
    """校验云端 API URL 的安全性(HTTPS + 域名白名单)。"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https" and hostname not in ("localhost", "127.0.0.1"):
        raise ValueError(f"云端 API 必须使用 HTTPS 协议: {url}")
    if hostname not in _ALLOWED_API_DOMAINS:
        raise ValueError(f"不允许的 API 域名: {hostname}")


def validate_mysql_database_name(name: str) -> bool:
    return bool(_DB_NAME_PATTERN.match(name))


# ============ 带校验/凭据的复合 setters ============

def set_cloud_api_url(url: str) -> None:
    validate_cloud_api_url(url)
    update_settings(cloud_api_url=url)


def set_sync_mode(mode: str) -> None:
    valid = {m.value for m in SyncMode}
    if mode in valid:
        update_settings(sync_mode=mode)
    else:
        logger.warning(f"无效的同步模式: {mode}")


def set_dock_edge(edge: str) -> None:
    if edge in ("left", "right", "top", "bottom"):
        update_settings(dock_edge=edge)
    else:
        logger.warning(f"无效的停靠边缘值: {edge}")


def set_db_type(db_type: str) -> None:
    if db_type in ("sqlite", "mysql"):
        update_settings(db_type=db_type)
    else:
        logger.warning(f"无效的数据库类型: {db_type}")


def set_mysql_config(host: str, port: int, user: str, password: str, database: str) -> None:
    """批量更新 MySQL 连接(密码走 keyring)。"""
    if database and not _DB_NAME_PATTERN.match(database):
        raise ValueError(f"不安全的数据库名(仅允许字母、数字、下划线): {database}")
    update_settings(mysql=MysqlConnection(host=host, port=port, user=user, database=database))
    set_mysql_password(password)


def get_mysql_config() -> dict:
    """返回兼容旧格式的 MySQL 配置 dict(含密码,供直连使用)。"""
    s = settings().mysql
    return {
        "host": s.host,
        "port": s.port,
        "user": s.user,
        "database": s.database,
        "password": get_mysql_password(),
    }


# ============ 特殊逻辑 ============

def get_default_hotkey() -> str:
    return "<cmd>+v"  # pynput: macOS 为 Cmd, Windows 为 Win 键


def get_effective_hotkey() -> str:
    """获取生效的 hotkey:用户设置 fallback 到平台默认。"""
    return settings().hotkey or get_default_hotkey()


def get_effective_database_path() -> str:
    """获取实际使用的 SQLite 数据库路径(空值 fallback 到 config_dir/clipboard.db)。"""
    p = settings().database_path
    if p:
        return p
    return str(get_config_dir() / "clipboard.db")


def is_plugin_enabled(plugin_id: str) -> bool:
    return plugin_id not in settings().disabled_plugins


def set_plugin_enabled(plugin_id: str, enabled: bool) -> None:
    current = set(settings().disabled_plugins)
    if enabled:
        current.discard(plugin_id)
    else:
        current.add(plugin_id)
    update_settings(disabled_plugins=tuple(current))


def apply_profile(name: str) -> None:
    """将指定 profile 的配置应用为顶级 settings。密码字段跳过(走 keyring)。"""
    s = settings()
    profile = s.db_profiles.get(name)
    if not profile:
        return
    new_mysql = MysqlConnection(
        host=profile.get("mysql_host", s.mysql.host),
        port=int(profile.get("mysql_port", s.mysql.port)),
        user=profile.get("mysql_user", s.mysql.user),
        database=profile.get("mysql_database", s.mysql.database),
    )
    update_settings(
        db_type=profile.get("db_type", s.db_type),
        database_path=profile.get("database_path", s.database_path),
        mysql=new_mysql,
        active_profile=name,
    )
