"""数据库设置 Tab：profile 选择 + SQLite / MySQL 切换 + 测试连接。"""

import logging

from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from config import (
    get_effective_database_path, get_mysql_config, set_mysql_config,
    settings, update_settings,
)
from i18n import t

logger = logging.getLogger(__name__)


class DatabaseTab(QWidget):
    """对应旧 SettingsDialog._build_database_tab + 数据库回调集合。"""

    def __init__(self, ctx=None, parent=None, **_legacy_kwargs):
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()
        self._on_db_type_changed(self.db_type_group.checkedId())

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- profile 行 ----
        profile_layout = QHBoxLayout()
        profile_layout.setSpacing(8)
        profile_layout.addWidget(QLabel(t("db_profile")))

        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        profiles = dict(settings().db_profiles)
        active = settings().active_profile
        for name in profiles:
            self.profile_combo.addItem(name)
        if active in profiles:
            self.profile_combo.setCurrentText(active)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        profile_layout.addWidget(self.profile_combo)

        add_profile_btn = QPushButton(t("add_profile"))
        add_profile_btn.clicked.connect(self._add_profile)
        profile_layout.addWidget(add_profile_btn)

        del_profile_btn = QPushButton(t("delete_profile"))
        del_profile_btn.clicked.connect(self._delete_profile)
        profile_layout.addWidget(del_profile_btn)

        layout.addLayout(profile_layout)

        # ---- 数据库类型卡片 ----
        db_type_label = QLabel(t("db_type"))
        db_type_label.setObjectName("sectionTitle")
        layout.addWidget(db_type_label)

        db_card_layout = QHBoxLayout()
        db_card_layout.setSpacing(12)

        self.sqlite_card = QPushButton(t("db_sqlite"))
        self.sqlite_card.setObjectName("dbTypeCard")
        self.sqlite_card.setCheckable(True)
        self.sqlite_card.setMinimumHeight(48)
        db_card_layout.addWidget(self.sqlite_card)

        self.mysql_card = QPushButton(t("db_mysql"))
        self.mysql_card.setObjectName("dbTypeCard")
        self.mysql_card.setCheckable(True)
        self.mysql_card.setMinimumHeight(48)
        db_card_layout.addWidget(self.mysql_card)

        self.db_type_group = QButtonGroup(self)
        self.db_type_group.setExclusive(True)
        self.db_type_group.addButton(self.sqlite_card, 0)
        self.db_type_group.addButton(self.mysql_card, 1)

        current_db_index = 0 if settings().db_type == "sqlite" else 1
        self.db_type_group.button(current_db_index).setChecked(True)
        self.db_type_group.idClicked.connect(self._on_db_type_changed)

        layout.addLayout(db_card_layout)

        # ---- SQLite 配置 ----
        self.sqlite_group = QGroupBox(t("sqlite_config"))
        sqlite_layout = QFormLayout(self.sqlite_group)
        sqlite_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        path_layout = QHBoxLayout()
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setText(get_effective_database_path())
        self.db_path_edit.setPlaceholderText(t("path_placeholder"))
        path_layout.addWidget(self.db_path_edit)

        browse_btn = QPushButton(t("browse"))
        browse_btn.clicked.connect(self._browse_db_path)
        path_layout.addWidget(browse_btn)
        sqlite_layout.addRow(t("db_path"), path_layout)

        layout.addWidget(self.sqlite_group)

        # ---- MySQL 配置 ----
        self.mysql_group = QGroupBox(t("mysql_config"))
        mysql_layout = QFormLayout(self.mysql_group)
        mysql_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        mysql_config = get_mysql_config()

        self.mysql_host_edit = QLineEdit()
        self.mysql_host_edit.setText(mysql_config["host"])
        self.mysql_host_edit.setPlaceholderText("localhost")
        mysql_layout.addRow(t("host"), self.mysql_host_edit)

        self.mysql_port_spin = QSpinBox()
        self.mysql_port_spin.setRange(1, 65535)
        self.mysql_port_spin.setValue(mysql_config["port"])
        mysql_layout.addRow(t("port"), self.mysql_port_spin)

        self.mysql_user_edit = QLineEdit()
        self.mysql_user_edit.setText(mysql_config["user"])
        self.mysql_user_edit.setPlaceholderText("root")
        mysql_layout.addRow(t("username"), self.mysql_user_edit)

        self.mysql_password_edit = QLineEdit()
        self.mysql_password_edit.setEchoMode(QLineEdit.Password)
        # Why: 预填已保存密码,避免重开对话框时字段为空导致 OK 按钮用空密码测试认证失败。
        self.mysql_password_edit.setText(mysql_config.get("password", ""))
        self.mysql_password_edit.setPlaceholderText(t("password"))
        mysql_layout.addRow(t("password"), self.mysql_password_edit)

        self.mysql_database_edit = QLineEdit()
        self.mysql_database_edit.setText(mysql_config["database"])
        self.mysql_database_edit.setPlaceholderText("clipboard")
        mysql_layout.addRow(t("db_name"), self.mysql_database_edit)

        test_btn_layout = QHBoxLayout()
        self.test_connection_btn = QPushButton(t("test_connection"))
        self.test_connection_btn.clicked.connect(self._test_mysql_connection)
        test_btn_layout.addWidget(self.test_connection_btn)
        test_btn_layout.addStretch()
        mysql_layout.addRow("", test_btn_layout)

        layout.addWidget(self.mysql_group)
        layout.addStretch()

    # ---- 回调 ----

    def _on_db_type_changed(self, index: int):
        is_sqlite = index == 0
        self.sqlite_group.setVisible(is_sqlite)
        self.mysql_group.setVisible(not is_sqlite)

    def _browse_db_path(self):
        import os
        import platform

        current_path = self.db_path_edit.text()
        if current_path and os.path.exists(os.path.dirname(current_path)):
            start_dir = current_path
        elif platform.system() == "Darwin" and os.path.exists("/Volumes"):
            start_dir = "/Volumes"
        else:
            start_dir = get_effective_database_path()

        path, _ = QFileDialog.getSaveFileName(
            self,
            t("select_db_file"),
            start_dir,
            "SQLite (*.db)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if path:
            self.db_path_edit.setText(path)

    def _test_mysql_connection(self):
        try:
            from core.mysql_database import MySQLDatabaseManager

            host = self.mysql_host_edit.text() or "localhost"
            port = self.mysql_port_spin.value()
            user = self.mysql_user_edit.text()
            password = self.mysql_password_edit.text()
            database = self.mysql_database_edit.text() or "clipboard"

            success, message = MySQLDatabaseManager.test_connection(
                host, port, user, password, database
            )

            if success:
                # Why: 连上以后再检测目标库是否是 website/api 的公共库，防止客户端
                #      个人 MySQL 误指到 api 公共库造成 schema 冲突。
                reserved = MySQLDatabaseManager.detect_api_reserved_tables(
                    host, port, user, password, database
                )
                if reserved:
                    QMessageBox.critical(
                        self,
                        f"MySQL — {t('error')}",
                        f"该库 '{database}' 是主程序（website/api）专用公共库，"
                        f"不能作为客户端个人库使用。\n\n"
                        f"检测到 api 标志表: {', '.join(reserved)}\n\n"
                        f"请换一个库名（例如 clipboard_personal）。"
                    )
                    return
                QMessageBox.information(self, f"MySQL — {t('connection_success')}", message)
            else:
                QMessageBox.warning(self, f"MySQL — {t('connection_failed')}", message)
        except ImportError:
            QMessageBox.warning(
                self, t("missing_dependency"),
                t("pymysql_required")
            )
        except Exception as e:
            QMessageBox.critical(self, f"MySQL — {t('error')}", f"{str(e)}")

    def _on_profile_changed(self, name: str):
        profiles = settings().db_profiles
        profile = profiles.get(name)
        if not profile:
            return
        db_type = profile.get("db_type", "sqlite")
        self.db_type_group.button(0 if db_type == "sqlite" else 1).setChecked(True)
        self._on_db_type_changed(0 if db_type == "sqlite" else 1)
        self.db_path_edit.setText(profile.get("database_path", ""))
        self.mysql_host_edit.setText(profile.get("mysql_host", "localhost"))
        self.mysql_port_spin.setValue(profile.get("mysql_port", 3306))
        self.mysql_user_edit.setText(profile.get("mysql_user", ""))
        # Why: profile 不持久化密码(只走 keyring),切换时用 keyring 值预填避免字段变空。
        self.mysql_password_edit.setText(get_mysql_config().get("password", ""))
        self.mysql_database_edit.setText(profile.get("mysql_database", "clipboard"))

    def _add_profile(self):
        name, ok = QInputDialog.getText(self, t("profile_name"), t("enter_profile_name"))
        if not ok or not name.strip():
            return
        name = name.strip()
        profiles = dict(settings().db_profiles)
        if name in profiles:
            QMessageBox.warning(self, t("warning"), t("profile_exists"))
            return
        # Why: profile 持久化到 settings.json，绝不能带明文密码（密码走 keyring）。
        profile_settings = self.current_db_settings()
        profile_settings["mysql_password"] = ""
        profiles[name] = profile_settings
        update_settings(db_profiles=profiles)
        self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(name)

    def _delete_profile(self):
        name = self.profile_combo.currentText()
        profiles = dict(settings().db_profiles)
        if len(profiles) <= 1:
            return
        if name == settings().active_profile:
            QMessageBox.warning(self, t("warning"), t("cannot_delete_active"))
            return
        reply = QMessageBox.question(
            self, t("confirm_delete"), t("confirm_delete_profile", name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            del profiles[name]
            update_settings(db_profiles=profiles)
            self.profile_combo.removeItem(self.profile_combo.currentIndex())

    # ---- 对外接口 ----

    def current_db_settings(self) -> dict:
        """从 UI 中读取当前数据库配置（纯读取，无副作用）。

        Why: 该函数会被 _add_profile / collect / OK 前的探测等多个路径调用，
        只读保证幂等。密码持久化统一搬到 OK 流程中一次完成。
        """
        db_type = "sqlite" if self.db_type_group.checkedId() == 0 else "mysql"
        return {
            "db_type": db_type,
            "database_path": self.db_path_edit.text(),
            "mysql_host": self.mysql_host_edit.text() or "localhost",
            "mysql_port": self.mysql_port_spin.value(),
            "mysql_user": self.mysql_user_edit.text(),
            # 明文密码随 dict 返回，调用方负责写入安全存储
            "mysql_password": self.mysql_password_edit.text(),
            "mysql_database": self.mysql_database_edit.text() or "clipboard",
        }

    def validate_and_persist_on_accept(self) -> bool:
        """OK 按下时的 MySQL 校验 + 持久化。返回 False 时阻止对话框关闭。"""
        if self.db_type_group.checkedId() != 1:
            return True

        try:
            from core.mysql_database import MySQLDatabaseManager

            host = self.mysql_host_edit.text() or "localhost"
            port = self.mysql_port_spin.value()
            user = self.mysql_user_edit.text()
            password = self.mysql_password_edit.text()
            database = self.mysql_database_edit.text() or "clipboard"

            success, message = MySQLDatabaseManager.test_connection(
                host, port, user, password, database
            )

            if not success:
                reply = QMessageBox.question(
                    self,
                    f"MySQL — {t('connection_failed')}",
                    t("save_anyway", message=message),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return False
            else:
                # Why: 连通性通过后兜底检测目标库是否是 api 公共库，防止和 Test 按钮
                #      绕开：即便用户没点 Test 直接按 OK，也不允许把个人库指到 api 公共库。
                reserved = MySQLDatabaseManager.detect_api_reserved_tables(
                    host, port, user, password, database
                )
                if reserved:
                    QMessageBox.critical(
                        self,
                        f"MySQL — {t('error')}",
                        f"该库 '{database}' 是主程序（website/api）专用公共库，"
                        f"不能作为客户端个人库使用。\n\n"
                        f"检测到 api 标志表: {', '.join(reserved)}\n\n"
                        f"请换一个库名（例如 clipboard_personal）。"
                    )
                    return False
        except ImportError:
            QMessageBox.warning(
                self, t("missing_dependency"),
                t("pymysql_required")
            )
            return False

        try:
            set_mysql_config(
                host=host, port=port, user=user,
                password=password, database=database,
            )
        except Exception as e:
            logger.warning(f"保存 MySQL 配置到安全存储失败: {e}")
        return True

    def collect(self) -> dict:
        """供 SettingsDialog.get_settings() 汇总：active_profile + db_settings。

        Why: get_settings() 在此处会顺手把当前 profile 写回 settings.db_profiles，
        与旧 _on_accept 行为保持一致。
        """
        db_settings = self.current_db_settings()
        profile_snapshot = dict(db_settings)
        # 持久化时剥掉明文密码——密码只通过 keyring 保存。
        profile_snapshot["mysql_password"] = ""

        profile_name = self.profile_combo.currentText()
        profiles = dict(settings().db_profiles)
        profiles[profile_name] = profile_snapshot
        update_settings(db_profiles=profiles)

        result = {"active_profile": profile_name}
        result.update(db_settings)
        return result
