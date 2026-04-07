"""
安全凭据存储模块

优先使用 keyring（系统级凭据管理），回退到 DPAPI（Windows）或 base64 混淆。
"""

import base64
import logging
import platform

logger = logging.getLogger(__name__)

_SERVICE_NAME = "SharedClipboard"

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
    except Exception:
        pass


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
            return
        except Exception as e:
            logger.warning(f"keyring 存储失败，回退到其他方式: {e}")

    if _HAS_DPAPI:
        try:
            encrypted = _dpapi_encrypt(value)
            _write_to_config(key, encrypted)
            return
        except Exception as e:
            logger.warning(f"DPAPI 加密失败，回退到 base64 混淆: {e}")

    # 最后回退：base64 混淆（非真正加密，但防止肉眼直读）
    obfuscated = "b64:" + base64.b64encode(value.encode("utf-8")).decode("ascii")
    _write_to_config(key, obfuscated)


def retrieve_credential(key: str) -> str:
    """读取凭据"""
    if _HAS_KEYRING:
        try:
            value = keyring.get_password(_SERVICE_NAME, key)
            if value is not None:
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
            return _dpapi_decrypt(raw)
        except Exception as e:
            logger.error(f"DPAPI 解密失败: {e}")
            return ""

    if raw.startswith("b64:"):
        try:
            return base64.b64decode(raw.removeprefix("b64:")).decode("utf-8")
        except Exception:
            return ""

    return raw


def delete_credential(key: str):
    """删除凭据"""
    if _HAS_KEYRING:
        try:
            keyring.delete_password(_SERVICE_NAME, key)
        except Exception:
            pass
    _write_to_config(key, "")


def _write_to_config(key: str, value: str):
    """写入配置文件（用于 DPAPI/base64 回退）"""
    from config import Config
    Config.set_setting(f"_secure_{key}", value)


def _read_from_config(key: str) -> str:
    """从配置文件读取"""
    from config import Config
    # 先尝试新的 _secure_ 前缀键
    value = Config.get_setting(f"_secure_{key}", "")
    if value:
        return value
    # 兼容旧的明文键名
    return Config.get_setting(key, "")
