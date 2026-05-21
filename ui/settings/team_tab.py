"""团队管理 Tab（v3.4）：仅在 Team / Super / Ultimate 档位可用。"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from config import PRICING_URL

logger = logging.getLogger(__name__)


class TeamTab(QWidget):
    """对应旧 SettingsDialog._build_team_tab。"""

    def __init__(
        self,
        ctx=None,
        parent=None,
        space_service=None,
        entitlement_service=None,
        cloud_api=None,
        **_legacy_kwargs,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self._space_service = space_service
        self._entitlement_service = entitlement_service
        self._cloud_api = cloud_api
        if ctx is not None:
            if self._space_service is None:
                self._space_service = getattr(ctx, "space_service", None)
            if self._entitlement_service is None:
                self._entitlement_service = getattr(ctx, "entitlement_service", None)
            if self._cloud_api is None:
                self._cloud_api = getattr(ctx, "cloud_api", None)
        self._team_space_list = None
        self._team_member_list = None
        self._team_enabled = self._build_ui()
        if self._team_enabled:
            self._refresh_team_spaces()

    def _build_ui(self) -> bool:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        desc = QLabel(
            "团队空间是可选协作增强；未启用或不可用时，本地剪贴板历史、搜索、收藏和热键仍可正常使用。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#aaa;font-size:12px;padding:0 0 6px 0;")
        layout.addWidget(desc)

        ent = None
        if self._entitlement_service is not None:
            try:
                ent = self._entitlement_service.current()
            except Exception:
                ent = None
        plan_val = ""
        if ent is not None and ent.plan is not None:
            plan_val = getattr(ent.plan, "value", str(ent.plan))

        team_enabled = plan_val in ("team", "super", "ultimate")

        if not team_enabled:
            tip = QLabel("升级到 Team 档位（或 Super / Ultimate）以解锁团队功能。")
            tip.setWordWrap(True)
            tip.setStyleSheet("color:#aaa;padding:16px;")
            layout.addWidget(tip)
            upgrade_btn = QPushButton("查看套餐")
            upgrade_btn.clicked.connect(self._open_pricing_page)
            layout.addWidget(upgrade_btn)
            layout.addStretch()
            return False

        # 上半区：team 空间列表 + 新建按钮
        spaces_label = QLabel("团队空间")
        spaces_label.setStyleSheet("color:#aaa;font-size:11px;font-weight:600;")
        layout.addWidget(spaces_label)

        self._team_space_list = QListWidget()
        self._team_space_list.itemSelectionChanged.connect(self._on_team_space_selected)
        layout.addWidget(self._team_space_list, 1)

        space_btn_row = QHBoxLayout()
        new_space_btn = QPushButton("新建空间")
        new_space_btn.clicked.connect(self._on_team_new_space)
        space_btn_row.addWidget(new_space_btn)
        invite_btn = QPushButton("邀请成员")
        invite_btn.clicked.connect(self._on_team_invite_member)
        space_btn_row.addWidget(invite_btn)
        space_btn_row.addStretch()
        layout.addLayout(space_btn_row)

        # 下半区：成员列表
        members_label = QLabel("成员")
        members_label.setStyleSheet("color:#aaa;font-size:11px;font-weight:600;")
        layout.addWidget(members_label)

        self._team_member_list = QListWidget()
        layout.addWidget(self._team_member_list, 1)
        return True

    def _refresh_team_spaces(self):
        if self._team_space_list is None:
            return
        self._team_space_list.clear()
        if self._space_service is None:
            return
        try:
            spaces = self._space_service.list_spaces()
        except Exception as exc:
            logger.debug(f"list_spaces 失败: {exc}")
            spaces = []
        for sp in spaces:
            label = f"{sp.name or sp.id[:8]}  ({sp.type})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, sp.id)
            self._team_space_list.addItem(item)

    def _on_team_space_selected(self):
        if self._team_member_list is None:
            return
        self._team_member_list.clear()
        item = self._team_space_list.currentItem()
        if item is None or self._space_service is None:
            return
        space_id = item.data(Qt.UserRole)
        try:
            members = self._space_service.list_members(space_id)
        except Exception as exc:
            logger.debug(f"list_members 失败: {exc}")
            members = []
        for m in members:
            self._team_member_list.addItem(f"{m.user_id}  [{m.role}]")

    def _on_team_new_space(self):
        if self._space_service is None:
            return
        name, ok = QInputDialog.getText(self, "新建团队空间", "空间名称：")
        if not ok or not name.strip():
            return
        try:
            self._space_service.create_space(name=name.strip(), type_="team")
        except Exception as exc:
            QMessageBox.warning(self, "创建失败", str(exc))
            return
        self._refresh_team_spaces()

    def _on_team_invite_member(self):
        if self._team_space_list is None:
            return
        item = self._team_space_list.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择一个团队空间。")
            return
        if self._cloud_api is None:
            QMessageBox.warning(self, "邀请失败", "未登录或云端服务不可用，请先登录。")
            return
        space_id = item.data(Qt.UserRole)
        email, ok = QInputDialog.getText(self, "邀请成员", "邀请成员邮箱：")
        if not ok or not email.strip():
            return
        role, ok = QInputDialog.getItem(
            self, "邀请角色", "成员权限：", ["editor", "viewer"], 0, False,
        )
        if not ok:
            return
        try:
            resp = self._cloud_api.invite_space_member(
                space_id=space_id, email=email.strip(), role=role,
            )
        except Exception as exc:
            QMessageBox.warning(self, "邀请失败", str(exc))
            return

        status = (resp or {}).get("status") or ""
        invite_url = (resp or {}).get("invitation_url") or ""
        if status == "invite_pending":
            self._show_invite_link(
                f"{email} 尚未注册，请把邀请链接复制并转发给对方：",
                invite_url,
            )
        elif status == "added":
            if invite_url:
                self._show_invite_link(
                    f"已把 {email} 加入空间。可把链接发给对方让 ta 通过链接进入：",
                    invite_url,
                )
            else:
                QMessageBox.information(self, "邀请成功", f"已邀请 {email} 加入空间。")
        else:
            QMessageBox.information(self, "邀请", resp.get("message") or "请求已提交。")
        self._on_team_space_selected()

    def _show_invite_link(self, prompt: str, url: str):
        if not url:
            QMessageBox.information(self, "邀请", prompt)
            return
        box = QMessageBox(self)
        box.setWindowTitle("邀请链接")
        box.setText(prompt)
        box.setInformativeText(url)
        copy_btn = box.addButton("复制链接", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is copy_btn:
            try:
                QGuiApplication.clipboard().setText(url)
            except Exception as exc:
                logger.debug(f"复制邀请链接失败: {exc}")

    def _open_pricing_page(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(PRICING_URL))
