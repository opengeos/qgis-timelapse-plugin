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

        # Dock widget (lazy loaded)
        self._timelapse_dock = None

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

        # Add Timelapse Panel action (checkable for dock toggle)
        self.timelapse_action = self.add_action(
            main_icon,
            self.tr("Create Timelapse"),
            self.toggle_timelapse_dock,
            status_tip=self.tr("Toggle Timelapse Animation Creator Panel"),
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
        # Remove dock widget
        if self._timelapse_dock:
            self.iface.removeDockWidget(self._timelapse_dock)
            self._timelapse_dock.deleteLater()
            self._timelapse_dock = None

        # Remove actions
        for action in self.actions:
            self.iface.removePluginRasterMenu(self.tr("&Timelapse"), action)

        # Remove toolbar
        if self.toolbar:
            del self.toolbar

        # Remove menu
        if self.menu:
            self.menu.deleteLater()

    def _ensure_dependencies(self) -> bool:
        """Check if dependencies are available and prompt installation if not.

        Returns:
            True if dependencies are ready, False if user cancelled.
        """
        from .core import venv_manager

        if venv_manager.dependencies_available():
            venv_manager.ensure_venv_packages_available()
            from .core.timelapse_core import reload_dependencies

            reload_dependencies()
            return True

        # Dependencies not found -- show the installer dialog
        from .dialogs.dependency_dialog import DependencyDialog

        dialog = DependencyDialog(self.iface.mainWindow())
        dialog.exec_()

        if dialog.was_successful():
            from .core.timelapse_core import reload_dependencies

            reload_dependencies()
            return True

        return False

    def toggle_timelapse_dock(self):
        """Toggle the Timelapse dock widget visibility."""
        if self._timelapse_dock is None:
            # Ensure dependencies are installed before creating the dock
            if not self._ensure_dependencies():
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

    def show_about(self):
        """Display the about dialog."""
        try:
            from .dialogs.about_dialog import AboutDialog

            dialog = AboutDialog(self.plugin_dir, self.iface.mainWindow())
            dialog.exec_()
        except Exception as e:
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
