"""
QGIS Timelapse Animation Creator Plugin - Main Plugin Class

This module contains the main plugin class that manages the QGIS interface
integration, menu items, toolbar buttons, and dockable panels.
"""

import os
import re

from qgis.PyQt.QtCore import Qt, QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar, QMessageBox


class TimelapsePlugin:
    """Timelapse Plugin implementation class for QGIS."""

    def __init__(self, iface):
        """Constructor.

        Args:
            iface: An interface instance that provides the hook to QGIS.
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = None
        self.toolbar = None

        # Initialize locale
        locale = QSettings().value("locale/userLocale", "en")[0:2]
        locale_path = os.path.join(self.plugin_dir, "i18n", f"timelapse_{locale}.qm")

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Dock widgets (lazy loaded)
        self._timelapse_dock = None
        self._settings_dock = None

        # Dependency state
        self._deps_ready = False
        self._deps_initialized = False
        self._deps_signal_connected = False

    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        Args:
            message: String to translate.

        Returns:
            str: Translated string.
        """
        return QCoreApplication.translate("TimelapsePlugin", message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        checkable=False,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        Args:
            icon_path: Path to the icon for this action.
            text: Text that appears in the menu for this action.
            callback: Function to be called when the action is triggered.
            enabled_flag: A flag indicating if the action should be enabled.
            add_to_menu: Flag indicating whether action should be added to menu.
            add_to_toolbar: Flag indicating whether action should be added to toolbar.
            status_tip: Optional text to show in status bar when mouse hovers over action.
            checkable: Whether the action is checkable (toggle).
            parent: Parent widget for the new action.

        Returns:
            The action that was created.
        """
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)
        action.setCheckable(checkable)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.menu.addAction(action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        # Create menu
        self.menu = QMenu(self.tr("&Timelapse"))
        self.iface.mainWindow().menuBar().addMenu(self.menu)

        # Create toolbar
        self.toolbar = QToolBar(self.tr("Timelapse Toolbar"))
        self.toolbar.setObjectName("TimelapseToolbar")
        self.iface.addToolBar(self.toolbar)

        # Get icon paths
        icon_base = os.path.join(self.plugin_dir, "icons")

        # Main panel icon
        main_icon = os.path.join(icon_base, "icon.png")
        if not os.path.exists(main_icon):
            main_icon = os.path.join(icon_base, "icon.svg")
        if not os.path.exists(main_icon):
            main_icon = ":/images/themes/default/mActionAddRasterLayer.svg"

        about_icon = os.path.join(icon_base, "about.svg")
        if not os.path.exists(about_icon):
            about_icon = ":/images/themes/default/mActionHelpContents.svg"

        settings_icon = os.path.join(icon_base, "settings.svg")
        if not os.path.exists(settings_icon):
            settings_icon = ":/images/themes/default/mActionOptions.svg"

        # Add Timelapse Panel action (checkable for dock toggle)
        self.timelapse_action = self.add_action(
            main_icon,
            self.tr("Create Timelapse"),
            self.toggle_timelapse_dock,
            status_tip=self.tr("Toggle Timelapse Animation Creator Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Add Settings Panel action (checkable for dock toggle)
        self.settings_action = self.add_action(
            settings_icon,
            self.tr("Settings"),
            self.toggle_settings_dock,
            status_tip=self.tr("Toggle Timelapse Settings Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Add separator to menu
        self.menu.addSeparator()

        # Update icon - use QGIS default refresh icon
        update_icon = ":/images/themes/default/mActionRefresh.svg"

        # Add Check for Updates action (menu only)
        self.add_action(
            update_icon,
            self.tr("Check for Updates..."),
            self.show_update_checker,
            add_to_toolbar=False,
            status_tip=self.tr("Check for plugin updates from GitHub"),
            parent=self.iface.mainWindow(),
        )

        # Add About action (menu only)
        self.add_action(
            about_icon,
            self.tr("About Timelapse"),
            self.show_about,
            add_to_toolbar=False,
            status_tip=self.tr("About Timelapse Plugin"),
            parent=self.iface.mainWindow(),
        )

    def unload(self):
        """Remove the plugin menu item and icon from QGIS GUI."""
        # Remove dock widgets
        if self._timelapse_dock:
            self.iface.removeDockWidget(self._timelapse_dock)
            self._timelapse_dock.deleteLater()
            self._timelapse_dock = None

        if self._settings_dock:
            self.iface.removeDockWidget(self._settings_dock)
            self._settings_dock.deleteLater()
            self._settings_dock = None

        # Remove actions
        for action in self.actions:
            self.iface.removePluginRasterMenu(self.tr("&Timelapse"), action)

        # Remove toolbar
        if self.toolbar:
            del self.toolbar

        # Remove menu
        if self.menu:
            self.menu.deleteLater()

    # ------------------------------------------------------------------
    # Dependency management
    # ------------------------------------------------------------------

    def _ensure_deps(self) -> bool:
        """Check if dependencies are installed and loaded.

        Returns True if deps are ready. If not, shows a non-blocking
        warning and offers to open Settings -> Dependencies tab.

        Returns:
            True if dependencies are ready and loaded, False otherwise.
        """
        if self._deps_ready:
            return True

        from .core.venv_manager import ensure_venv_packages_available, get_venv_status

        is_ready, status_msg = get_venv_status()

        if is_ready:
            if ensure_venv_packages_available():
                self._deps_ready = True
                self._post_deps_init()
                return True

        # Dependencies not ready -- show non-blocking warning
        self._check_dependencies_on_open()
        return False

    def _check_dependencies_on_open(self):
        """Check if dependencies are installed and prompt if missing."""
        try:
            from .core.venv_manager import check_dependencies

            all_ok, missing, _installed = check_dependencies()
            if all_ok:
                return

            missing_names = ", ".join(name for name, _ in missing)
            reply = QMessageBox.warning(
                self.iface.mainWindow(),
                "Missing Dependencies",
                f"The following required packages are not installed:\n\n"
                f"  {missing_names}\n\n"
                f"The Timelapse plugin needs these packages to function.\n\n"
                f"Would you like to open Settings to install them?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )

            if reply == QMessageBox.Yes:
                self._open_settings_deps_tab()

        except Exception:
            # Don't let dependency check errors prevent other actions
            pass

    def _open_settings_deps_tab(self):
        """Open the Settings dock and switch to the Dependencies tab."""
        if self._settings_dock is None:
            try:
                from .dialogs.settings_dock import SettingsDockWidget

                self._settings_dock = SettingsDockWidget(
                    self.iface, self.iface.mainWindow()
                )
                self._settings_dock.setObjectName("TimelapseSettingsDock")
                self._settings_dock.visibilityChanged.connect(
                    self._on_settings_visibility_changed
                )
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self._settings_dock)
                self._connect_deps_signal()
            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Settings panel:\n{str(e)}",
                )
                return

        self._settings_dock.show()
        self._settings_dock.raise_()
        self.settings_action.setChecked(True)
        self._settings_dock.show_dependencies_tab()

    def _connect_deps_signal(self):
        """Connect settings dock signals to refresh deps state."""
        if not self._deps_signal_connected and self._settings_dock is not None:
            self._settings_dock.deps_installed.connect(self._on_deps_installed)
            self._settings_dock.auth_succeeded.connect(self._on_auth_completed)
            self._settings_dock.settings_saved.connect(self._try_auto_init_ee)
            self._deps_signal_connected = True

    def _on_deps_installed(self):
        """Handle successful dependency installation from settings dock."""
        from .core.venv_manager import ensure_venv_packages_available

        if ensure_venv_packages_available():
            self._deps_ready = True
            self._post_deps_init()
            self.iface.messageBar().pushSuccess(
                "Timelapse",
                "Dependencies installed! You can now use all Timelapse features.",
            )

    def _on_auth_completed(self):
        """Handle successful EE authentication from the settings dock.

        Tries to initialize EE, and if no project ID is configured yet,
        opens the Settings panel on the Earth Engine tab so the user can
        enter one.
        """
        from .core.timelapse_core import is_ee_initialized

        self._try_auto_init_ee()

        if not is_ee_initialized():
            # Project ID not set yet — open Settings on the EE tab
            self._show_settings_ee_tab()

    def _show_settings_ee_tab(self):
        """Open the Settings dock and switch to the Earth Engine tab."""
        if self._settings_dock is None:
            try:
                from .dialogs.settings_dock import SettingsDockWidget

                self._settings_dock = SettingsDockWidget(
                    self.iface, self.iface.mainWindow()
                )
                self._settings_dock.setObjectName("TimelapseSettingsDock")
                self._settings_dock.visibilityChanged.connect(
                    self._on_settings_visibility_changed
                )
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self._settings_dock)
                self._connect_deps_signal()
            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Settings panel:\n{str(e)}",
                )
                return
        else:
            self._settings_dock.show()
            self._settings_dock.raise_()
        if self._settings_dock is not None:
            self._settings_dock.show_ee_tab()
            self.iface.messageBar().pushInfo(
                "Timelapse",
                "Please enter your Google Cloud project ID and click Save Settings.",
            )

    def _post_deps_init(self):
        """One-time initialization after dependencies are confirmed ready."""
        if self._deps_initialized:
            return
        self._deps_initialized = True
        self._try_auto_init_ee()

    def _try_auto_init_ee(self):
        """Try to auto-initialize Earth Engine using settings or env var."""
        try:
            from .core.timelapse_core import initialize_ee, is_ee_initialized

            if is_ee_initialized():
                return

            # Read project ID from plugin settings
            settings = QSettings()
            project_id = settings.value("QgisTimelapse/project_id", "", type=str)
            if project_id:
                project_id = project_id.strip()
                if not project_id:
                    project_id = None

            # Fall back to environment variable
            if not project_id:
                project_id = os.environ.get("EE_PROJECT_ID", None)

            if project_id:
                try:
                    from qgis.core import QgsMessageLog, Qgis

                    QgsMessageLog.logMessage(
                        f"Auto-initializing Earth Engine with project: {project_id}",
                        "Timelapse",
                        Qgis.Info,
                    )
                    initialize_ee(project=project_id)
                except Exception as exc:
                    from qgis.core import QgsMessageLog, Qgis

                    QgsMessageLog.logMessage(
                        f"Auto-init EE failed: {exc}",
                        "Timelapse",
                        Qgis.Warning,
                    )
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Dock widget toggles
    # ------------------------------------------------------------------

    def toggle_timelapse_dock(self):
        """Toggle the Timelapse dock widget visibility."""
        if self._timelapse_dock is None:
            # Ensure dependencies are installed before creating the dock
            if not self._ensure_deps():
                self.timelapse_action.setChecked(False)
                return

            try:
                from .dialogs.timelapse_dock import TimelapseDockWidget

                self._timelapse_dock = TimelapseDockWidget(
                    self.iface, self.iface.mainWindow()
                )
                self._timelapse_dock.setObjectName("TimelapseDock")
                self._timelapse_dock.visibilityChanged.connect(
                    self._on_timelapse_visibility_changed
                )
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self._timelapse_dock)
                self._timelapse_dock.show()
                self._timelapse_dock.raise_()
                return

            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Timelapse panel:\n{str(e)}",
                )
                self.timelapse_action.setChecked(False)
                return

        # Toggle visibility
        if self._timelapse_dock.isVisible():
            self._timelapse_dock.hide()
        else:
            self._timelapse_dock.show()
            self._timelapse_dock.raise_()

    def _on_timelapse_visibility_changed(self, visible):
        """Handle Timelapse dock visibility change."""
        self.timelapse_action.setChecked(visible)

    def toggle_settings_dock(self):
        """Toggle the Settings dock widget visibility.

        Settings must be accessible even without dependencies installed,
        because the Dependencies tab is how users install them.
        """
        if self._settings_dock is None:
            try:
                from .dialogs.settings_dock import SettingsDockWidget

                self._settings_dock = SettingsDockWidget(
                    self.iface, self.iface.mainWindow()
                )
                self._settings_dock.setObjectName("TimelapseSettingsDock")
                self._settings_dock.visibilityChanged.connect(
                    self._on_settings_visibility_changed
                )
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self._settings_dock)
                self._settings_dock.show()
                self._settings_dock.raise_()
                self._connect_deps_signal()
                return

            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Settings panel:\n{str(e)}",
                )
                self.settings_action.setChecked(False)
                return

        # Toggle visibility
        if self._settings_dock.isVisible():
            self._settings_dock.hide()
        else:
            self._settings_dock.show()
            self._settings_dock.raise_()

    def _on_settings_visibility_changed(self, visible):
        """Handle Settings dock visibility change."""
        self.settings_action.setChecked(visible)

    # ------------------------------------------------------------------
    # About and updates
    # ------------------------------------------------------------------

    def show_about(self):
        """Display the about dialog."""
        try:
            from .dialogs.about_dialog import AboutDialog

            dialog = AboutDialog(self.plugin_dir, self.iface.mainWindow())
            dialog.exec_()
        except Exception:
            # Fallback to simple message box
            version = self._get_version()
            about_text = f"""
<h2>Timelapse Animation Creator for QGIS</h2>
<p>Version: {version}</p>
<p>Author: Qiusheng Wu</p>

<h3>Features:</h3>
<ul>
<li><b>NAIP Timelapse:</b> High-resolution aerial imagery (US only)</li>
<li><b>Landsat Timelapse:</b> Long-term satellite imagery (1984-present)</li>
<li><b>Sentinel-2 Timelapse:</b> Multispectral satellite imagery</li>
<li><b>Sentinel-1 Timelapse:</b> SAR radar imagery</li>
<li><b>MODIS NDVI:</b> Vegetation index animations</li>
<li><b>GOES:</b> Weather satellite animations</li>
</ul>

<h3>Links:</h3>
<ul>
<li><a href="https://github.com/opengeos/qgis-timelapse-plugin">GitHub Repository</a></li>
<li><a href="https://github.com/opengeos/qgis-timelapse-plugin/issues">Report Issues</a></li>
</ul>

<p>Licensed under MIT License</p>
"""
            QMessageBox.about(
                self.iface.mainWindow(),
                self.tr("About Timelapse"),
                about_text,
            )

    def show_update_checker(self):
        """Display the update checker dialog."""
        try:
            from .dialogs.update_checker import UpdateCheckerDialog
        except ImportError as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to import update checker dialog:\n{str(e)}",
            )
            return

        try:
            dialog = UpdateCheckerDialog(self.plugin_dir, self.iface.mainWindow())
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to open update checker:\n{str(e)}",
            )

    def _get_version(self):
        """Read the current version from local metadata.txt."""
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
