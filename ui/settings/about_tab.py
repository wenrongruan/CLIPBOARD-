"""关于 Tab：版本号、官网、GitHub、下载页等链接。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget,
)

from config import APP_VERSION
from i18n import t


class AboutTab(QWidget):
    """对应旧 SettingsDialog._build_about_tab。"""

    def __init__(self, ctx=None, parent=None, **_legacy_kwargs):
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        app_name_label = QLabel(t("app_name"))
        app_name_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        app_name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(app_name_label)

        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet("color: #888888; font-size: 13px;")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        desc_label = QLabel(t("about_description"))
        desc_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        desc_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc_label)

        layout.addSpacing(10)

        link_style = "color: #58a6ff; text-decoration: none;"
        links_group = QGroupBox("")
        links_layout = QFormLayout(links_group)
        links_layout.setSpacing(12)

        website_label = QLabel(
            f'<a href="https://www.jlike.com" style="{link_style}">www.jlike.com</a>'
        )
        website_label.setOpenExternalLinks(True)
        links_layout.addRow(t("official_website"), website_label)

        github_label = QLabel(
            f'<a href="https://github.com/wenrongruan/CLIPBOARD-" style="{link_style}">'
            f'github.com/wenrongruan/CLIPBOARD-</a>'
        )
        github_label.setOpenExternalLinks(True)
        links_layout.addRow(t("github_repo"), github_label)

        download_label = QLabel(
            f'<a href="https://github.com/wenrongruan/CLIPBOARD-/releases" '
            f'style="{link_style}">GitHub Releases</a>'
        )
        download_label.setOpenExternalLinks(True)
        links_layout.addRow(t("download_page"), download_label)

        layout.addWidget(links_group)
        layout.addStretch()
