"""
Timelapse Core Processing Module

This module contains the core functionality for creating timelapse animations
from satellite and aerial imagery using Google Earth Engine.
"""

from .timelapse_core import (
    check_dependencies,
    reload_dependencies,
    get_ee_project,
    is_ee_initialized,
    initialize_ee,
    bbox_to_ee_geometry,
    geojson_to_ee_geometry,
    create_naip_timelapse,
    create_sentinel2_timelapse,
    create_sentinel1_timelapse,
    create_landsat_timelapse,
    create_modis_ndvi_timelapse,
    create_goes_timelapse,
)

__all__ = [
    "check_dependencies",
    "reload_dependencies",
    "get_ee_project",
    "is_ee_initialized",
    "initialize_ee",
    "bbox_to_ee_geometry",
    "geojson_to_ee_geometry",
    "create_naip_timelapse",
    "create_sentinel2_timelapse",
    "create_sentinel1_timelapse",
    "create_landsat_timelapse",
    "create_modis_ndvi_timelapse",
    "create_goes_timelapse",
]
