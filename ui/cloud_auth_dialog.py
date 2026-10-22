"""云端登录/注册对话框"""

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
)

from .theme import follow_system_theme
from .cloud_login_widget import CloudLoginWidget
from core.cloud_api import CloudAPIClient
from ui.styles import theme_style

logger = logging.getLogger(__name__)


class CloudAuthDialog(QDialog):
    """云端登录/注册对话框，使用应用统一主题"""

    def __init__(self, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.cloud_api = cloud_api
        self._auth_result = None

        self.setWindowTitle("云端登录")
        self.setMinimumSize(420, 440)
        self.resize(440, 460)
        follow_system_theme(self)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel("云端登录")
        title.setStyleSheet(theme_style("font-size: 18px; font-weight: bold; color: $text;"))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("登录以启用跨设备云端同步")
        subtitle.setStyleSheet(theme_style("color: $muted; font-size: 12px;"))
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # 复用登录表单组件
        controller = getattr(self.parentWidget(), "cloud_controller", None)
        self._login_widget = CloudLoginWidget(
            self.cloud_api, before_auth_change=getattr(controller, "prepare_auth_change", None),
        )
        self._login_widget.login_succeeded.connect(self._on_login_succeeded)
        layout.addWidget(self._login_widget)

        layout.addStretch()

    def _on_login_succeeded(self, result: dict):
        self.cloud_api = self._login_widget.cloud_api
        self._auth_result = result
        QTimer.singleShot(500, self.accept)

    def get_auth_result(self) -> dict:
        """获取认证结果"""
        return self._auth_result
