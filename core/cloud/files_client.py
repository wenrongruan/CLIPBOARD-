"""FilesClient：付费文件接口（单段 / multipart 上传 + 下载 + 去重 + 元数据）。

所有 OSS presigned URL 都先过 _validate_storage_url（HttpClient 上）。
单文件硬上限 1 GB（FILE_SIZE_HARD_LIMIT）；超过 32 MB 走 multipart。
"""

from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

import httpx

from core.cloud.http import CloudAPIError

if TYPE_CHECKING:  # pragma: no cover
    from core.cloud_api import CloudAPIClient

logger = logging.getLogger(__name__)


class FilesClient:
    """文件同步底层 HTTP（与 file_sync_service 配合）。"""

    def __init__(self, facade: "CloudAPIClient"):
        self._facade = facade
        self._http = facade._http

    def files_list(self, since_id: int, device_id: str, limit: int = 100) -> dict:
        """增量拉取文件列表，返回 {items: [...], has_more: bool}。"""
        response = self._facade._request(
            "GET", "/api/v1/files/sync",
            params={"since_id": since_id, "device_id": device_id, "limit": limit},
        )
        return response.json()

    def files_get_quota(self) -> dict:
        """返回 {plan, quota_bytes, used_bytes, max_file_size_bytes}"""
        response = self._facade._request("GET", "/api/v1/files/quota")
        return response.json()

    def files_request_upload(self, meta: dict) -> dict:
        """请求上传位点。服务端按 size 决定单段 / multipart，并返回 presigned URL（仅 OSS）。
        meta 必须包含 name / size / sha256；可选 mime_type / device_id / device_name。
        返回示例（单段）:
          {"file_id": 123, "cloud_id": 123, "upload_mode": "single",
           "upload_url": "...", "expires_at": 1712345678}
        multipart:
          {"file_id": 123, "cloud_id": 123, "upload_mode": "multipart",
           "parts": [{"part_number": 1, "url": "..."}, ...],
           "complete_url": "...", "expires_at": ...}
        """
        if int(meta.get("size", 0)) > self._http.FILE_SIZE_HARD_LIMIT:
            raise CloudAPIError("单文件不能超过 1 GB", 413)
        response = self._facade._request("POST", "/api/v1/files/upload", json=meta)
        return response.json()

    def files_complete_upload(self, cloud_id: int, etags: list) -> dict:
        """multipart 完成：上报每一段 etag，服务端确认并落 meta。"""
        response = self._facade._request(
            "POST", f"/api/v1/files/{cloud_id}/complete", json={"parts": etags},
        )
        return response.json()

    def files_get_download_url(self, cloud_id: int) -> str:
        response = self._facade._request("GET", f"/api/v1/files/{cloud_id}/download-url")
        return response.json().get("url", "")

    def files_update_meta(self, cloud_id: int, patch: dict) -> dict:
        response = self._facade._request("PATCH", f"/api/v1/files/{cloud_id}", json=patch)
        return response.json()

    def files_delete(self, cloud_id: int) -> bool:
        try:
            self._facade._request("DELETE", f"/api/v1/files/{cloud_id}")
            return True
        except CloudAPIError as e:
            logger.warning(f"删除云端文件失败 (cloud_id={cloud_id}): {e}")
            return False

    def upload_file_to_url(
        self,
        url: str,
        file_path: str,
        part_offset: int = 0,
        part_size: Optional[int] = None,
        progress_cb=None,
        extra_headers: Optional[dict] = None,
        default_content_type: Optional[str] = "application/octet-stream",
    ) -> str:
        """向 OSS presigned URL 发 PUT（支持分片）。

        - part_offset / part_size: multipart 切片位置；None 表示整个文件
        - progress_cb(sent_in_this_call, total_in_this_call): 每约 200 ms 或 1 MB 调用一次
        - default_content_type: 默认加在请求头里的 Content-Type；传 None 表示不发。
          OSS multipart UploadPart 的 presigned URL 通常不把 Content-Type 纳入签名，
          此时客户端若硬加会导致 V4 SignatureDoesNotMatch。
        返回响应 header 的 ETag（去引号）；非 2xx 抛 CloudAPIError。
        """
        if not self._http._validate_storage_url(url, self._http._ALLOWED_UPLOAD_DOMAINS):
            raise CloudAPIError(f"上传域名被拒绝: {url}", 0)

        size = os.path.getsize(file_path) if part_size is None else int(part_size)

        import time as _time
        sent = 0
        last_emit_ts = 0.0
        last_emit_sent = 0

        def _iter():
            nonlocal sent, last_emit_ts, last_emit_sent
            remaining = size
            chunk_bytes = 1 << 20  # 1 MB
            with open(file_path, "rb") as fp:
                if part_offset:
                    fp.seek(int(part_offset))
                while remaining > 0:
                    want = min(chunk_bytes, remaining)
                    data = fp.read(want)
                    if not data:
                        break
                    remaining -= len(data)
                    sent += len(data)
                    now = _time.monotonic()
                    if progress_cb is not None and (
                        now - last_emit_ts >= 0.2 or sent - last_emit_sent >= chunk_bytes
                    ):
                        try:
                            progress_cb(sent, size)
                        except Exception:
                            pass
                        last_emit_ts = now
                        last_emit_sent = sent
                    yield data

        request_headers = httpx.Headers({"Content-Length": str(size)})
        if default_content_type:
            request_headers["Content-Type"] = default_content_type
        if extra_headers:
            for key, value in extra_headers.items():
                if value is None:
                    continue
                request_headers[str(key)] = str(value)

        try:
            resp = self._http._client.put(
                url,
                content=_iter(),
                headers=request_headers,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=300.0, pool=300.0),
            )
        except httpx.HTTPError as e:
            raise CloudAPIError(f"OSS 上传失败: {e}", 0)

        if resp.status_code >= 400:
            raise CloudAPIError(
                f"OSS 上传返回 {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )
        # 发完最后一次进度，确保 UI 走到 100%
        if progress_cb is not None:
            try:
                progress_cb(size, size)
            except Exception:
                pass
        etag = resp.headers.get("ETag") or resp.headers.get("etag") or ""
        return etag.strip('"')

    def download_file_to(
        self, url: str, dest_path: str, progress_cb=None,
    ) -> int:
        """从 presigned URL 流式下载到本地文件；返回字节数。"""
        if not self._http._validate_storage_url(url, self._http._ALLOWED_DOWNLOAD_DOMAINS):
            raise CloudAPIError(f"下载域名被拒绝: {url}", 0)

        import time as _time
        total_bytes = 0
        expected = 0
        last_emit_ts = 0.0
        last_emit = 0
        tmp_path = dest_path + ".part"
        _success = False
        try:
            with self._http._client.stream(
                "GET", url,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=300.0),
            ) as resp:
                if resp.status_code >= 400:
                    raise CloudAPIError(
                        f"OSS 下载返回 {resp.status_code}", resp.status_code,
                    )
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    expected = int(cl)
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(1 << 20):
                        if not chunk:
                            continue
                        f.write(chunk)
                        total_bytes += len(chunk)
                        now = _time.monotonic()
                        if progress_cb is not None and (
                            now - last_emit_ts >= 0.2
                            or total_bytes - last_emit >= (1 << 20)
                        ):
                            try:
                                progress_cb(total_bytes, expected or total_bytes)
                            except Exception:
                                pass
                            last_emit_ts = now
                            last_emit = total_bytes
            os.replace(tmp_path, dest_path)
            _success = True
        except httpx.HTTPError as e:
            raise CloudAPIError(f"OSS 下载网络错误: {e}", 0)
        finally:
            if not _success:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        if progress_cb is not None:
            try:
                progress_cb(total_bytes, expected or total_bytes)
            except Exception:
                pass
        return total_bytes
