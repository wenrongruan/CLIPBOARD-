"""本地文件沙盒存储工具：计算 sha256、复制进容器、security-scoped bookmark。

沙盒策略：用户通过 NSOpenPanel / 拖拽选择文件 → **立即**流式复制到沙盒容器
（`get_files_local_dir()/<sha[0:2]>/<sha>.bin`），随后所有读写都基于沙盒副本。
bookmark 仅用于"在 Finder 中定位源文件"这类辅助展示。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


_CHUNK = 1 << 20  # 1 MB


def sandbox_path_for(sha: str) -> Path:
    from config import get_files_local_dir
    root = Path(get_files_local_dir())
    sub = root / sha[:2]
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{sha}.bin"


def hash_and_copy_into_container(
    src_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Tuple[str, int, Path]:
    """一次 pass 同时计算 sha256 并写入沙盒副本，返回 (sha, size, dest_path)。

    大文件（GB 级）避免读两遍：先写到临时文件，算完 sha 后 os.replace 到最终路径。
    同 sha 并发导入时最后一次 replace 获胜，不做预存在检查（TOCTOU 无意义）。
    """
    from config import get_files_local_dir
    total = os.path.getsize(src_path)
    h = hashlib.sha256()
    done = 0
    tmp_root = Path(get_files_local_dir())
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = tmp_root / f".import-{os.getpid()}-{os.urandom(8).hex()}.tmp"
    try:
        with open(src_path, "rb") as fsrc, open(tmp, "wb") as fdst:
            while True:
                chunk = fsrc.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                fdst.write(chunk)
                done += len(chunk)
                if progress_cb:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass
        sha = h.hexdigest()
        dest = sandbox_path_for(sha)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return sha, total, dest


def remove_from_container(sha: str) -> None:
    try:
        sandbox_path_for(sha).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.debug("删除沙盒副本失败", exc_info=True)


def guess_mime(name: str) -> str:
    mt, _ = mimetypes.guess_type(name)
    return mt or "application/octet-stream"


# ========== macOS security-scoped bookmark ==========

def make_bookmark(path: str) -> Optional[bytes]:
    """仅 macOS 沙盒构建有效；其它平台返回 None 表示不使用 bookmark。"""
    try:
        from Foundation import NSURL  # type: ignore
    except Exception:
        return None
    try:
        url = NSURL.fileURLWithPath_(path)
        # 0x0800 = NSURLBookmarkCreationWithSecurityScope
        # 0x1000 = NSURLBookmarkCreationSecurityScopeAllowOnlyReadAccess
        options = 0x0800 | 0x1000
        data, err = url.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
            options, None, None, None,
        )
        if err is not None:
            logger.debug(f"创建 bookmark 失败: {err}")
            return None
        return bytes(data) if data is not None else None
    except Exception as e:
        logger.debug(f"创建 bookmark 异常: {e}")
        return None


def resolve_bookmark(blob: bytes) -> Optional[str]:
    """将 bookmark 解析回 POSIX 路径；失败返回 None。"""
    if not blob:
        return None
    try:
        from Foundation import NSURL, NSData  # type: ignore
    except Exception:
        return None
    try:
        data = NSData.dataWithBytes_length_(blob, len(blob))
        options = 0x0400  # NSURLBookmarkResolutionWithSecurityScope
        url, is_stale, err = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
            data, options, None, None, None,
        )
        if err is not None or url is None:
            return None
        path = url.path()
        return str(path) if path else None
    except Exception as e:
        logger.debug(f"解析 bookmark 异常: {e}")
        return None
