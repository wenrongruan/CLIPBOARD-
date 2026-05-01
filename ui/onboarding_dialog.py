"""首次启动 3 步引导：复制 → 热键唤出 → 找回。

设计原则：
- 极简，只覆盖主路径，不解释云同步/团队/插件等扩展能力。
- 任何路径退出（完成或跳过）都把 `settings.onboarding_done` 置 True。
- 不阻塞主窗口；新用户跳过即可。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)

from config import get_effective_hotkey, update_settings, flush_settings

logger = logging.getLogger(__name__)


class OnboardingDialog(QDialog):
    """3 步引导对话框。

    步骤：
      1. 提示用户复制任意一段文本（外部通过 advance_on_copy() 推进）。
      2. 提示当前热键（用户按下热键唤出窗口后，外部 advance_on_wake() 推进）。
      3. 提示点击列表第一条即可粘回；用户点击 完成 即结束。
    """

    finished_or_skipped = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._step = 1
        self.setWindowTitle("欢迎使用 SharedClipboard")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumSize(460, 300)
        self._setup_ui()
        self._render_step()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        self.slogan = QLabel("复制过的东西，再也不用找第二遍。")
        self.slogan.setStyleSheet("font-size:15px;font-weight:600;")
        self.slogan.setWordWrap(True)
        layout.addWidget(self.slogan)

        self.step_label = QLabel("")
        self.step_label.setStyleSheet("color:#aaa;font-size:11px;")
        layout.addWidget(self.step_label)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size:14px;font-weight:500;")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.body_label = QLabel("")
        self.body_label.setWordWrap(True)
        self.body_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        layout.addWidget(self.body_label, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.skip_btn = QPushButton("跳过")
        self.skip_btn.clicked.connect(self._on_skip)
        btn_row.addWidget(self.skip_btn)

        self.next_btn = QPushButton("我已复制 →")
        self.next_btn.setObjectName("okButton")
        self.next_btn.clicked.connect(self._on_next)
        btn_row.addWidget(self.next_btn)

        layout.addLayout(btn_row)

    def _render_step(self) -> None:
        self.step_label.setText(f"第 {self._step} 步 / 共 3 步")
        if self._step == 1:
            self.title_label.setText("先复制任意一段文本或图片")
            self.body_label.setText(
                "在任何地方选中文本或图片并按 Ctrl+C（macOS 上 ⌘+C）。"
                "SharedClipboard 会安静地把它记入历史。"
            )
            self.next_btn.setText("我已复制 →")
            self.next_btn.setEnabled(True)
        elif self._step == 2:
            hk = get_effective_hotkey() or "（请在设置中配置热键）"
            self.title_label.setText("用热键随时唤出主窗口")
            self.body_label.setText(
                f"按 {hk} 即可呼出剪贴板历史。\n"
                "想改热键？设置 → 热键。"
            )
            self.next_btn.setText("继续 →")
            self.next_btn.setEnabled(True)
        else:
            self.title_label.setText("点一下，就把它粘回去")
            self.body_label.setText(
                "在历史列表里点击任意一条，或按回车，"
                "内容会被复制回剪贴板，下次粘贴就是它。\n\n"
                "搜索、收藏、标签、同步都在主界面里——需要时再用，不打扰你。"
            )
            self.next_btn.setText("完成")
            self.next_btn.setEnabled(True)
            self.skip_btn.setVisible(False)
        # 文字长度可能比上一步多，强制按当前内容重算大小，避免下沿被裁掉
        self.adjustSize()

    # ---- 外部推进入口 ----

    def advance_on_copy(self) -> None:
        if self._step == 1:
            self._step = 2
            self._render_step()

    def advance_on_wake(self) -> None:
        if self._step == 2:
            self._step = 3
            self._render_step()

    # ---- 关闭路径 ----

    def _persist_done(self) -> None:
        try:
            update_settings(onboarding_done=True)
            flush_settings()
        except Exception as exc:
            logger.debug(f"保存 onboarding_done 失败: {exc}")

    def _on_next(self) -> None:
        if self._step < 3:
            self._step += 1
            self._render_step()
            return
        self._persist_done()
        self.finished_or_skipped.emit()
        self.accept()

    def _on_skip(self) -> None:
        self._persist_done()
        self.finished_or_skipped.emit()
        self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist_done()
        try:
            self.finished_or_skipped.emit()
        except Exception:
            pass
        super().closeEvent(event)
