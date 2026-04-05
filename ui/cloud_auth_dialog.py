"""云端登录/注册对话框"""

import logging
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QTabWidget,
    QWidget,
)

from .styles import MAIN_STYLE
from core.cloud_api import CloudAPIClient, CloudAPIError

logger = logging.getLogger(__name__)


class CloudAuthDialog(QDialog):
    """云端登录/注册对话框，使用项目暗色主题"""

    def __init__(self, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.cloud_api = cloud_api
        self._auth_result = None  # 登录/注册成功后的结果数据

        self.setWindowTitle("云端账户")
        self.setFixedSize(420, 380)
        self.setStyleSheet(MAIN_STYLE)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel("云端同步")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("登录或注册以启用跨设备云端同步")
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # Tab 切换：登录 / 注册
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # ===== 登录 Tab =====
        login_tab = QWidget()
        login_layout = QFormLayout(login_tab)
        login_layout.setSpacing(12)
        login_layout.setContentsMargins(12, 16, 12, 16)

        self.login_email = QLineEdit()
        self.login_email.setPlaceholderText("your@email.com")
        login_layout.addRow("邮箱:", self.login_email)

        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.Password)
        self.login_password.setPlaceholderText("密码")
        login_layout.addRow("密码:", self.login_password)

        self.login_btn = QPushButton("登录")
        self.login_btn.setObjectName("okButton")
        self.login_btn.setMinimumHeight(36)
        self.login_btn.clicked.connect(self._do_login)
        login_layout.addRow("", self.login_btn)

        self.login_status = QLabel("")
        self.login_status.setWordWrap(True)
        self.login_status.setStyleSheet("color: #f87171; font-size: 12px;")
        login_layout.addRow("", self.login_status)

        self.tab_widget.addTab(login_tab, "登录")

        # ===== 注册 Tab =====
        register_tab = QWidget()
        register_layout = QFormLayout(register_tab)
        register_layout.setSpacing(12)
        register_layout.setContentsMargins(12, 16, 12, 16)

        self.reg_email = QLineEdit()
        self.reg_email.setPlaceholderText("your@email.com")
        register_layout.addRow("邮箱:", self.reg_email)

        self.reg_password = QLineEdit()
        self.reg_password.setEchoMode(QLineEdit.Password)
        self.reg_password.setPlaceholderText("至少 6 个字符")
        register_layout.addRow("密码:", self.reg_password)

        self.reg_confirm = QLineEdit()
        self.reg_confirm.setEchoMode(QLineEdit.Password)
        self.reg_confirm.setPlaceholderText("再次输入密码")
        register_layout.addRow("确认密码:", self.reg_confirm)

        self.reg_display_name = QLineEdit()
        self.reg_display_name.setPlaceholderText("可选")
        register_layout.addRow("显示名称:", self.reg_display_name)

        self.register_btn = QPushButton("注册")
        self.register_btn.setObjectName("okButton")
        self.register_btn.setMinimumHeight(36)
        self.register_btn.clicked.connect(self._do_register)
        register_layout.addRow("", self.register_btn)

        self.register_status = QLabel("")
        self.register_status.setWordWrap(True)
        self.register_status.setStyleSheet("color: #f87171; font-size: 12px;")
        register_layout.addRow("", self.register_status)

        self.tab_widget.addTab(register_tab, "注册")

        # 回车键触发
        self.login_password.returnPressed.connect(self._do_login)
        self.reg_confirm.returnPressed.connect(self._do_register)

    def _set_loading(self, loading: bool):
        """切换加载状态"""
        self.login_btn.setEnabled(not loading)
        self.register_btn.setEnabled(not loading)
        if loading:
            self.login_btn.setText("请稍候...")
            self.register_btn.setText("请稍候...")
        else:
            self.login_btn.setText("登录")
            self.register_btn.setText("注册")

    def _validate_email(self, email: str) -> bool:
        """简单校验邮箱格式"""
        return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))

    def _execute_auth(self, status_label: QLabel, success_text: str, api_call):
        """执行认证请求的通用逻辑"""
        self._set_loading(True)
        status_label.setText("")

        try:
            result = api_call()
            self._auth_result = result
            status_label.setStyleSheet("color: #4ade80; font-size: 12px;")
            status_label.setText(success_text)
            QTimer.singleShot(500, self.accept)
        except CloudAPIError as e:
            status_label.setStyleSheet("color: #f87171; font-size: 12px;")
            status_label.setText(str(e))
            self._set_loading(False)
        except Exception as e:
            status_label.setStyleSheet("color: #f87171; font-size: 12px;")
            status_label.setText(f"连接失败: {e}")
            self._set_loading(False)

    def _do_login(self):
        """执行登录"""
        email = self.login_email.text().strip()
        password = self.login_password.text()

        if not email or not password:
            self.login_status.setText("请输入邮箱和密码")
            return

        if not self._validate_email(email):
            self.login_status.setText("邮箱格式不正确")
            return

        self._execute_auth(
            self.login_status, "登录成功！",
            lambda: self.cloud_api.login(email, password),
        )

    def _do_register(self):
        """执行注册"""
        email = self.reg_email.text().strip()
        password = self.reg_password.text()
        confirm = self.reg_confirm.text()
        display_name = self.reg_display_name.text().strip() or None

        if not email or not password:
            self.register_status.setText("请输入邮箱和密码")
            return

        if not self._validate_email(email):
            self.register_status.setText("邮箱格式不正确")
            return

        if len(password) < 6:
            self.register_status.setText("密码至少需要 6 个字符")
            return

        if password != confirm:
            self.register_status.setText("两次输入的密码不一致")
            return

        self._execute_auth(
            self.register_status, "注册成功！",
            lambda: self.cloud_api.register(email, password, display_name),
        )

    def get_auth_result(self) -> dict:
        """获取认证结果"""
        return self._auth_result
