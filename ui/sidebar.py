"""左侧栏：Space 切换 + 标签过滤 + 保存的搜索 + 升级入口。

职责：
- 列出个人空间 + 已知 team spaces，切换时 emit space_changed(space_id or None)
- 列出当前 space 的标签，选中时 emit tag_filter_changed(tag_id or None)
- 提供"新建 Space"、"管理团队"、"升级"按钮

折叠：
- 标题行右侧的 ‹/› 按钮可把整块内容收进 36px 窄轨道，给右侧列表让出宽度
- 状态写入 settings.sidebar_collapsed，重启后保持

注意：
- 所有 service 调用都 try/except 兜底，避免未登录/schema 缺失时崩溃
- 个人空间统一用 space_id=None 表示（SpaceService 的约定）
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# 展开 / 折叠态的侧栏宽度（px）。
# 折叠态 = 只剩一条窄轨道放切换按钮，展开态 = 原来的 200px。
EXPANDED_WIDTH = 200
COLLAPSED_WIDTH = 38
# 折叠动画时长（ms）；太慢会挡住用户连续操作
TOGGLE_DURATION = 160


class Sidebar(QWidget):
    """左侧空间 / 标签 / 升级入口面板。"""

    space_changed = Signal(object)          # str or None
    tag_filter_changed = Signal(object)     # str or None
    create_space_requested = Signal()
    manage_team_requested = Signal()
    upgrade_requested = Signal()
    collapsed_changed = Signal(bool)        # True = 已折叠成窄轨道

    def __init__(
        self,
        space_service=None,
        tag_service=None,
        entitlement_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self._space_service = space_service
        self._tag_service = tag_service
        self._entitlement_service = entitlement_service
        self._spaces: list = []               # [Space]，与 combo index 对齐（0 号是个人空间占位）
        self._suppress_space_signal = False
        self._suppress_tag_signal = False
        self._collapsed = self._read_saved_collapsed()
        self.setObjectName("sidebar")
        # 折叠靠动画改 min/maxWidth，这里先把策略放开，否则 QHBoxLayout 会把宽度钉死
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._setup_ui()
        # 首帧直接落到目标宽度（不做动画），避免启动瞬间看到一次无意义的收缩
        self.set_collapsed(self._collapsed, animate=False, persist=False)
        self.refresh_spaces()
        self.refresh_tags(None)
        self._refresh_entitlement_ui()

    # ------------------------------------------------------------------
    # 折叠状态
    # ------------------------------------------------------------------

    @staticmethod
    def _read_saved_collapsed() -> bool:
        """读取上次的折叠状态；配置不可用时按展开处理。"""
        try:
            from config import settings as _settings
            return bool(getattr(_settings(), "sidebar_collapsed", False))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"读取 sidebar_collapsed 失败: {exc}")
            return False

    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        """折叠 / 展开标签栏。"""
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool, *, animate: bool = True, persist: bool = True) -> None:
        """切换折叠态。

        animate=False 用于构造期首帧；persist=False 用于不希望回写配置的调用方。
        """
        collapsed = bool(collapsed)
        changed = collapsed != self._collapsed
        self._collapsed = collapsed

        self._content.setVisible(not collapsed)
        self.header_label.setVisible(not collapsed)
        self.collapse_btn.setText("›" if collapsed else "‹")
        self.collapse_btn.setToolTip("展开标签栏" if collapsed else "折叠标签栏")

        target = COLLAPSED_WIDTH if collapsed else EXPANDED_WIDTH
        if animate and changed:
            self._animate_width(target)
        else:
            self._set_width_now(target)

        if changed and persist:
            self._persist_collapsed(collapsed)
        if changed:
            self.collapsed_changed.emit(collapsed)

    @staticmethod
    def _persist_collapsed(collapsed: bool) -> None:
        try:
            from config import update_settings
            update_settings(sidebar_collapsed=collapsed)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"保存 sidebar_collapsed 失败: {exc}")

    def _set_width_now(self, width: int) -> None:
        self._width_group.stop()
        self.setFixedWidth(width)

    def _animate_width(self, target: int) -> None:
        """对 min/maxWidth 同时做补间。

        Why 不能只动 maximumWidth：折叠时内容已隐藏，sizeHint 会瞬间塌到几像素，
        布局立刻把宽度钳到那么小 —— 看起来就是"啪"地闪一下。minimumWidth 一起补间
        才能让宽度真正平滑地跟着动画走。
        """
        start = self.width()
        if start == target:
            self._set_width_now(target)
            return
        self._width_group.stop()
        for idx in range(self._width_group.animationCount()):
            anim = self._width_group.animationAt(idx)
            anim.setStartValue(start)
            anim.setEndValue(target)
        self._width_group.start()

    # ------------------------------------------------------------------
    # UI 构造
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- 标题行：标题 + 折叠按钮（这一行始终可见，折叠后只剩按钮）---
        # Why 包一层 QWidget 再 addWidget(..., Qt.AlignTop)：折叠时 _content 被隐藏，
        # 外层 QVBoxLayout 没有任何可伸展的项，会把剩余高度均分给所有 item，
        # 按钮就被推到面板正中。加上 AlignTop 后这一行严格按 sizeHint 贴顶。
        self._header = QWidget()
        self._header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.header_label = QLabel("标签")
        self.header_label.setStyleSheet("color:#aaa;font-size:11px;font-weight:600;")
        header.addWidget(self.header_label)
        header.addStretch(1)

        self.collapse_btn = QPushButton("‹")
        self.collapse_btn.setObjectName("sidebarToggleBtn")
        # 折叠态宽度 38 - 左右各 8 的外边距 = 22，正好是这个按钮 —— 再把命中区放大就放不下了
        self.collapse_btn.setFixedSize(22, 22)
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.setToolTip("折叠标签栏")
        self.collapse_btn.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.collapse_btn)

        layout.addWidget(self._header, 0, Qt.AlignTop)

        # --- 可折叠内容：标签列表 / 空间 / 团队 / 升级入口 ---
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # 标签树（主路径）
        self.tag_list = QListWidget()
        self.tag_list.setSelectionMode(QListWidget.SingleSelection)
        self.tag_list.itemSelectionChanged.connect(self._on_tag_selection_changed)
        content_layout.addWidget(self.tag_list, 1)

        # --- Space 切换（默认隐藏；登录且存在非个人 space 时再显示）---
        self.space_section = QWidget()
        space_layout = QVBoxLayout(self.space_section)
        space_layout.setContentsMargins(0, 0, 0, 0)
        space_layout.setSpacing(4)

        space_label = QLabel("空间")
        space_label.setStyleSheet("color:#aaa;font-size:11px;font-weight:600;")
        space_layout.addWidget(space_label)

        space_row = QHBoxLayout()
        space_row.setSpacing(4)
        self.space_combo = QComboBox()
        self.space_combo.currentIndexChanged.connect(self._on_space_index_changed)
        space_row.addWidget(self.space_combo, 1)

        self.create_space_btn = QPushButton("+")
        self.create_space_btn.setFixedSize(22, 22)
        self.create_space_btn.setToolTip("新建空间")
        self.create_space_btn.clicked.connect(self._on_create_space_clicked)
        space_row.addWidget(self.create_space_btn)

        space_layout.addLayout(space_row)
        content_layout.addWidget(self.space_section)
        self.space_section.setVisible(False)

        # --- 团队（按权益显示）---
        self.manage_team_btn = QPushButton("管理团队")
        self.manage_team_btn.clicked.connect(self.manage_team_requested.emit)
        content_layout.addWidget(self.manage_team_btn)
        self.manage_team_btn.setVisible(False)

        # --- 升级 / 了解云端增强（默认隐藏；登录且非 Team 档位时再显示）---
        self.upgrade_btn = QPushButton("了解云端增强")
        self.upgrade_btn.setObjectName("okButton")
        self.upgrade_btn.clicked.connect(self.upgrade_requested.emit)
        content_layout.addWidget(self.upgrade_btn)
        self.upgrade_btn.setVisible(False)

        layout.addWidget(self._content, 1)

        # --- 宽度补间：min/maxWidth 一起动（见 _animate_width 注释）---
        self._width_group = QParallelAnimationGroup(self)
        for _prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self, _prop, self)
            anim.setDuration(TOGGLE_DURATION)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._width_group.addAnimation(anim)

    # ------------------------------------------------------------------
    # 刷新方法（给外部调用）
    # ------------------------------------------------------------------

    def refresh_spaces(self) -> None:
        """从 SpaceService 重新拉取空间列表。"""
        spaces = []
        if self._space_service is not None:
            try:
                spaces = list(self._space_service.list_spaces())
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"list_spaces 失败: {exc}")
                spaces = []
        self._spaces = spaces

        current_id = None
        if self._space_service is not None:
            try:
                current_id = self._space_service.get_current_space_id()
            except Exception:
                current_id = None

        self._suppress_space_signal = True
        try:
            self.space_combo.clear()
            # 0 号固定是"个人空间"
            self.space_combo.addItem("个人空间", userData=None)
            for sp in spaces:
                label = sp.name or sp.id[:8]
                self.space_combo.addItem(label, userData=sp.id)

            # 选中当前
            target_index = 0
            if current_id:
                for i in range(self.space_combo.count()):
                    if self.space_combo.itemData(i) == current_id:
                        target_index = i
                        break
            self.space_combo.setCurrentIndex(target_index)
        finally:
            self._suppress_space_signal = False
        # 空间数据更新后同步刷新可见性
        try:
            self._refresh_entitlement_ui()
        except Exception:
            pass

    def refresh_tags(self, space_id: Optional[str]) -> None:
        """刷新当前 space 的标签列表。"""
        self._suppress_tag_signal = True
        try:
            self.tag_list.clear()
            # 固定首项："全部"
            all_item = QListWidgetItem("全部")
            all_item.setData(Qt.UserRole, None)
            self.tag_list.addItem(all_item)
            self.tag_list.setCurrentItem(all_item)

            if self._tag_service is None:
                return

            try:
                # space_id=None 语义：个人空间；TagService.list_tags 的 None 是"所有"
                # 我们当前只查当前 space 的 tags（个人空间用空串 space_id）
                effective = space_id if space_id else ""
                tags = list(self._tag_service.list_tags(effective))
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"list_tags 失败: {exc}")
                tags = []

            for tag in tags:
                item = QListWidgetItem(tag.name or tag.id[:8])
                item.setData(Qt.UserRole, tag.id)
                self.tag_list.addItem(item)
        finally:
            self._suppress_tag_signal = False

    def current_space_id(self) -> Optional[str]:
        """返回 combo 当前选中的 space_id；个人空间返回 None。"""
        data = self.space_combo.currentData()
        return data if data else None

    def current_tag_id(self) -> Optional[str]:
        item = self.tag_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return data if data else None

    # ------------------------------------------------------------------
    # 内部槽
    # ------------------------------------------------------------------

    def _on_space_index_changed(self, idx: int) -> None:
        if self._suppress_space_signal or idx < 0:
            return
        space_id = self.space_combo.itemData(idx)
        # 切换到指定 space 时，刷新右侧标签列表
        self.refresh_tags(space_id)
        self.space_changed.emit(space_id if space_id else None)

    def _on_tag_selection_changed(self) -> None:
        if self._suppress_tag_signal:
            return
        tag_id = self.current_tag_id()
        self.tag_filter_changed.emit(tag_id)

    def _on_create_space_clicked(self) -> None:
        dlg = _CreateSpaceDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.get_name()
        type_ = dlg.get_type()
        if not name:
            return
        if self._space_service is None:
            # 无服务可用时仅 emit 信号让上层处理
            self.create_space_requested.emit()
            return
        try:
            self._space_service.create_space(name=name, type_=type_)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"创建 space 失败: {exc}")
            return
        self.create_space_requested.emit()
        self.refresh_spaces()

    def _refresh_entitlement_ui(self) -> None:
        """根据登录状态、entitlement、是否存在非个人空间，统一刷新扩展入口可见性。

        P4 触发原则：升级提示只在触达限制时出现。侧栏不再常驻"了解云端增强"按钮——
        用户可在「设置 → 云端同步」中查看 SubscriptionWidget；即将满额、分享受限、
        文件配额满等场景由具体功能上下文触发。
        """
        # 登录状态
        try:
            from config import get_cloud_access_token
            has_login = bool(get_cloud_access_token())
        except Exception:
            has_login = False

        # entitlement
        ent = None
        if self._entitlement_service is not None:
            try:
                ent = self._entitlement_service.current()
            except Exception:
                ent = None

        has_team_features = False
        if ent is not None:
            has_team_features = bool(
                getattr(ent, "team_seats", 0) or getattr(ent, "is_team_owner", False)
            )

        has_non_personal_space = bool(self._spaces)

        # Space 区块：登录 + 至少一个团队空间
        self.space_section.setVisible(has_login and has_non_personal_space)

        # 管理团队按钮：仅团队权益用户
        self.manage_team_btn.setVisible(bool(has_team_features))

        # 升级按钮：始终隐藏；改由触达限制场景按需弹提示
        self.upgrade_btn.setVisible(False)


class _CreateSpaceDialog(QDialog):
    """极简新建 Space 对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建空间")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("空间名")
        form.addRow("名称", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("个人 (personal)", "personal")
        self.type_combo.addItem("团队 (team)", "team")
        form.addRow("类型", self.type_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_name(self) -> str:
        return self.name_edit.text().strip()

    def get_type(self) -> str:
        return self.type_combo.currentData() or "personal"


__all__ = ["Sidebar", "EXPANDED_WIDTH", "COLLAPSED_WIDTH"]
