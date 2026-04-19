"""可复用的云端登录表单组件"""

import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
)

from core.cloud_api import CloudAPIClient, CloudAPIError

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
        form_layout = QFormLayout(self)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setLabelAlignment(Qt.AlignLeft)

        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("your@email.com")
        form_layout.addRow("邮箱:", self.email_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密码")
        form_layout.addRow("密码:", self.password_edit)

        self.login_btn = QPushButton("登录")
        self.login_btn.setObjectName("okButton")
        self.login_btn.setMinimumHeight(36)
        self.login_btn.clicked.connect(self._do_login)
        form_layout.addRow("", self.login_btn)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")
        form_layout.addRow("", self.status_label)

        # 注册链接
        link_style = "color: #58a6ff; text-decoration: none;"
        register_label = QLabel(
            f'还没有账号？<a href="https://www.jlike.com/account.html" style="{link_style}">去注册</a>'
            f'　|　<a href="https://www.jlike.com/privacy.html" style="{link_style}">隐私协议</a>'
        )
        register_label.setOpenExternalLinks(True)
        register_label.setStyleSheet("color: #888888; font-size: 12px;")
        form_layout.addRow("", register_label)

        # 回车键触发登录
        self.password_edit.returnPressed.connect(self._do_login)

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
