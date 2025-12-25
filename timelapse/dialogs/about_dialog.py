"""
About Dialog for Timelapse Plugin

This dialog displays information about the Timelapse plugin including
version, author, features, and links to documentation.
"""

import os
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QTextBrowser,
)
from qgis.PyQt.QtGui import QFont, QPixmap


class AboutDialog(QDialog):
    """About dialog for the Timelapse plugin."""

    def __init__(self, plugin_dir, parent=None):
        super().__init__(parent)
        self.plugin_dir = plugin_dir
        self.version = self._get_version()

        self.setWindowTitle("About Timelapse Plugin")
        self.setMinimumWidth(550)
        self.setMinimumHeight(500)

        self._setup_ui()

    def _get_version(self):
        """Read the version from metadata.txt."""
        metadata_path = os.path.join(self.plugin_dir, "metadata.txt")
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                content = f.read()
            version_match = re.search(r"^version=(.+)$", content, re.MULTILINE)
            if version_match:
                return version_match.group(1).strip()
        except (FileNotFoundError, OSError, IOError):
            pass
        return "Unknown"

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header with icon and title
        header_layout = QHBoxLayout()

        # Plugin icon
        icon_path = os.path.join(self.plugin_dir, "icons", "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(self.plugin_dir, "icons", "icon.svg")

        if os.path.exists(icon_path):
            icon_label = QLabel()
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                icon_label.setPixmap(
                    pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                header_layout.addWidget(icon_label)

        # Title and version
        title_layout = QVBoxLayout()

        title_label = QLabel("Timelapse Animation Creator")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)

        version_label = QLabel(f"Version {self.version}")
        version_label.setStyleSheet("color: gray; font-size: 12px;")
        title_layout.addWidget(version_label)

        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Description
        desc_text = """
<p>A QGIS plugin for creating timelapse animations from satellite and aerial imagery
using Google Earth Engine.</p>

<p>Create stunning timelapse animations showing environmental changes, urban development,
seasonal variations, and more from various satellite data sources.</p>
"""
        desc_label = QLabel(desc_text)
        desc_label.setWordWrap(True)
        desc_label.setOpenExternalLinks(True)
        layout.addWidget(desc_label)

        # Features group
        features_group = QGroupBox("Supported Imagery")
        features_layout = QVBoxLayout(features_group)

        features_browser = QTextBrowser()
        features_browser.setOpenExternalLinks(True)
        features_browser.setMaximumHeight(180)
        features_html = """
<table style="width:100%; border-collapse: collapse;">
<tr style="background-color: #f0f0f0;">
    <td style="padding: 5px;"><b>NAIP</b></td>
    <td style="padding: 5px;">High-resolution aerial imagery (US only, 2003-present)</td>
</tr>
<tr>
    <td style="padding: 5px;"><b>Landsat</b></td>
    <td style="padding: 5px;">Long-term satellite archive (1984-present)</td>
</tr>
<tr style="background-color: #f0f0f0;">
    <td style="padding: 5px;"><b>Sentinel-2</b></td>
    <td style="padding: 5px;">Multispectral imagery (2015-present)</td>
</tr>
<tr>
    <td style="padding: 5px;"><b>Sentinel-1</b></td>
    <td style="padding: 5px;">SAR radar imagery (2014-present)</td>
</tr>
<tr style="background-color: #f0f0f0;">
    <td style="padding: 5px;"><b>MODIS NDVI</b></td>
    <td style="padding: 5px;">Vegetation phenology animations</td>
</tr>
<tr>
    <td style="padding: 5px;"><b>GOES</b></td>
    <td style="padding: 5px;">Weather satellite animations</td>
</tr>
</table>
"""
        features_browser.setHtml(features_html)
        features_layout.addWidget(features_browser)
        layout.addWidget(features_group)

        # Author info
        author_group = QGroupBox("Author")
        author_layout = QVBoxLayout(author_group)

        author_info = QLabel(
            """
<p><b>Qiusheng Wu</b></p>
<p>Email: <a href="mailto:giswqs@gmail.com">giswqs@gmail.com</a></p>
<p>Website: <a href="https://wetlands.io">https://wetlands.io</a></p>
"""
        )
        author_info.setOpenExternalLinks(True)
        author_layout.addWidget(author_info)
        layout.addWidget(author_group)

        # Links
        links_layout = QHBoxLayout()

        github_btn = QPushButton("GitHub Repository")
        github_btn.clicked.connect(self._open_github)
        links_layout.addWidget(github_btn)

        issues_btn = QPushButton("Report Issue")
        issues_btn.clicked.connect(self._open_issues)
        links_layout.addWidget(issues_btn)

        docs_btn = QPushButton("Documentation")
        docs_btn.clicked.connect(self._open_docs)
        links_layout.addWidget(docs_btn)

        layout.addLayout(links_layout)

        # License
        license_label = QLabel(
            "<p style='color: gray; text-align: center;'>"
            "Licensed under the MIT License</p>"
        )
        license_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(license_label)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_btn.setMinimumHeight(32)
        layout.addWidget(close_btn)

    def _open_github(self):
        """Open GitHub repository in browser."""
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices

        QDesktopServices.openUrl(
            QUrl("https://github.com/opengeos/qgis-timelapse-plugin")
        )

    def _open_issues(self):
        """Open GitHub issues page in browser."""
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices

        QDesktopServices.openUrl(
            QUrl("https://github.com/opengeos/qgis-timelapse-plugin/issues")
        )

    def _open_docs(self):
        """Open documentation in browser."""
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices

        QDesktopServices.openUrl(
            QUrl("https://github.com/opengeos/qgis-timelapse-plugin#readme")
        )
