"""可复用的云端登录表单组件"""

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

# 兜底超时：若 20 秒内 worker 线程没有发回结果，强制重置 UI 并提示
_LOGIN_WATCHDOG_MS = 20_000

# 模块级单例线程池，避免每次登录创建新的 Executor；max_workers=2 防止前一个任务卡死阻塞新任务
_executor = ThreadPoolExecutor(max_workers=2)


class CloudLoginWidget(QWidget):
    """云端登录表单，可嵌入对话框或设置页。"""

    login_succeeded = Signal(dict)   # 登录成功，携带 API 返回结果
    login_failed = Signal(str)       # 登录失败，携带错误消息
    # 内部信号：后台线程 -> 主线程，传 (result_dict_or_None, error_message_or_empty)
    _login_done = Signal(object, str)

    def __init__(self, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.cloud_api = cloud_api
        self._login_done.connect(self._handle_login_result)
        self._current_request_id = 0
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_login_timeout)
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
        style = self._link_style
        self.register_label.setText(
            f'还没有账号？<a href="{normalized}/account.html" style="{style}">去注册</a>'
            f'　|　<a href="{normalized}/privacy.html" style="{style}">隐私协议</a>'
        )

    def _set_loading(self, loading: bool):
        self.login_btn.setEnabled(not loading)
        self.login_btn.setText("请稍候..." if loading else "登录")

    def _do_login(self):
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
        current_url = settings().cloud_api_url
        if new_url != current_url:
            try:
                set_cloud_api_url(new_url)
            except ValueError as e:
                self.status_label.setText(f"服务器地址无效：{e}")
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
        self._current_request_id += 1
        request_id = self._current_request_id
        signal = self._login_done

        def _login_task():
            t0 = time.time()
            logger.warning(f"[Login#{request_id}] 开始请求云端登录 ({email})")
            try:
                result = api.login(email, password)
                logger.warning(f"[Login#{request_id}] 登录成功，耗时 {time.time()-t0:.2f}s")
                signal.emit(result or {}, "")
            except CloudAPIError as e:
                logger.warning(f"[Login#{request_id}] 登录失败（API 错误）: {e}，耗时 {time.time()-t0:.2f}s")
                signal.emit(None, str(e))
            except Exception as e:
                logger.warning(f"[Login#{request_id}] 登录失败（未知错误）: {e!r}，耗时 {time.time()-t0:.2f}s", exc_info=True)
                signal.emit(None, f"连接失败: {e}")

        _executor.submit(_login_task)
        self._watchdog.start(_LOGIN_WATCHDOG_MS)

    def _on_login_timeout(self):
        """watchdog：worker 线程超时未返回，强制重置 UI"""
        logger.warning(f"[Login#{self._current_request_id}] 登录超时未返回，重置 UI")
        # 作废当前 request，避免迟到的结果覆盖
        self._current_request_id += 1
        self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")
        self.status_label.setText("登录超时，请检查网络后重试")
        self._set_loading(False)
        self.login_failed.emit("登录超时")

    def _handle_login_result(self, result, error_msg: str):
        """在主线程中处理登录结果"""
        self._watchdog.stop()
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
