"""订阅状态组件 — 嵌入设置对话框的「云端同步」选项卡"""

import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt
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
    _subscription_loaded = QtSignal(object)  # 后台线程加载完成信号

    def __init__(self, cloud_api: CloudAPIClient, parent=None):
        super().__init__(parent)
        self.cloud_api = cloud_api
        self._executor: ThreadPoolExecutor | None = None
        self._subscription_loaded.connect(self._on_subscription_loaded)
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

        # QGroupBox 内的 QLabel 和 QFormLayout 行标签在某些深色主题下默认色不可见，
        # 这里统一给 groupbox 后代样式，保证所有行标签/小提示在深色背景下看得清
        _group_style = (
            "QGroupBox{color:#e8e8e8;font-weight:600;border:1px solid #3c3c3c;"
            "border-radius:6px;margin-top:10px;padding:8px 10px 10px 10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}"
            "QGroupBox QLabel{color:#cbd5e1;background:transparent;}"
        )

        # ===== 账户信息组 =====
        account_group = QGroupBox("账户信息")
        account_group.setStyleSheet(_group_style)
        account_layout = QFormLayout(account_group)
        account_layout.setSpacing(10)
        account_layout.setLabelAlignment(Qt.AlignLeft)

        from config import settings
        email = settings().cloud_user_email

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
        usage_group.setStyleSheet(_group_style)
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

        # 文件存储（付费功能，未启用时显示「需要升级」）
        files_layout = QHBoxLayout()
        files_layout.setSpacing(8)
        files_caption = QLabel("文件存储:")
        files_caption.setStyleSheet("color: #e8e8e8;")
        files_layout.addWidget(files_caption)
        self.files_count_label = QLabel("-- / --")
        self.files_count_label.setStyleSheet("color: #aaaaaa;")
        files_layout.addWidget(self.files_count_label)
        files_layout.addStretch()
        usage_layout.addLayout(files_layout)

        self.files_usage_progress = QProgressBar()
        self.files_usage_progress.setRange(0, 100)
        self.files_usage_progress.setValue(0)
        self.files_usage_progress.setTextVisible(False)
        self.files_usage_progress.setFixedHeight(8)
        self.files_usage_progress.setStyleSheet("""
            QProgressBar {background-color:#3c3c3c;border:none;border-radius:4px;}
            QProgressBar::chunk {background-color:#0078d4;border-radius:4px;}
        """)
        usage_layout.addWidget(self.files_usage_progress)

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

        # 先用本地 EntitlementService 兜底展示，避免 HTTP 未返回前出现"空白套餐"
        self._fill_from_local_entitlement()

        self.plan_label.setText(self.plan_label.text() + "（刷新中...）")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1)

        future = self._executor.submit(self._fetch_subscription)
        future.add_done_callback(
            lambda f: self._subscription_loaded.emit(f)
        )

    def _fill_from_local_entitlement(self):
        """在云端响应到达前，先展示本地缓存的套餐/配额，避免空白。"""
        try:
            from core.entitlement_service import get_entitlement_service, Plan
            ent = get_entitlement_service().current()
            plan_name_map = {
                Plan.FREE: "免费版",
                Plan.BASIC: "Basic",
                Plan.SUPER: "Super",
                Plan.ULTIMATE: "Ultimate",
            }
            self.plan_label.setText(plan_name_map.get(ent.plan, str(ent.plan.value)))
            status_map = {"active": "有效", "expired": "已过期", "cancelled": "已取消",
                           "trial": "试用中", "inactive": "未激活"}
            self.status_label.setText(status_map.get(ent.status, ent.status or "--"))
            if ent.files_quota_bytes > 0:
                self.files_count_label.setText(
                    f"已用 {self._fmt_bytes(ent.files_used_bytes)} / {self._fmt_bytes(ent.files_quota_bytes)}"
                )
                pct = min(100, int(ent.files_used_bytes * 100 / max(1, ent.files_quota_bytes)))
                self.files_usage_progress.setValue(pct)
            else:
                self.files_count_label.setText("仅 Basic / Super / Ultimate 可用")
        except Exception as e:
            logger.debug(f"本地 entitlement 预填失败: {e}")

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        if n <= 0:
            return "0"
        if n >= (1 << 30):
            return f"{n / (1 << 30):.2f} GB"
        return f"{n / (1 << 20):.1f} MB"

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
                plan_name_map = {
                    "free": "免费版",
                    "basic": "Basic",
                    "super": "Super",
                    "ultimate": "Ultimate",
                }
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
            usage = sub.get("usage")
            if isinstance(usage, dict) and usage:
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

            # 文件存储用量（如果服务端下发，则展示；否则通过 EntitlementService 兜底）
            files_block = sub.get("files") if isinstance(sub.get("files"), dict) else {}
            files_used = int(files_block.get("used_bytes") or sub.get("files_used_bytes") or 0)
            files_quota = int(
                files_block.get("quota_bytes") or sub.get("files_quota_bytes") or 0
            )
            if files_quota == 0:
                try:
                    from core.entitlement_service import get_entitlement_service
                    ent = get_entitlement_service().current()
                    files_used = ent.files_used_bytes
                    files_quota = ent.files_quota_bytes
                except Exception:
                    pass

            def _fmt(n):
                if n <= 0:
                    return "0"
                if n >= (1 << 30):
                    return f"{n / (1 << 30):.2f} GB"
                return f"{n / (1 << 20):.1f} MB"

            if files_quota > 0:
                self.files_count_label.setText(f"已用 {_fmt(files_used)} / {_fmt(files_quota)}")
                pct = min(100, int(files_used * 100 / max(1, files_quota)))
                self.files_usage_progress.setValue(pct)
                color = "#0078d4" if pct < 80 else ("#fbbf24" if pct < 95 else "#f87171")
                self.files_usage_progress.setStyleSheet(
                    f"QProgressBar{{background-color:#3c3c3c;border:none;border-radius:4px;}}"
                    f"QProgressBar::chunk{{background-color:{color};border-radius:4px;}}"
                )
            else:
                self.files_count_label.setText("仅 Basic / Super / Ultimate 可用")
                self.files_usage_progress.setValue(0)

        except CloudAPIError as e:
            # 云端刷新失败但已有本地 entitlement 展示，只提示状态行
            logger.warning(f"加载订阅信息失败: {e}")
            self.status_label.setText(f"云端刷新失败: {e}")
            # 把"(刷新中...)"后缀去掉
            self.plan_label.setText(self.plan_label.text().replace("（刷新中...）", ""))
        except Exception as e:
            logger.error(f"加载订阅信息异常: {e}")
            self.status_label.setText(f"云端异常: {e}")
            self.plan_label.setText(self.plan_label.text().replace("（刷新中...）", ""))

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
            # 服务端登出失败时不能静默清本地，否则用户以为已撤销但 token 仍有效
            logger.warning(f"退出登录异常: {e}")
            force_reply = QMessageBox.question(
                self,
                "服务端未确认退出",
                (
                    "服务端未确认退出，可能因网络问题。\n"
                    "如担心账号安全，请前往 jlike.com 手动撤销会话。\n\n"
                    "是否仍在本地清除登录态？"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if force_reply != QMessageBox.Yes:
                return
            self._reset_to_logged_out()
            self.logout_completed.emit()
            QMessageBox.information(
                self,
                "提示",
                "已在本地清除登录态，但服务端会话可能仍有效，请自行到 jlike.com 撤销。",
            )
            return

        self._reset_to_logged_out()
        self.logout_completed.emit()

        QMessageBox.information(self, "提示", "已退出云端账户，重启应用后生效。")
