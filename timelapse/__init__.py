"""
QGIS Timelapse Animation Creator Plugin

This plugin allows users to create timelapse animations from satellite
and aerial imagery (NAIP, Landsat, Sentinel-2, Sentinel-1, GOES, MODIS)
using Google Earth Engine.
"""

from .timelapse_plugin import TimelapsePlugin


def classFactory(iface):
    """Load TimelapsePlugin class from file timelapse_plugin.

    Args:
        iface: A QGIS interface instance.

    Returns:
        TimelapsePlugin: The plugin instance.
    """
    return TimelapsePlugin(iface)

