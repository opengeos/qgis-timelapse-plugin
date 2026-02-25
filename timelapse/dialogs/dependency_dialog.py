"""
Dependency Installer Dialog for Timelapse Plugin

This dialog provides a one-click installer for required Python packages
(earthengine-api, numpy, Pillow) into an isolated virtual environment
at ~/.qgis_timelapse.
"""

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..core import venv_manager


class InstallWorker(QThread):
    """Worker thread for creating venv and installing dependencies."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        """Execute venv creation and dependency installation."""
        try:
            self.progress.emit(5, "Locating Python interpreter...")

            self.progress.emit(10, "Creating virtual environment...")
            venv_manager.create_venv(
                progress_callback=lambda msg: self.progress.emit(20, msg)
            )

            self.progress.emit(
                30, "Installing dependencies (this may take a few minutes)..."
            )
            venv_manager.install_dependencies(
                progress_callback=lambda msg: self.progress.emit(60, msg)
            )

            self.progress.emit(90, "Configuring Python path...")
            venv_manager.ensure_venv_packages_available()

            self.progress.emit(100, "Installation complete!")
            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))


class DependencyDialog(QDialog):
    """Dialog for installing required plugin dependencies."""

    def __init__(self, parent=None):
        """Initialize the dependency installation dialog.

        Args:
            parent: Parent widget.
        """
        super().__init__(parent)
        self._install_worker = None
        self._success = False

        self.setWindowTitle("Timelapse - Install Dependencies")
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QLabel("Install Required Dependencies")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # Description
        desc = QLabel(
            "The Timelapse plugin requires the following Python packages:\n\n"
            "  - earthengine-api (Google Earth Engine)\n"
            "  - numpy\n"
            "  - Pillow (image processing)\n\n"
            "These will be installed into an isolated virtual environment\n"
            f"at: {venv_manager.VENV_DIR}\n\n"
            "Click 'Install' to begin."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Log / status text
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_text.setPlaceholderText("Installation log will appear here...")
        layout.addWidget(self._log_text)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # Buttons
        btn_layout = QHBoxLayout()

        self._install_btn = QPushButton("Install")
        self._install_btn.setMinimumHeight(36)
        self._install_btn.clicked.connect(self._start_install)
        btn_layout.addWidget(self._install_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setMinimumHeight(36)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

    def _start_install(self):
        """Begin the installation process in a worker thread."""
        self._install_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._log_text.clear()
        self._log_text.append("Starting installation...")

        self._install_worker = InstallWorker()
        self._install_worker.progress.connect(self._on_progress)
        self._install_worker.finished.connect(self._on_finished)
        self._install_worker.error.connect(self._on_error)
        self._install_worker.start()

    def _on_progress(self, percent, message):
        """Handle progress updates from the worker.

        Args:
            percent: Progress percentage (0-100).
            message: Status message to display.
        """
        self._progress_bar.setValue(percent)
        self._log_text.append(message)

    def _on_finished(self):
        """Handle successful installation."""
        self._success = True
        self._log_text.append("\nAll dependencies installed successfully!")
        self._cancel_btn.setText("Close")
        self._cancel_btn.setEnabled(True)

        QMessageBox.information(
            self,
            "Installation Complete",
            "Dependencies have been installed successfully.\n"
            "The Timelapse panel will now open.",
        )
        self.accept()

    def _on_error(self, error_msg):
        """Handle installation error.

        Args:
            error_msg: Error message from the worker.
        """
        self._log_text.append(f"\nERROR: {error_msg}")
        self._install_btn.setEnabled(True)
        self._install_btn.setText("Retry")
        self._cancel_btn.setEnabled(True)
        self._progress_bar.setValue(0)

        QMessageBox.critical(
            self,
            "Installation Failed",
            f"Failed to install dependencies:\n\n{error_msg}\n\n"
            "Check the log for details. You can retry or cancel.",
        )

    def was_successful(self) -> bool:
        """Return whether the installation completed successfully.

        Returns:
            True if dependencies were installed successfully.
        """
        return self._success

    def closeEvent(self, event):
        """Handle dialog close -- warn if worker is running.

        Args:
            event: The close event.
        """
        if self._install_worker and self._install_worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Installation in Progress",
                "An installation is in progress. " "Are you sure you want to cancel?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self._install_worker.terminate()
            self._install_worker.wait()
        event.accept()
