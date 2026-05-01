"""分享链接对话框。

流程：
- 构造时接收选中的 items、ShareService、space_id
- 第一页选择过期时间（1h / 24h / 7d / 30d），确认后调用 share_service.create_share_link
- 第二页显示返回的 URL + 复制按钮 + QR 码（qrcode 可选，缺失时只显示 URL）
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.models import ClipboardItem

logger = logging.getLogger(__name__)


_EXPIRY_OPTIONS = [
    ("1 小时", 3600),
    ("24 小时", 86400),
    ("7 天", 7 * 86400),
    ("30 天", 30 * 86400),
]


class ShareLinkDialog(QDialog):
    """创建共享链接的对话框。"""

    def __init__(
        self,
        items: List[ClipboardItem],
        share_service,
        space_id: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._items = list(items or [])
        self._share_service = share_service
        # Service 侧约定 space_id 是字符串；None 统一转成 ""
        self._space_id = space_id or ""
        self._result: Optional[dict] = None

        self.setWindowTitle("分享剪贴板条目")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        self._stack.addWidget(self._build_config_page())
        self._stack.addWidget(self._build_result_page())

        self._stack.setCurrentIndex(0)

    def _build_config_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(10)

        space_text = "个人空间" if not self._space_id else f"空间 {self._space_id[:8]}"
        info = QLabel(f"将分享 <b>{len(self._items)}</b> 条记录，来自 {space_text}")
        info.setTextFormat(Qt.RichText)
        v.addWidget(info)

        # 先告诉用户典型场景再选有效期；避免误以为这是团队协作入口
        scenario = QLabel(
            "适用场景：把这一组文本/图片发给同事、客户或自己其他设备一次性使用。\n"
            "链接到期后自动失效，可创建多个链接，互不影响。"
        )
        scenario.setStyleSheet("color:#aaa;font-size:11px;")
        scenario.setWordWrap(True)
        v.addWidget(scenario)

        expire_label = QLabel("链接有效期")
        expire_label.setStyleSheet("color:#aaa;font-size:11px;")
        v.addWidget(expire_label)

        self._expiry_group = QButtonGroup(self)
        for i, (label, seconds) in enumerate(_EXPIRY_OPTIONS):
            rb = QRadioButton(label)
            rb.setProperty("seconds", seconds)
            if i == 1:  # 默认 24 小时
                rb.setChecked(True)
            self._expiry_group.addButton(rb, i)
            v.addWidget(rb)

        v.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn is not None:
            ok_btn.setText("创建链接")
            ok_btn.setObjectName("okButton")
        buttons.accepted.connect(self._on_create_clicked)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(10)

        self._result_title = QLabel("链接已生成")
        self._result_title.setStyleSheet("color:#e8e8e8;font-size:14px;font-weight:600;")
        v.addWidget(self._result_title)

        url_row = QHBoxLayout()
        self._url_edit = QLineEdit()
        self._url_edit.setReadOnly(True)
        url_row.addWidget(self._url_edit, 1)
        self._copy_btn = QPushButton("复制")
        self._copy_btn.clicked.connect(self._copy_url)
        url_row.addWidget(self._copy_btn)
        v.addLayout(url_row)

        self._copied_label = QLabel("")
        self._copied_label.setStyleSheet("color:#7ccf7c;font-size:11px;")
        v.addWidget(self._copied_label)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setMinimumHeight(20)
        v.addWidget(self._qr_label)

        self._qr_hint = QLabel("")
        self._qr_hint.setStyleSheet("color:#888;font-size:11px;")
        self._qr_hint.setAlignment(Qt.AlignCenter)
        self._qr_hint.setWordWrap(True)
        v.addWidget(self._qr_hint)

        v.addStretch()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        v.addLayout(close_row)

        return page

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def _on_create_clicked(self) -> None:
        if self._share_service is None:
            QMessageBox.warning(self, "无法分享", "ShareService 不可用。")
            return

        checked = self._expiry_group.checkedButton()
        seconds = int(checked.property("seconds") or 86400) if checked else 86400

        item_ids = [i.id for i in self._items if i.id is not None]
        if not item_ids:
            QMessageBox.warning(self, "无法分享", "没有可分享的条目（item_id 为空）。")
            return

        try:
            result = self._share_service.create_share_link(
                space_id=self._space_id,
                item_ids=item_ids,
                expires_in_seconds=seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"创建 share link 失败: {exc}")
            QMessageBox.critical(self, "创建失败", f"创建分享链接失败：{exc}")
            return

        self._result = result or {}
        url = str(self._result.get("share_url") or "")
        token = str(self._result.get("token") or "")
        display = url or (f"token: {token}" if token else "")
        if not display:
            QMessageBox.warning(self, "创建失败", "云端未返回有效链接。")
            return

        self._url_edit.setText(display)
        self._render_qr(url or token)
        self._stack.setCurrentIndex(1)

    def _copy_url(self) -> None:
        text = self._url_edit.text()
        if not text:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._copied_label.setText("已复制到剪贴板")

    def _render_qr(self, text: str) -> None:
        if not text:
            self._qr_label.clear()
            self._qr_hint.setText("")
            return
        try:
            import qrcode  # type: ignore
        except ImportError:
            self._qr_label.clear()
            self._qr_hint.setText(
                "未安装 qrcode 库，如需二维码请执行：pip install qrcode[pil]"
            )
            return
        try:
            img = qrcode.make(text)
            buf = BytesIO()
            img.save(buf, format="PNG")
            pix = QPixmap()
            pix.loadFromData(buf.getvalue())
            if pix.isNull():
                self._qr_label.clear()
                self._qr_hint.setText("二维码生成失败")
                return
            # 最大 240x240
            pix = pix.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._qr_label.setPixmap(pix)
            self._qr_hint.setText("")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"qr render failed: {exc}")
            self._qr_label.clear()
            self._qr_hint.setText(f"二维码生成失败：{exc}")

    def get_result(self) -> Optional[dict]:
        return self._result


__all__ = ["ShareLinkDialog"]
