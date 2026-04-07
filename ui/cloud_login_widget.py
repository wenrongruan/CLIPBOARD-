"""可复用的云端登录表单组件"""

import re
import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
)

from core.cloud_api import CloudAPIClient, CloudAPIError

logger = logging.getLogger(__name__)

# 模块级单例线程池，避免每次登录创建新的 Executor
_executor = ThreadPoolExecutor(max_workers=1)


class CloudLoginWidget(QWidget):
    """云端登录表单，可嵌入对话框或设置页。"""

    login_succeeded = Signal(dict)   # 登录成功，携带 API 返回结果
    login_failed = Signal(str)       # 登录失败，携带错误消息
    _login_done = Signal(object)     # 内部信号：后台线程 -> 主线程

    def __init__(self, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.cloud_api = cloud_api
        self._login_done.connect(self._handle_login_result)
        self._setup_ui()

    def _setup_ui(self):
        form_layout = QFormLayout(self)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(0, 0, 0, 0)

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

        def _login_task():
            return api.login(email, password)

        future = _executor.submit(_login_task)
        future.add_done_callback(lambda f: self._login_done.emit(f))

    def _handle_login_result(self, future):
        """在主线程中处理登录结果"""
        try:
            result = future.result()
            self.status_label.setStyleSheet("color: #4ade80; font-size: 12px;")
            self.status_label.setText("登录成功！")
            self.login_btn.setText("已登录")
            self.login_succeeded.emit(result if result else {})
        except Exception as e:
            msg = str(e) if isinstance(e, CloudAPIError) else f"连接失败: {e}"
            self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")
            self.status_label.setText(msg)
            self._set_loading(False)
            self.login_failed.emit(msg)
