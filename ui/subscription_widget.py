"""订阅状态组件 — 嵌入设置对话框的「云端同步」选项卡"""

import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QProgressBar,
    QMessageBox,
)

from core.cloud_api import CloudAPIClient, CloudAPIError
from PySide6.QtCore import Signal as QtSignal

logger = logging.getLogger(__name__)


class SubscriptionWidget(QWidget):
    """订阅状态组件，显示当前套餐、用量和管理按钮"""

    logout_completed = QtSignal()  # 退出登录完成信号

    def __init__(self, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.cloud_api = cloud_api
        self._executor: ThreadPoolExecutor | None = None
        self._setup_ui()
        self._load_subscription()

    def closeEvent(self, event):
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
        super().closeEvent(event)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)

        # ===== 账户信息组 =====
        account_group = QGroupBox("账户信息")
        account_layout = QFormLayout(account_group)
        account_layout.setSpacing(10)

        from config import Config
        email = Config.get_cloud_user_email()

        self.email_label = QLabel(email or "未登录")
        self.email_label.setStyleSheet("color: #e8e8e8;")
        account_layout.addRow("邮箱:", self.email_label)

        self.plan_label = QLabel("加载中...")
        self.plan_label.setStyleSheet("color: #58a6ff; font-weight: bold;")
        account_layout.addRow("当前套餐:", self.plan_label)

        self.status_label = QLabel("--")
        self.status_label.setStyleSheet("color: #aaaaaa;")
        account_layout.addRow("状态:", self.status_label)

        layout.addWidget(account_group)

        # ===== 用量信息组 =====
        usage_group = QGroupBox("用量")
        usage_layout = QVBoxLayout(usage_group)
        usage_layout.setSpacing(10)

        # 条目用量
        items_layout = QHBoxLayout()
        items_layout.setSpacing(8)
        self.items_label = QLabel("剪贴板条目:")
        self.items_label.setStyleSheet("color: #e8e8e8;")
        items_layout.addWidget(self.items_label)
        self.items_count_label = QLabel("-- / --")
        self.items_count_label.setStyleSheet("color: #aaaaaa;")
        items_layout.addWidget(self.items_count_label)
        items_layout.addStretch()
        usage_layout.addLayout(items_layout)

        # 用量进度条
        self.usage_progress = QProgressBar()
        self.usage_progress.setRange(0, 100)
        self.usage_progress.setValue(0)
        self.usage_progress.setTextVisible(False)
        self.usage_progress.setFixedHeight(8)
        self.usage_progress.setStyleSheet("""
            QProgressBar {
                background-color: #3c3c3c;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 4px;
            }
        """)
        usage_layout.addWidget(self.usage_progress)

        # 设备数
        self.devices_label = QLabel("已注册设备: --")
        self.devices_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        usage_layout.addWidget(self.devices_label)

        layout.addWidget(usage_group)

        # ===== 操作按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.upgrade_btn = QPushButton("升级套餐")
        self.upgrade_btn.setObjectName("okButton")
        self.upgrade_btn.clicked.connect(self._open_pricing)
        btn_layout.addWidget(self.upgrade_btn)

        self.manage_btn = QPushButton("管理账户")
        self.manage_btn.clicked.connect(self._open_account)
        btn_layout.addWidget(self.manage_btn)

        self.logout_btn = QPushButton("退出登录")
        self.logout_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                border: 1px solid #ff6b6b;
                border-radius: 6px;
                padding: 4px 8px;
                color: #ff6b6b;
            }
            QPushButton:hover {
                background-color: rgba(255, 107, 107, 0.2);
            }
        """)
        self.logout_btn.clicked.connect(self._do_logout)
        btn_layout.addWidget(self.logout_btn)

        layout.addLayout(btn_layout)

        # 刷新按钮
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedWidth(80)
        self.refresh_btn.clicked.connect(self._load_subscription)
        refresh_layout.addWidget(self.refresh_btn)
        layout.addLayout(refresh_layout)

        layout.addStretch()

    def _reset_to_logged_out(self):
        """重置 UI 到未登录状态"""
        self.email_label.setText("未登录")
        self.plan_label.setText("未登录")
        self.status_label.setText("--")
        self.items_count_label.setText("-- / --")
        self.usage_progress.setValue(0)
        self.devices_label.setText("已注册设备: --")

    def _load_subscription(self):
        """加载订阅信息（HTTP 请求在后台线程执行）"""
        if not self.cloud_api.is_authenticated:
            self._reset_to_logged_out()
            return

        self.plan_label.setText("加载中...")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1)

        future = self._executor.submit(self._fetch_subscription)
        future.add_done_callback(
            lambda f: QTimer.singleShot(0, lambda: self._on_subscription_loaded(f))
        )

    def _fetch_subscription(self) -> dict:
        """在后台线程中获取订阅信息"""
        return self.cloud_api.get_subscription()

    def _on_subscription_loaded(self, future):
        """订阅信息加载完成回调（主线程）"""
        try:
            sub = future.result()

            # 套餐信息 — 兼容扁平和嵌套两种响应格式
            plan = sub.get("plan", "free")
            if isinstance(plan, dict):
                plan_name = plan.get("name", "免费版")
                max_items = plan.get("max_items", 30)
                max_devices = plan.get("max_devices", 2)
            else:
                plan_name_map = {"free": "免费版", "pro": "专业版", "premium": "高级版"}
                plan_name = plan_name_map.get(plan, str(plan))
                max_items = sub.get("max_records", 30)
                max_devices = sub.get("max_devices", 2)

            self.plan_label.setText(plan_name)

            status = sub.get("status", "active")
            status_map = {
                "active": "有效",
                "expired": "已过期",
                "cancelled": "已取消",
                "trial": "试用中",
            }
            self.status_label.setText(status_map.get(status, status))

            # 用量 — 兼容扁平和嵌套格式
            usage = sub.get("usage", {})
            if isinstance(usage, dict):
                items_count = usage.get("items_count", 0)
                devices_count = usage.get("devices_count", 0)
            else:
                items_count = sub.get("used_records", 0)
                devices_count = sub.get("used_devices", 0)

            self.items_count_label.setText(f"已用 {items_count}/{max_items} 条")

            if max_items > 0:
                percentage = min(int(items_count / max_items * 100), 100)
                self.usage_progress.setValue(percentage)

                # 用量高时变红
                chunk_color = "#f87171" if percentage >= 80 else "#0078d4"
                self.usage_progress.setStyleSheet(f"""
                    QProgressBar {{ background-color: #3c3c3c; border: none; border-radius: 4px; }}
                    QProgressBar::chunk {{ background-color: {chunk_color}; border-radius: 4px; }}
                """)

            # 设备数
            self.devices_label.setText(f"已注册设备: {devices_count}/{max_devices}")

        except CloudAPIError as e:
            self.plan_label.setText("加载失败")
            self.status_label.setText(str(e))
            logger.warning(f"加载订阅信息失败: {e}")
        except Exception as e:
            self.plan_label.setText("加载失败")
            logger.error(f"加载订阅信息异常: {e}")

    def _open_pricing(self):
        """打开套餐页面"""
        QDesktopServices.openUrl(QUrl("https://www.jlike.com/pricing.html"))

    def _open_account(self):
        """打开账户管理页面"""
        QDesktopServices.openUrl(QUrl("https://www.jlike.com/account.html"))

    def _do_logout(self):
        """退出登录"""
        reply = QMessageBox.question(
            self,
            "退出登录",
            "确定要退出云端账户吗？\n退出后将停止云端同步。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self.cloud_api.logout()
        except Exception as e:
            logger.warning(f"退出登录异常: {e}")

        self._reset_to_logged_out()
        self.logout_completed.emit()

        QMessageBox.information(self, "提示", "已退出云端账户，重启应用后生效。")
