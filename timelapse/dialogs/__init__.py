"""
Timelapse Plugin Dialogs

This module contains the dialog and dock widget classes for the Timelapse plugin.
"""

from .timelapse_dock import TimelapseDockWidget
from .update_checker import UpdateCheckerDialog
from .about_dialog import AboutDialog

__all__ = [
    "TimelapseDockWidget",
    "UpdateCheckerDialog",
    "AboutDialog",
]

