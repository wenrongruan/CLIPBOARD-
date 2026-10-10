"""可复用的云端登录表单组件"""

import html
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
)

from config import (
    normalize_cloud_api_url,
    set_cloud_api_url,
    settings,
)
from core.cloud_api import CloudAPIClient, CloudAPIError, rebuild_cloud_client_for_url
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 请求超过 20 秒时提示仍在等待，保持串行登录。
_LOGIN_WATCHDOG_MS = 20_000

# 登录请求串行执行，避免迟到结果覆盖另一账号的凭证。
_executor = ThreadPoolExecutor(max_workers=1)
_active_login_futures = set()


def active_login_futures():
    return tuple(_active_login_futures)


def _mask_email(email: str) -> str:
    """邮箱脱敏（a***@domain），Why: 邮箱属个人信息，不应明文进持久化日志。"""
    if not email or "@" not in email:
        return "<redacted>"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


class CloudLoginWidget(QWidget):
    """云端登录表单，可嵌入对话框或设置页。"""

    login_succeeded = Signal(dict)   # 登录成功，携带 API 返回结果
    login_failed = Signal(str)       # 登录失败，携带错误消息
    # 内部信号：后台线程 -> 主线程，传 (result_dict_or_None, error_message_or_empty)
    _login_done = Signal(int, object, str)

    def __init__(self, cloud_api: CloudAPIClient, parent=None, before_auth_change=None):
        super().__init__(parent)
        self.cloud_api = cloud_api
        self._before_auth_change = before_auth_change
        self._login_in_flight = False
        self._login_done.connect(self._handle_login_result)
        self._current_request_id = 0
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_login_timeout)
        self._auth_wait_timer = QTimer(self)
        self._auth_wait_timer.setInterval(50)
        self._setup_ui()

    def _setup_ui(self):
        # Why: 原先把 email/password/登录按钮/状态/注册链接全塞进同一个 QFormLayout，
        # 按钮与密码框之间只有单行 spacing，视觉上挤成一团；拆成 Form（输入）+ VBox（按钮/提示）
        # 两段后，按钮上方天然有一段留白，整体更易读。
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(0, 4, 0, 0)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setLabelAlignment(Qt.AlignLeft)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.jlike.com")
        self.url_edit.setText(settings().cloud_api_url or "https://www.jlike.com")
        self.url_edit.setMinimumHeight(30)
        self.url_edit.setToolTip(
            "云端服务器地址。默认 https://www.jlike.com；\n"
            "可改为自托管服务器或本地测试地址（http 仅限 localhost）。"
        )
        form_layout.addRow("服务器:", self.url_edit)

        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("your@email.com")
        self.email_edit.setMinimumHeight(30)
        form_layout.addRow("邮箱:", self.email_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密码")
        self.password_edit.setMinimumHeight(30)
        form_layout.addRow("密码:", self.password_edit)

        root.addLayout(form_layout)

        self.login_btn = QPushButton("登录")
        self.login_btn.setObjectName("okButton")
        self.login_btn.setMinimumHeight(36)
        self.login_btn.clicked.connect(self._do_login)
        root.addSpacing(2)
        root.addWidget(self.login_btn)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")
        root.addWidget(self.status_label)

        # 注册链接 —— 跟随服务器地址，自托管用户也能跳到对应站点
        link_style = "color: #58a6ff; text-decoration: none;"
        self._link_style = link_style
        self.register_label = QLabel()
        self.register_label.setOpenExternalLinks(True)
        self.register_label.setStyleSheet("color: #888888; font-size: 12px;")
        self._refresh_register_links(self.url_edit.text())
        self.url_edit.textChanged.connect(self._refresh_register_links)
        root.addWidget(self.register_label)

        # 回车键触发登录
        self.password_edit.returnPressed.connect(self._do_login)

    def _refresh_register_links(self, url: str):
        normalized = normalize_cloud_api_url(url) or "https://www.jlike.com"
        # Why 必须 HTML 转义：url_edit 是用户输入，register_label 是富文本 QLabel，
        # 未转义时输入 `x"><img src="file:///...` 之类内容即可注入标签。
        safe = html.escape(normalized, quote=True)
        style = html.escape(self._link_style, quote=True)
        self.register_label.setText(
            f'还没有账号？<a href="{safe}/account.html" style="{style}">去注册</a>'
            f'　|　<a href="{safe}/privacy.html" style="{style}">隐私协议</a>'
        )

    def _set_loading(self, loading: bool):
        self.login_btn.setEnabled(not loading)
        self.login_btn.setText("请稍候..." if loading else "登录")

    def _do_login(self):
        if self._login_in_flight:
            return
        email = self.email_edit.text().strip()
        password = self.password_edit.text()

        if not email or not password:
            self.status_label.setText("请输入邮箱和密码")
            return

        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            self.status_label.setText("邮箱格式不正确")
            return

        # 用户可能改了服务器地址：保存到 settings 并重建 client，让 login 走新域名
        try:
            new_url = normalize_cloud_api_url(self.url_edit.text())
        except Exception:
            new_url = ""
        if not new_url:
            self.status_label.setText("请填写服务器地址")
            return
        self._login_in_flight = True
        self._current_request_id += 1
        request_id = self._current_request_id
        self._set_loading(True)
        self.status_label.setText("正在等待上一账号的后台任务结束…")

        def start():
            from shiboken6 import isValid
            if isValid(self):
                try:
                    self._start_login(email, password, new_url, request_id)
                except Exception as exc:
                    logger.warning("无法开始登录请求: %s", exc)
                    self._handle_login_result(request_id, None, str(exc))

        if self._before_auth_change is not None:
            self._before_auth_change(start)
        else:
            def wait_turn():
                if any(not future.done() for future in active_login_futures()):
                    return
                self._auth_wait_timer.stop()
                self._auth_wait_timer.timeout.disconnect(wait_turn)
                start()
            self._auth_wait_timer.timeout.connect(wait_turn)
            self._auth_wait_timer.start()
            wait_turn()

    def _start_login(self, email, password, new_url, request_id):
        current_url = settings().cloud_api_url
        if new_url != current_url:
            try:
                set_cloud_api_url(new_url)
            except ValueError as e:
                self.status_label.setText(f"服务器地址无效：{e}")
                self._login_in_flight = False
                self._set_loading(False)
                return
            self.cloud_api = rebuild_cloud_client_for_url(new_url)
        else:
            # 即便 URL 没变，也确认当前 client 是用同一个 base_url 构造的；
            # 不一致就重建（例如老版本残留的旧实例）
            try:
                base_url = getattr(self.cloud_api, "base_url", None)
                if base_url is None and hasattr(self.cloud_api, "_http"):
                    base_url = self.cloud_api._http.base_url
                if base_url and urlparse(base_url).netloc != urlparse(new_url).netloc:
                    self.cloud_api = rebuild_cloud_client_for_url(new_url)
            except Exception:
                pass

        self._set_loading(True)
        self.status_label.setText("")

        api = self.cloud_api
        signal = self._login_done

        def _login_task():
            t0 = time.time()
            logger.debug(f"[Login#{request_id}] 开始请求云端登录 ({_mask_email(email)})")
            try:
                result = api.login(email, password)
                logger.debug(f"[Login#{request_id}] 登录成功，耗时 {time.time()-t0:.2f}s")
                signal.emit(request_id, result or {}, "")
            except CloudAPIError as e:
                logger.warning(f"[Login#{request_id}] 登录失败（API 错误）: {e}，耗时 {time.time()-t0:.2f}s")
                signal.emit(request_id, None, str(e))
            except Exception as e:
                logger.warning(f"[Login#{request_id}] 登录失败（未知错误）: {e!r}，耗时 {time.time()-t0:.2f}s", exc_info=True)
                signal.emit(request_id, None, f"连接失败: {e}")

        future = _executor.submit(_login_task)
        _active_login_futures.add(future)
        future.add_done_callback(_active_login_futures.discard)
        self._watchdog.start(_LOGIN_WATCHDOG_MS)

    def _on_login_timeout(self):
        """请求未结束时继续禁止重试，避免重叠请求写入不同账号的凭证。"""
        logger.warning(f"[Login#{self._current_request_id}] 登录请求仍未结束")
        self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")
        self.status_label.setText("登录响应较慢，仍在等待当前请求结束，请暂勿重复登录。")

    def _handle_login_result(self, request_id, result, error_msg: str):
        """在主线程中处理登录结果"""
        if request_id != self._current_request_id:
            return
        self._watchdog.stop()
        self._login_in_flight = False
        self._set_loading(False)
        if error_msg:
            self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")
            self.status_label.setText(error_msg)
            self._set_loading(False)
            self.login_failed.emit(error_msg)
            return

        self.status_label.setStyleSheet("color: #4ade80; font-size: 12px;")
        self.status_label.setText("登录成功！")
        self.login_btn.setText("已登录")
        self.login_succeeded.emit(result if isinstance(result, dict) else {})
