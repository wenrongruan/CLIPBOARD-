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
import re
import shutil
import stat
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


_CHUNK = 1 << 20  # 1 MB
_OFFICE_MIME_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# content_sha256 必须是 64 位小写/大写十六进制。
# Why 入口强制校验：sandbox_path_for 直接把 sha 拼进路径（root / sha[:2] / f"{sha}.bin"），
# 值来自云端返回的 content_sha256。若不校验，"../../x" 这类值配合
# mkdir(parents=True) 可以穿越沙盒容器写任意文件。
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class FileCopyCancelledError(InterruptedError):
    """用户取消文件导入；临时副本已清理。"""


def validate_sha256(sha) -> str:
    """校验并规范化 sha256（转小写）。非法值抛 ValueError。"""
    if not isinstance(sha, str) or _SHA256_RE.fullmatch(sha) is None:
        raise ValueError(f"非法 content_sha256: {sha!r}")
    return sha.lower()


def sandbox_path_for(sha: str) -> Path:
    sha = validate_sha256(sha)
    from config import get_files_local_dir
    root = Path(get_files_local_dir())
    sub = root / sha[:2]
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{sha}.bin"


def cleanup_legacy_open_views() -> int:
    """移除容器内全部旧打开视图硬链接，并隔离仍被旧 FD 持有的原件 inode。

    只读取规范的 <sha[:2]>/<sha>.bin，绝不以编辑过的打开视图作为原件来源。
    已损坏原件保留在隐藏隔离文件中；移除规范缓存路径供后续重新下载。
    返回删除的旧视图数量。可重复执行，独立视图和无硬链接原件不受影响。
    """
    from config import get_files_local_dir
    root = Path(get_files_local_dir())
    try:
        if not _is_plain_directory(root.lstat()):
            return 0
        if hasattr(os, "fwalk") and hasattr(os, "O_NOFOLLOW"):
            return _cleanup_legacy_open_views_posix(root)
        return _cleanup_legacy_open_views_portable(root)
    except FileNotFoundError:
        return 0
    except OSError:
        logger.warning("旧文件打开视图清理失败", exc_info=True)
        return 0


def _is_plain_directory(info) -> bool:
    # Windows junction 也是 reparse point；lstat 为目录不表示可以安全遍历。
    return (stat.S_ISDIR(info.st_mode)
            and not (getattr(info, "st_file_attributes", 0)
                     & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _copy_original_stream(source, target) -> str:
    digest = hashlib.sha256()
    while chunk := source.read(_CHUNK):
        target.write(chunk)
        digest.update(chunk)
    return digest.hexdigest()


def _cleanup_legacy_open_views_posix(root: Path) -> int:
    # dir_fd + O_NOFOLLOW 使检查后被替换的目录 symlink 也无法逃离容器。
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, dir_flags)
    origins = {}
    removed = 0
    try:
        for prefix in os.listdir(root_fd):
            if re.fullmatch(r"[0-9a-f]{2}", prefix) is None:
                continue
            try:
                prefix_fd = os.open(prefix, dir_flags, dir_fd=root_fd)
            except OSError:
                continue
            try:
                for name in os.listdir(prefix_fd):
                    sha = name[:-4] if name.endswith(".bin") else ""
                    if _SHA256_RE.fullmatch(sha) is None or sha[:2] != prefix:
                        continue
                    info = os.stat(name, dir_fd=prefix_fd, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                        inode = (info.st_dev, info.st_ino)
                        origins.setdefault(inode, []).append((prefix, name, sha))
            finally:
                os.close(prefix_fd)

        if not origins:
            return 0
        try:
            view_fd = os.open("open_view", dir_flags, dir_fd=root_fd)
        except OSError:
            view_fd = None
        if view_fd is not None:
            try:
                for _, _, names, directory_fd in os.fwalk(".", dir_fd=view_fd, follow_symlinks=False):
                    for name in names:
                        try:
                            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                            if (stat.S_ISREG(info.st_mode)
                                    and (info.st_dev, info.st_ino) in origins):
                                os.unlink(name, dir_fd=directory_fd)
                                removed += 1
                        except OSError:
                            logger.warning("旧打开视图硬链接删除失败", exc_info=True)
            finally:
                os.close(view_fd)

        # unlink 后 st_nlink 可能已变成 1，但旧编辑器 FD 仍指向该 inode。
        # 因而依据清理前快照原子替换，而非再次以当前链接数决定是否隔离。
        for inode, entries in origins.items():
            for prefix, name, sha in entries:
                prefix_fd = None
                tmp = f".detach-{os.urandom(8).hex()}.tmp"
                try:
                    prefix_fd = os.open(prefix, dir_flags, dir_fd=root_fd)
                    source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=prefix_fd)
                    with os.fdopen(source_fd, "rb") as source:
                        info = os.fstat(source.fileno())
                        if (info.st_dev, info.st_ino) != inode or not stat.S_ISREG(info.st_mode):
                            continue
                        target_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                            0o600, dir_fd=prefix_fd)
                        with os.fdopen(target_fd, "wb") as target:
                            digest = _copy_original_stream(source, target)
                    info = os.stat(name, dir_fd=prefix_fd, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) != inode:
                        continue
                    if digest == sha.lower():
                        os.replace(tmp, name, src_dir_fd=prefix_fd, dst_dir_fd=prefix_fd)
                    else:
                        quarantine = f".legacy-corrupt-{name}-{os.urandom(8).hex()}"
                        os.replace(name, quarantine, src_dir_fd=prefix_fd, dst_dir_fd=prefix_fd)
                        logger.warning("旧沙盒原件校验失败，已隔离缓存: %s", name)
                except OSError:
                    logger.warning("隔离旧沙盒原件 inode 失败: %s", name, exc_info=True)
                finally:
                    if prefix_fd is not None:
                        try:
                            os.unlink(tmp, dir_fd=prefix_fd)
                        except FileNotFoundError:
                            pass
                        finally:
                            os.close(prefix_fd)
        return removed
    finally:
        os.close(root_fd)


def _cleanup_legacy_open_views_portable(root: Path) -> int:
    # Windows 没有目录 FD：只遍历经过 lstat 的容器子目录，不跟随 symlink。
    origins = {}
    for prefix in root.iterdir():
        if re.fullmatch(r"[0-9a-f]{2}", prefix.name) is None or not _is_plain_directory(prefix.lstat()):
            continue
        for source in prefix.iterdir():
            sha = source.stem if source.suffix == ".bin" else ""
            if _SHA256_RE.fullmatch(sha) is None or sha[:2] != prefix.name:
                continue
            info = source.lstat()
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                origins.setdefault((info.st_dev, info.st_ino), []).append((source, sha))
    removed = 0
    views = root / "open_view"
    if views.exists() and _is_plain_directory(views.lstat()):
        for directory, directories, names in os.walk(views, followlinks=False):
            directories[:] = [name for name in directories
                              if _is_plain_directory((Path(directory) / name).lstat())]
            for name in names:
                view = Path(directory) / name
                info = view.lstat()
                if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) in origins:
                    view.unlink()
                    removed += 1
    for inode, entries in origins.items():
        for source, sha in entries:
            tmp = source.parent / f".detach-{os.urandom(8).hex()}.tmp"
            try:
                info = source.lstat()
                if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != inode:
                    continue
                with source.open("rb") as original, tmp.open("xb") as target:
                    digest = _copy_original_stream(original, target)
                if digest == sha.lower():
                    os.replace(tmp, source)
                else:
                    os.replace(source, source.parent / f".legacy-corrupt-{source.name}-{os.urandom(8).hex()}")
                    logger.warning("旧沙盒原件校验失败，已隔离缓存: %s", source.name)
            finally:
                tmp.unlink(missing_ok=True)
    return removed


def hash_and_copy_into_container(
    src_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    *,
    is_cancelled: Optional[Callable[[], bool]] = None,
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
    def check_cancelled():
        if is_cancelled is not None and is_cancelled():
            raise FileCopyCancelledError("文件导入已取消")

    try:
        check_cancelled()
        with open(src_path, "rb") as fsrc, open(tmp, "wb") as fdst:
            while True:
                check_cancelled()
                chunk = fsrc.read(_CHUNK)
                if not chunk:
                    break
                check_cancelled()
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
        check_cancelled()
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return sha, done, dest


def materialize_for_open(local_path: str, display_name: str) -> str:
    """把 `<sha>.bin` 暴露成带原始扩展名的副本，供系统 Launch Services 识别。

    在 `<files_local_dir>/open_view/<sha>/<原名>` 下创建独立副本。
    每次重新复制，避免旧硬链接或同大小的已编辑副本污染内容寻址原件。
    返回可直接交给 `open` / `QDesktopServices` 的路径。
    """
    from config import get_files_local_dir
    raw_name = os.path.basename(display_name or "").strip()
    # Why 不能只靠 basename：basename("..") 返回 ".."，直接拼路径等于往上级目录写。
    # display_name 来自云端返回的文件名，必须白名单化：剔除路径分隔符 / NUL /
    # 控制字符，落到 "." / ".." 时回退为 "file"。
    raw_name = re.sub(r"[\x00-\x1f\x7f]", "", raw_name)
    raw_name = raw_name.replace("/", "_").replace("\\", "_").replace("\x00", "")
    if raw_name in ("", ".", ".."):
        raw_name = "file"
    safe_name = raw_name
    sha_stem = Path(local_path).stem or "item"
    root = Path(get_files_local_dir()) / "open_view" / sha_stem
    root.mkdir(parents=True, exist_ok=True)
    dst = root / safe_name
    tmp = root / f".open-{os.urandom(8).hex()}.tmp"
    try:
        shutil.copyfile(local_path, tmp)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return str(dst)


def remove_from_container(sha: str, local_path: str | None = None) -> None:
    try:
        target = sandbox_path_for(sha)
        if local_path is not None and (not local_path or Path(local_path) != target):
            return
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        from config import get_files_local_dir
        shutil.rmtree(Path(get_files_local_dir()) / "open_view" / target.stem, ignore_errors=True)
    except FileNotFoundError:
        pass
    except OSError:
        logger.debug("删除沙盒副本失败", exc_info=True)


def guess_mime(name: str) -> str:
    # guess_type() lazily reads system MIME tables on its first call, including
    # /etc/apache2/mime.types on macOS. An App Store sandbox cannot read that
    # file. Accessing the stdlib's bundled types_map does no filesystem I/O.
    suffix = Path(name).suffix.lower()
    return _OFFICE_MIME_TYPES.get(suffix) or mimetypes.types_map.get(suffix) or "application/octet-stream"


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
