"""
Settings Dock Widget for Timelapse Plugin

This module provides a settings panel for configuring
Earth Engine authentication and managing plugin dependencies.
"""

import os

from qgis.PyQt.QtCore import Qt, QSettings, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QGroupBox,
    QFormLayout,
    QMessageBox,
    QFileDialog,
    QTabWidget,
    QProgressBar,
)
from qgis.PyQt.QtGui import QFont

try:
    import ee
except ImportError:
    ee = None


class SettingsDockWidget(QDockWidget):
    """A settings panel for configuring timelapse plugin options."""

    # Emitted when dependencies are successfully installed
    deps_installed = pyqtSignal()
    # Emitted when EE authentication succeeds
    auth_succeeded = pyqtSignal()
    # Emitted when settings are saved
    settings_saved = pyqtSignal()

    # Settings keys
    SETTINGS_PREFIX = "QgisTimelapse/"

    def __init__(self, iface, parent=None):
        """Initialize the settings dock widget.

        Args:
            iface: QGIS interface instance.
            parent: Parent widget.
        """
        super().__init__("Timelapse Settings", parent)
        self.iface = iface
        self.settings = QSettings()
        self._deps_worker = None
        self._auth_worker = None

        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Set up the settings UI."""
        # Main widget
        main_widget = QWidget()
        self.setWidget(main_widget)

        # Main layout
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(10)

        # Header
        header_label = QLabel("Timelapse Settings")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)

        # Tab widget for organized settings
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Dependencies tab (first tab)
        deps_tab = self._create_dependencies_tab()
        self.tab_widget.addTab(deps_tab, "Dependencies")

        # Earth Engine tab
        ee_tab = self._create_ee_tab()
        self.tab_widget.addTab(ee_tab, "Earth Engine")

        # Buttons
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(self.save_btn)

        self.reset_btn = QPushButton("Reset Defaults")
        self.reset_btn.clicked.connect(self._reset_defaults)
        button_layout.addWidget(self.reset_btn)

        layout.addLayout(button_layout)

        # Stretch at the end
        layout.addStretch()

        # Status label
        self.status_label = QLabel("Settings loaded")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.status_label)

    def _create_dependencies_tab(self):
        """Create the dependencies management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Info label
        info_label = QLabel(
            "This plugin requires additional Python packages.\n"
            "Click 'Install Dependencies' to install them in an\n"
            "isolated virtual environment (~/.qgis_timelapse)."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(info_label)

        # Package status group
        status_group = QGroupBox("Package Status")
        self._deps_status_layout = QFormLayout(status_group)

        # Create status labels for each package
        self._deps_labels = {}
        from ..core.venv_manager import REQUIRED_PACKAGES

        for package_name, _version_spec in REQUIRED_PACKAGES:
            label = QLabel("Checking...")
            label.setStyleSheet("color: gray;")
            self._deps_labels[package_name] = label
            self._deps_status_layout.addRow(f"{package_name}:", label)

        layout.addWidget(status_group)

        # Install button
        self.install_deps_btn = QPushButton("Install Dependencies")
        self.install_deps_btn.clicked.connect(self._install_dependencies)
        layout.addWidget(self.install_deps_btn)

        # Progress bar (hidden by default)
        self.deps_progress_bar = QProgressBar()
        self.deps_progress_bar.setVisible(False)
        layout.addWidget(self.deps_progress_bar)

        # Progress/status label
        self.deps_progress_label = QLabel("")
        self.deps_progress_label.setWordWrap(True)
        self.deps_progress_label.setVisible(False)
        layout.addWidget(self.deps_progress_label)

        # Cancel button (hidden by default)
        self.cancel_deps_btn = QPushButton("Cancel")
        self.cancel_deps_btn.setStyleSheet("color: red;")
        self.cancel_deps_btn.setVisible(False)
        self.cancel_deps_btn.clicked.connect(self._cancel_deps_install)
        layout.addWidget(self.cancel_deps_btn)

        # Refresh button
        self.refresh_deps_btn = QPushButton("Refresh Status")
        self.refresh_deps_btn.clicked.connect(self._refresh_deps_status)
        layout.addWidget(self.refresh_deps_btn)

        layout.addStretch()

        # Initial status check
        self._refresh_deps_status()

        return widget

    def _refresh_deps_status(self):
        """Refresh the dependency status display."""
        from ..core.venv_manager import check_dependencies

        all_ok, missing, installed = check_dependencies()

        for package_name, version in installed:
            if package_name in self._deps_labels:
                self._deps_labels[package_name].setText(f"v{version} (installed)")
                self._deps_labels[package_name].setStyleSheet(
                    "color: green; font-weight: bold;"
                )

        for package_name, _version_spec in missing:
            if package_name in self._deps_labels:
                self._deps_labels[package_name].setText("Not installed")
                self._deps_labels[package_name].setStyleSheet("color: red;")

        self.install_deps_btn.setEnabled(not all_ok)
        if all_ok:
            self.install_deps_btn.setText("All Dependencies Installed")
        else:
            self.install_deps_btn.setText(
                f"Install Dependencies ({len(missing)} missing)"
            )

    def _install_dependencies(self):
        """Start installing missing dependencies."""
        from .deps_manager import DepsInstallWorker

        # Guard against concurrent installs
        if self._deps_worker is not None and self._deps_worker.isRunning():
            return

        # Update UI for installation mode
        self.install_deps_btn.setEnabled(False)
        self.refresh_deps_btn.setEnabled(False)
        self.deps_progress_bar.setVisible(True)
        self.deps_progress_bar.setRange(0, 100)
        self.deps_progress_bar.setValue(0)
        self.deps_progress_label.setVisible(True)
        self.deps_progress_label.setText("Starting installation...")
        self.deps_progress_label.setStyleSheet("")
        self.cancel_deps_btn.setVisible(True)
        self.cancel_deps_btn.setEnabled(True)

        # Start worker
        self._deps_worker = DepsInstallWorker()
        self._deps_worker.progress.connect(self._on_deps_progress)
        self._deps_worker.finished.connect(self._on_deps_finished)
        self._deps_worker.start()

    def _on_deps_progress(self, percent, message):
        """Handle progress updates from the dependency install worker.

        Args:
            percent: Installation progress percentage (0-100).
            message: Status message describing current operation.
        """
        self.deps_progress_bar.setValue(percent)
        self.deps_progress_label.setText(message)

    def _on_deps_finished(self, success, message):
        """Handle completion of the dependency installation.

        Args:
            success: True if all packages installed successfully.
            message: Summary message.
        """
        # Reset UI
        self.deps_progress_bar.setVisible(False)
        self.deps_progress_label.setText(message)
        self.cancel_deps_btn.setVisible(False)
        self.refresh_deps_btn.setEnabled(True)

        if success:
            self.deps_progress_label.setStyleSheet("color: green;")
            self.iface.messageBar().pushSuccess(
                "Timelapse", "Dependencies installed successfully!"
            )
            self.deps_installed.emit()

            # Auto-start EE authentication if credentials don't exist
            from ..core.venv_manager import ee_credentials_exist

            if not ee_credentials_exist():
                self._start_auth()
        else:
            self.deps_progress_label.setStyleSheet("color: red;")
            self.install_deps_btn.setEnabled(True)

        # Refresh status display
        self._refresh_deps_status()

    def _cancel_deps_install(self):
        """Cancel the ongoing dependency installation."""
        if self._deps_worker is not None and self._deps_worker.isRunning():
            self._deps_worker.cancel()
            self.cancel_deps_btn.setEnabled(False)
            self.deps_progress_label.setText("Cancelling...")

    def show_dependencies_tab(self):
        """Switch to the Dependencies tab and refresh status."""
        self.tab_widget.setCurrentIndex(0)
        self._refresh_deps_status()

    def show_ee_tab(self):
        """Switch to the Earth Engine tab and focus the project ID input."""
        self.tab_widget.setCurrentIndex(1)
        self.project_id_input.setFocus()

    def _create_ee_tab(self):
        """Create the Earth Engine settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Authentication group
        auth_group = QGroupBox("Authentication")
        auth_layout = QFormLayout(auth_group)

        # Project ID
        self.project_id_input = QLineEdit()
        self.project_id_input.setPlaceholderText("Google Cloud Project ID")
        auth_layout.addRow("Project ID:", self.project_id_input)

        # Service account
        self.service_account_input = QLineEdit()
        self.service_account_input.setPlaceholderText(
            "Optional: service-account@project.iam.gserviceaccount.com"
        )
        auth_layout.addRow("Service Account:", self.service_account_input)

        # Credentials file
        cred_layout = QHBoxLayout()
        self.credentials_input = QLineEdit()
        self.credentials_input.setPlaceholderText("Path to credentials JSON file")
        cred_layout.addWidget(self.credentials_input)
        self.browse_cred_btn = QPushButton("...")
        self.browse_cred_btn.setMaximumWidth(30)
        self.browse_cred_btn.clicked.connect(self._browse_credentials)
        cred_layout.addWidget(self.browse_cred_btn)
        auth_layout.addRow("Credentials:", cred_layout)

        layout.addWidget(auth_group)

        # Actions group
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)

        # Initialize button
        init_btn = QPushButton("Initialize Earth Engine")
        init_btn.clicked.connect(self._initialize_ee)
        actions_layout.addWidget(init_btn)

        # Authenticate button
        auth_btn = QPushButton("Authenticate (opens browser)")
        auth_btn.clicked.connect(self._authenticate_ee)
        actions_layout.addWidget(auth_btn)

        # Status
        self.ee_status_label = QLabel("Status: Not initialized")
        self.ee_status_label.setStyleSheet("color: gray;")
        actions_layout.addWidget(self.ee_status_label)

        layout.addWidget(actions_group)

        layout.addStretch()
        return widget

    def _browse_credentials(self):
        """Open file browser for credentials file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Credentials File",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path:
            self.credentials_input.setText(file_path)

    def _initialize_ee(self):
        """Initialize Earth Engine with current settings."""
        if ee is None:
            QMessageBox.warning(
                self,
                "Warning",
                "Earth Engine API not installed.\n\n"
                "Please install dependencies from the Dependencies tab first.",
            )
            return

        project = self.project_id_input.text().strip()
        if not project:
            project = os.environ.get("EE_PROJECT_ID", "")

        if not project:
            QMessageBox.warning(
                self,
                "Project ID Required",
                "A Google Cloud project ID is required to initialize "
                "Earth Engine.\n\nPlease enter your project ID above.",
            )
            self.project_id_input.setFocus()
            return

        try:
            # Check if credentials file is specified
            cred_file = self.credentials_input.text().strip()
            credentials = None

            if cred_file:
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(
                    cred_file,
                    scopes=["https://www.googleapis.com/auth/earthengine"],
                )

            ee.Initialize(credentials=credentials, project=project)

            self.ee_status_label.setText("Status: Initialized")
            self.ee_status_label.setStyleSheet("color: green;")
            self.iface.messageBar().pushSuccess(
                "Timelapse", "Earth Engine initialized successfully!"
            )

        except Exception as e:
            self.ee_status_label.setText("Status: Error")
            self.ee_status_label.setStyleSheet("color: red;")
            QMessageBox.critical(
                self,
                "Initialization Error",
                f"Failed to initialize Earth Engine:\n\n{str(e)}",
            )

    def _authenticate_ee(self):
        """Start Earth Engine authentication in the background."""
        self._start_auth()

    def _start_auth(self):
        """Start Earth Engine authentication in a background thread."""
        from .deps_manager import EEAuthWorker

        # Guard against concurrent auth
        if self._auth_worker is not None and self._auth_worker.isRunning():
            return

        self.ee_status_label.setText(
            "Authenticating... A browser window should open.\n"
            "Complete the sign-in and return here."
        )
        self.ee_status_label.setStyleSheet("color: blue;")
        self.deps_progress_bar.setVisible(True)
        self.deps_progress_bar.setRange(0, 0)  # Indeterminate

        self._auth_worker = EEAuthWorker()
        self._auth_worker.progress.connect(self._on_auth_progress)
        self._auth_worker.finished.connect(self._on_auth_finished)
        self._auth_worker.start()

    def _on_auth_progress(self, percent, message):
        """Handle auth progress updates.

        Args:
            percent: Progress percentage.
            message: Status message.
        """
        self.ee_status_label.setText(message)

    def _on_auth_finished(self, success, message):
        """Handle authentication completion.

        Args:
            success: Whether authentication succeeded.
            message: Result message.
        """
        self._auth_worker = None
        self.deps_progress_bar.setVisible(False)
        self.deps_progress_bar.setRange(0, 100)

        if success:
            self.ee_status_label.setText("Status: Credentials found")
            self.ee_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.iface.messageBar().pushSuccess(
                "Timelapse",
                "Earth Engine authenticated successfully!",
            )
            self.auth_succeeded.emit()
        else:
            self.ee_status_label.setText(f"Authentication failed: {message[:150]}")
            self.ee_status_label.setStyleSheet("color: red;")

    def _load_settings(self):
        """Load settings from QSettings."""
        # Earth Engine
        self.project_id_input.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}project_id", "", type=str)
        )
        self.service_account_input.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}service_account", "", type=str)
        )
        self.credentials_input.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}credentials", "", type=str)
        )

        self.status_label.setText("Settings loaded")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")

    def _save_settings(self):
        """Save settings to QSettings."""
        # Earth Engine
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}project_id", self.project_id_input.text()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}service_account",
            self.service_account_input.text(),
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}credentials", self.credentials_input.text()
        )

        self.settings.sync()

        self.status_label.setText("Settings saved")
        self.status_label.setStyleSheet("color: green; font-size: 10px;")

        self.iface.messageBar().pushSuccess("Timelapse", "Settings saved successfully!")
        self.settings_saved.emit()

    def _reset_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        # Earth Engine
        self.project_id_input.clear()
        self.service_account_input.clear()
        self.credentials_input.clear()

        self.status_label.setText("Defaults restored (not saved)")
        self.status_label.setStyleSheet("color: orange; font-size: 10px;")
