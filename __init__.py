"""
QGIS Timelapse Animation Creator Plugin

This plugin allows users to create timelapse animations from satellite
and aerial imagery (NAIP, Sentinel-2, Sentinel-1) using Google Earth Engine.
"""


def classFactory(iface):
    """Load TimelapsePlugin class from file timelapse_plugin.

    Args:
        iface: A QGIS interface instance.

    Returns:
        TimelapsePlugin: The plugin instance.
    """
    from .timelapse_plugin import TimelapsePlugin

    return TimelapsePlugin(iface)
