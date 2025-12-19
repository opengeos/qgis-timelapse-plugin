"""
QGIS Timelapse Animation Creator Plugin

Main plugin module that handles QGIS integration.
"""

import os
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsProject

from .timelapse_dialog import TimelapseDockWidget


class TimelapsePlugin:
    """QGIS Plugin for creating timelapse animations from satellite imagery."""

    def __init__(self, iface):
        """Constructor.

        Args:
            iface: A QGIS interface instance.
        """
        self.iface = iface
        self.plugin_dir = Path(__file__).parent
        
        # Initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = self.plugin_dir / 'i18n' / f'timelapse_{locale}.qm'

        if locale_path.exists():
            self.translator = QTranslator()
            self.translator.load(str(locale_path))
            QCoreApplication.installTranslator(self.translator)

        self.actions = []
        self.menu = self.tr('&Timelapse')
        self.toolbar = self.iface.addToolBar('Timelapse')
        self.toolbar.setObjectName('TimelapseToolbar')
        
        self.dock_widget = None

    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        Args:
            message: String to translate.
        
        Returns:
            str: Translated string.
        """
        return QCoreApplication.translate('TimelapsePlugin', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None
    ):
        """Add a toolbar icon and menu item.

        Args:
            icon_path: Path to the icon file.
            text: Text for the menu item.
            callback: Function to call when the action is triggered.
            enabled_flag: Enable/disable the action.
            add_to_menu: Add action to the menu.
            add_to_toolbar: Add action to the toolbar.
            status_tip: Status bar message.
            whats_this: What's This help text.
            parent: Parent widget.
        
        Returns:
            QAction: The created action.
        """
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToRasterMenu(self.menu, action)

        self.actions.append(action)
        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_path = str(self.plugin_dir / 'icons' / 'icon.png')
        self.add_action(
            icon_path,
            text=self.tr('Create Timelapse'),
            callback=self.run,
            parent=self.iface.mainWindow(),
            status_tip=self.tr('Create timelapse animations from satellite imagery')
        )

    def unload(self):
        """Remove the plugin menu items and icons from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginRasterMenu(self.tr('&Timelapse'), action)
            self.iface.removeToolBarIcon(action)
        
        # Remove dock widget if it exists
        if self.dock_widget is not None:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget = None
        
        del self.toolbar

    def run(self):
        """Run the plugin - show/hide the dockable panel."""
        if self.dock_widget is None:
            self.dock_widget = TimelapseDockWidget(self.iface)
            self.dock_widget.closed.connect(self.on_dock_closed)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
        else:
            # Toggle visibility
            if self.dock_widget.isVisible():
                self.dock_widget.hide()
            else:
                self.dock_widget.show()
    
    def on_dock_closed(self):
        """Handle dock widget close event."""
        # Keep the reference but allow it to be shown again
        pass
