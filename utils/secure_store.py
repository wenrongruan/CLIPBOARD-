"""
安全凭据存储模块

优先使用 keyring（系统级凭据管理），回退到 DPAPI（Windows）或 base64 混淆。
"""

import base64
import logging
import platform

logger = logging.getLogger(__name__)

_SERVICE_NAME = "SharedClipboard"

# 当前实际使用的凭据存储后端：'keyring' / 'dpapi' / 'base64' / 'unknown'
_active_backend: str = "unknown"


def _set_active_backend(backend: str):
    """设置当前活动后端，首次降级时打一次 warning（闭包去重，无需模块级标志）。"""
    global _active_backend
    if backend == _active_backend:
        return
    _active_backend = backend
    if backend != "keyring":
        _warn_degraded_once(backend)


def _make_warn_once():
    """闭包去重：首个降级后端打一次 warning，之后保持沉默。
    Why: 取代原 _backend_warned 全局布尔，把去重状态封闭在函数里。
    """
    warned = False

    def _warn(backend: str):
        nonlocal warned
        if warned:
            return
        logger.warning("凭据存储已降级到 %s，安全等级低于系统钥匙串。", backend)
        warned = True

    return _warn


_warn_degraded_once = _make_warn_once()


def get_active_backend() -> str:
    """返回当前凭据存储后端名称（'keyring' / 'dpapi' / 'base64' / 'unknown'）"""
    return _active_backend


def is_degraded() -> bool:
    """当前凭据存储是否降级（非 keyring；unknown 视为未定，不算降级）。"""
    return _active_backend not in ("keyring", "unknown")


class CredentialDecryptError(Exception):
    """已存在凭据但无法解密（DPAPI 解密失败、base64 损坏等）。
    调用方应将此区别于 "凭据不存在"，通常意味着密钥环或加密 key 发生变化，需提示用户重新登录。"""

# 尝试导入 keyring
try:
    import keyring
    _HAS_KEYRING = True
except ImportError:
    _HAS_KEYRING = False

# Windows DPAPI 回退
_HAS_DPAPI = False
if platform.system() == "Windows" and not _HAS_KEYRING:
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        _crypt32 = ctypes.windll.crypt32
        _kernel32 = ctypes.windll.kernel32
        _HAS_DPAPI = True
    except Exception as e:
        logger.debug(f"DPAPI 不可用: {e}")


def _make_blob(data: bytes) -> DATA_BLOB:
    """创建 DATA_BLOB，正确处理 ctypes 指针"""
    blob = DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                              ctypes.POINTER(ctypes.c_char))
    return blob


def _dpapi_encrypt(data: str) -> str:
    """使用 Windows DPAPI 加密"""
    raw = data.encode("utf-8")
    blob_in = _make_blob(raw)
    blob_out = DATA_BLOB()
    if _crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        _kernel32.LocalFree(blob_out.pbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    raise RuntimeError("DPAPI CryptProtectData failed")


def _dpapi_decrypt(encoded: str) -> str:
    """使用 Windows DPAPI 解密"""
    raw = base64.b64decode(encoded.removeprefix("dpapi:"))
    blob_in = _make_blob(raw)
    blob_out = DATA_BLOB()
    if _crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        _kernel32.LocalFree(blob_out.pbData)
        return decrypted.decode("utf-8")
    raise RuntimeError("DPAPI CryptUnprotectData failed")


def store_credential(key: str, value: str):
    """安全存储凭据"""
    if not value:
        delete_credential(key)
        return

    if _HAS_KEYRING:
        try:
            keyring.set_password(_SERVICE_NAME, key, value)
            _set_active_backend("keyring")
            return
        except Exception as e:
            logger.warning(f"keyring 存储失败，回退到其他方式: {e}")

    if _HAS_DPAPI:
        try:
            encrypted = _dpapi_encrypt(value)
            _write_to_config(key, encrypted)
            _set_active_backend("dpapi")
            return
        except Exception as e:
            logger.warning(f"DPAPI 加密失败，回退到 base64 混淆: {e}")

    # 最后回退：base64 混淆（非真正加密，但防止肉眼直读）
    obfuscated = "b64:" + base64.b64encode(value.encode("utf-8")).decode("ascii")
    _write_to_config(key, obfuscated)
    _set_active_backend("base64")


def retrieve_credential(key: str) -> str:
    """读取凭据"""
    if _HAS_KEYRING:
        try:
            value = keyring.get_password(_SERVICE_NAME, key)
            if value is not None:
                _set_active_backend("keyring")
                return value
        except Exception as e:
            logger.warning(f"keyring 读取失败: {e}")

    # 从配置文件读取（可能是 DPAPI 加密或 base64 混淆的）
    raw = _read_from_config(key)
    if not raw:
        return ""

    # 明文旧数据（兼容迁移）
    if not raw.startswith("dpapi:") and not raw.startswith("b64:"):
        # 自动迁移旧的明文凭据到加密存储
        store_credential(key, raw)
        return raw

    if raw.startswith("dpapi:") and _HAS_DPAPI:
        try:
            result = _dpapi_decrypt(raw)
            _set_active_backend("dpapi")
            return result
        except Exception as e:
            logger.error(f"DPAPI 解密凭据 '{key}' 失败: {e}")
            raise CredentialDecryptError(f"DPAPI 解密失败: {key}") from e

    if raw.startswith("b64:"):
        try:
            result = base64.b64decode(raw.removeprefix("b64:")).decode("utf-8")
            _set_active_backend("base64")
            return result
        except Exception as e:
            logger.error(f"base64 解码凭据 '{key}' 失败: {e}")
            raise CredentialDecryptError(f"base64 解码失败: {key}") from e

    return raw


def delete_credential(key: str):
    """删除凭据"""
    if _HAS_KEYRING:
        try:
            keyring.delete_password(_SERVICE_NAME, key)
        except Exception as e:
            logger.debug(f"keyring 删除凭据 '{key}' 失败（可能不存在）: {e}")
    _write_to_config(key, "")


def _write_to_config(key: str, value: str):
    """写入配置文件（用于 DPAPI/base64 回退）"""
    from config import set_raw_setting
    set_raw_setting(f"_secure_{key}", value)


def _read_from_config(key: str) -> str:
    """从配置文件读取"""
    from config import get_raw_setting
    # 先尝试新的 _secure_ 前缀键
    value = get_raw_setting(f"_secure_{key}", "")
    if value:
        return value
    # 兼容旧的明文键名
    return get_raw_setting(key, "")
