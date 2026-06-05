"""HttpClient.refresh_token 并发竞态回归。

复现"程序没退出却自动掉线"：access token 15 分钟到期后，多个后台线程
（剪贴板同步 worker、文件同步 worker 等共用同一个 HttpClient）会在同一时刻
集体撞 401 并各自调用 refresh_token()。而服务端 refresh token 是单次使用
（AuthController::refresh 里 `DELETE FROM refresh_tokens` 用完即焚）。

无锁时两个线程读到同一个旧 refresh token 并发去换：第一个成功轮换，第二个
拿已被消费的旧 token 撞 401 → refresh_token() 走清空分支把本地登录态抹掉
→ 用户"自动掉线"。

期望：加刷新锁 + 双重检查后，并发刷新绝不能清空登录态。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.cloud.http import HttpClient


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _SingleUseRefreshServer:
    """模拟单次使用的 /auth/refresh：旧 token 一旦被消费，再用即 401。

    每个刷新请求人为拖住 0.3s，制造两个线程并发持有同一旧 token 的竞态窗口。
    """

    def __init__(self):
        self._consumed: set[str] = set()
        self._lock = threading.Lock()
        self._issued = 1

    def post(self, url, json=None, timeout=None):  # 对齐 httpx.Client.post 签名
        rt = (json or {}).get("refresh_token", "")
        time.sleep(0.3)  # 拖住在途刷新，给并发线程留出读到同一旧 token 的窗口
        with self._lock:
            if rt in self._consumed:
                return _Resp(401, {"error": "Invalid or expired refresh token"})
            self._consumed.add(rt)
            self._issued += 1
            return _Resp(200, {
                "token": f"acc-{self._issued}",
                "refresh_token": f"ref-{self._issued}",
            })


def test_concurrent_refresh_does_not_clear_login_state():
    server = _SingleUseRefreshServer()
    with patch("core.cloud.http.set_cloud_access_token"), \
         patch("core.cloud.http.set_cloud_refresh_token"), \
         patch.object(HttpClient, "_update_auth_json"):
        http = HttpClient("https://www.example.com")
        real_client = http._client
        http._client = server  # type: ignore[assignment]  # 只用到 .post
        real_client.close()
        http.set_tokens("acc-1", "ref-1")

        results: list[bool] = []
        results_lock = threading.Lock()

        def worker():
            ok = http.refresh_token()
            with results_lock:
                results.append(ok)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(5)
        t2.join(5)

        # 核心断言：并发刷新后仍登录（token 未被任何一个线程清空）
        assert http.is_authenticated, "并发刷新把登录态清空了 —— 用户会自动掉线"
        assert http._refresh_token_str, "refresh token 被清空"
        # 两个线程都应视为刷新成功（一个真刷新，一个复用刚换好的新 token）
        assert all(results) and len(results) == 2, f"刷新结果异常: {results}"
