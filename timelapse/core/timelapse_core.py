"""
Timelapse Core Processing Module

This module contains the core functionality for creating timelapse animations
from satellite and aerial imagery using Google Earth Engine.
Based on the geemap timelapse module.
"""

import datetime
import glob
import os
import re
import tempfile
from typing import Optional, Union, List, Dict, Any

try:
    import ee
except ImportError:
    ee = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"Warning: Failed to import PIL (Pillow): {e}")
    print("Timelapse GIFs will be created without text overlays.")
    Image = None
    ImageDraw = None
    ImageFont = None
except Exception as e:
    print(f"Error: Unexpected error importing PIL (Pillow): {e}")
    print("Timelapse GIFs will be created without text overlays.")
    Image = None
    ImageDraw = None
    ImageFont = None


def check_dependencies() -> Dict[str, bool]:
    """Check if all required dependencies are installed.

    Returns:
        Dict with dependency names and their availability.
    """
    return {
        "earthengine-api": ee is not None,
        "Pillow": Image is not None,
    }


def get_ee_project() -> Optional[str]:
    """Get GEE project ID from environment variable.

    Returns:
        Project ID string or None.
    """
    return os.environ.get("EE_PROJECT_ID", None)


# Global flag to track if EE has been initialized
_ee_initialized = False


def is_ee_initialized() -> bool:
    """Check if Earth Engine has been initialized.

    Returns:
        True if initialized, False otherwise.
    """
    global _ee_initialized
    return _ee_initialized


def initialize_ee(project: str = None, force: bool = False) -> bool:
    """Initialize Google Earth Engine.

    Args:
        project: GEE project ID. If None, uses EE_PROJECT_ID env variable.
        force: If True, reinitialize even if already initialized.

    Returns:
        True if initialization successful, False otherwise.
    """
    global _ee_initialized

    if ee is None:
        return False

    # Skip if already initialized (unless forced)
    if _ee_initialized and not force:
        return True

    # Use provided project or fall back to env variable
    if project is None or project.strip() == "":
        project = get_ee_project()

    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
        _ee_initialized = True
        return True
    except Exception:
        try:
            ee.Authenticate()
            if project:
                ee.Initialize(project=project)
            else:
                ee.Initialize()
            _ee_initialized = True
            return True
        except Exception:
            return False


def bbox_to_ee_geometry(
    xmin: float, ymin: float, xmax: float, ymax: float
) -> "ee.Geometry":
    """Convert bounding box to Earth Engine Geometry.

    Args:
        xmin: Minimum longitude.
        ymin: Minimum latitude.
        xmax: Maximum longitude.
        ymax: Maximum latitude.

    Returns:
        ee.Geometry.Rectangle object.
    """
    return ee.Geometry.Rectangle([xmin, ymin, xmax, ymax], geodesic=False)


def geojson_to_ee_geometry(geojson: dict) -> "ee.Geometry":
    """Convert GeoJSON to Earth Engine Geometry.

    Args:
        geojson: GeoJSON dictionary.

    Returns:
        ee.Geometry object.
    """
    return ee.Geometry(geojson)


def vector_to_geojson(
    vector_path: str,
    bbox: Dict[str, float] = None,
) -> dict:
    """Convert a local vector file to GeoJSON, optionally filtering by bbox.

    Args:
        vector_path: Path to vector file (Shapefile, GeoJSON, GeoPackage, KML, etc.).
        bbox: Optional bounding box dict with xmin, ymin, xmax, ymax (WGS84).

    Returns:
        GeoJSON dictionary.
    """
    import json

    try:
        from osgeo import ogr, osr
    except ImportError:
        raise ImportError("GDAL/OGR is required for vector file support.")

    # Open the vector file
    ds = ogr.Open(vector_path)
    if ds is None:
        raise ValueError(f"Could not open vector file: {vector_path}")

    layer = ds.GetLayer()
    if layer is None:
        raise ValueError(f"Could not read layer from: {vector_path}")

    # Get source CRS and create transformation to WGS84
    source_srs = layer.GetSpatialRef()
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)

    transform = None
    if source_srs is not None and not source_srs.IsSame(target_srs):
        # Handle axis order for GDAL 3+
        source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transform = osr.CoordinateTransformation(source_srs, target_srs)

    # Set spatial filter if bbox provided
    if bbox is not None:
        # Create bbox geometry in WGS84
        bbox_geom = ogr.Geometry(ogr.wkbPolygon)
        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(bbox["xmin"], bbox["ymin"])
        ring.AddPoint(bbox["xmax"], bbox["ymin"])
        ring.AddPoint(bbox["xmax"], bbox["ymax"])
        ring.AddPoint(bbox["xmin"], bbox["ymax"])
        ring.AddPoint(bbox["xmin"], bbox["ymin"])
        bbox_geom.AddGeometry(ring)

        # Transform bbox to source CRS if needed
        if transform is not None:
            inverse_transform = osr.CoordinateTransformation(target_srs, source_srs)
            bbox_geom.Transform(inverse_transform)

        layer.SetSpatialFilter(bbox_geom)

    # Build GeoJSON FeatureCollection
    features = []
    for feature in layer:
        geom = feature.GetGeometryRef()
        if geom is None:
            continue

        # Clone and transform geometry
        geom = geom.Clone()
        if transform is not None:
            geom.Transform(transform)

        # Get properties
        properties = {}
        for i in range(feature.GetFieldCount()):
            field_name = feature.GetFieldDefnRef(i).GetName()
            field_value = feature.GetField(i)
            properties[field_name] = field_value

        geojson_geom = json.loads(geom.ExportToJson())
        features.append(
            {
                "type": "Feature",
                "geometry": geojson_geom,
                "properties": properties,
            }
        )

    ds = None  # Close dataset

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def geojson_to_ee_featurecollection(
    geojson: dict,
    geodesic: bool = False,
) -> "ee.FeatureCollection":
    """Convert GeoJSON to Earth Engine FeatureCollection.

    Args:
        geojson: GeoJSON dictionary (FeatureCollection or Feature).
        geodesic: Whether line segments should be interpreted as spherical geodesics.

    Returns:
        ee.FeatureCollection object.
    """
    if geojson["type"] == "FeatureCollection":
        for feature in geojson["features"]:
            if feature["geometry"]["type"] != "Point":
                feature["geometry"]["geodesic"] = geodesic
        return ee.FeatureCollection(geojson)
    elif geojson["type"] == "Feature":
        geojson["geometry"]["geodesic"] = geodesic
        return ee.FeatureCollection([ee.Feature(geojson)])
    else:
        # Assume it's a geometry
        return ee.FeatureCollection([ee.Feature(ee.Geometry(geojson))])


def load_overlay_data(
    overlay_data: str,
    source_type: str = "local",
    bbox: Dict[str, float] = None,
) -> "ee.FeatureCollection":
    """Load overlay data from local file or EE asset.

    Args:
        overlay_data: Path to local vector file or ee.FeatureCollection asset ID.
        source_type: Either "local" or "ee".
        bbox: Optional bounding box for filtering (xmin, ymin, xmax, ymax in WGS84).

    Returns:
        ee.FeatureCollection object.
    """
    if source_type == "local":
        # Convert local file to GeoJSON, filtering by bbox
        geojson = vector_to_geojson(overlay_data, bbox)
        if not geojson["features"]:
            raise ValueError("No features found intersecting the bounding box.")
        return geojson_to_ee_featurecollection(geojson)
    else:
        # Load from Earth Engine asset
        # Strip whitespace from asset ID
        asset_id = overlay_data.strip()
        # Return the FeatureCollection directly without filtering
        # The paint operation will only render what's visible in the region
        return ee.FeatureCollection(asset_id)


def check_color(color: str) -> str:
    """Check and normalize color to hex format.

    Args:
        color: Color string (name like 'red', hex like '#ff0000' or 'ff0000').

    Returns:
        Hex color code with # prefix.
    """
    if color.startswith("#"):
        return color
    # Common color names to hex
    color_map = {
        "red": "#FF0000",
        "green": "#00FF00",
        "blue": "#0000FF",
        "black": "#000000",
        "white": "#FFFFFF",
        "yellow": "#FFFF00",
        "cyan": "#00FFFF",
        "magenta": "#FF00FF",
        "orange": "#FFA500",
        "purple": "#800080",
        "pink": "#FFC0CB",
        "brown": "#A52A2A",
        "gray": "#808080",
        "grey": "#808080",
    }
    if color.lower() in color_map:
        return color_map[color.lower()]
    # Assume it's a hex without #
    if len(color) == 6:
        return f"#{color}"
    return color


def add_overlay(
    collection: "ee.ImageCollection",
    overlay_data,
    color: str = "black",
    width: int = 1,
    opacity: float = 1.0,
    region: "ee.Geometry" = None,
) -> "ee.ImageCollection":
    """Add vector overlay to an image collection.

    Adapted from geemap.timelapse.add_overlay.

    Args:
        collection: The image collection to add the overlay to.
        overlay_data: The ee.FeatureCollection, asset ID string, or ee.Geometry.
        color: The color of the overlay (name or hex).
        width: The stroke width of the overlay.
        opacity: The opacity of the overlay (0-1).
        region: Optional region to filter the overlay by.

    Returns:
        ee.ImageCollection with the overlay blended onto each image.
    """
    # Convert overlay_data to FeatureCollection if needed (same as geemap)
    if not isinstance(overlay_data, ee.FeatureCollection):
        if isinstance(overlay_data, str):
            overlay_data = ee.FeatureCollection(overlay_data)
        elif isinstance(overlay_data, ee.Feature):
            overlay_data = ee.FeatureCollection([overlay_data])
        elif isinstance(overlay_data, ee.Geometry):
            overlay_data = ee.FeatureCollection([ee.Feature(overlay_data)])

    # Get target projection from first image
    target_proj = collection.first().projection()

    # Filter and clip by region if provided
    region_geom = None
    if region is not None:
        if isinstance(region, ee.Geometry):
            region_geom = region
        else:
            region_geom = region.geometry()
        overlay_data = overlay_data.filterBounds(region_geom).map(
            lambda feature: feature.intersection(region_geom, ee.ErrorMargin(1))
        )

    # Normalize color
    hex_color = check_color(color)
    # Remove # for palette
    palette_color = hex_color.lstrip("#")

    # Create overlay image with proper projection (same as geemap)
    empty = ee.Image().byte().setDefaultProjection(target_proj)
    image = empty.paint(
        featureCollection=overlay_data,
        color=1,
        width=width,
    ).visualize(palette=[palette_color], opacity=opacity)
    image = image.setDefaultProjection(target_proj)

    # Clip to region if provided
    if region_geom is not None:
        image = image.clip(region_geom)

    # Blend overlay with each image in collection
    blend_col = collection.map(
        lambda img: img.blend(image)
        .setDefaultProjection(img.projection())
        .set("system:time_start", img.get("system:time_start"))
    )
    return blend_col


def date_sequence(
    start_year: int,
    end_year: int,
    start_date: str,
    end_date: str,
    frequency: str = "year",
    step: int = 1,
) -> list:
    """Generate a sequence of date ranges based on frequency.

    Args:
        start_year: Starting year.
        end_year: Ending year.
        start_date: Start date within year (MM-dd).
        end_date: End date within year (MM-dd).
        frequency: Temporal frequency ('year', 'quarter', 'month', 'day').
        step: Step size.

    Returns:
        List of tuples (start_date, end_date, label) for each time period.
    """
    from datetime import date, timedelta

    # Validate and parse start_date and end_date in "MM-dd" format
    try:
        start_dt = datetime.datetime.strptime(start_date, "%m-%d")
        end_dt = datetime.datetime.strptime(end_date, "%m-%d")
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "start_date and end_date must be strings in 'MM-dd' format, "
            f"got start_date={start_date!r}, end_date={end_date!r}"
        ) from exc

    start_month = start_dt.month
    start_day = start_dt.day
    end_month = end_dt.month
    end_day = end_dt.day
    dates = []

    if frequency == "year":
        for year in range(start_year, end_year + 1, step):
            start = date(year, start_month, start_day)
            end = date(year, end_month, end_day)
            label = str(year)
            dates.append((start, end, label))

    elif frequency == "quarter":
        quarters = [(1, 3), (4, 6), (7, 9), (10, 12)]
        for year in range(start_year, end_year + 1, step):
            for q_idx, (q_start, q_end) in enumerate(quarters, 1):
                # Check if quarter is within the date range
                q_start_date = date(year, q_start, 1)
                if q_end == 12:
                    q_end_date = date(year, 12, 31)
                else:
                    q_end_date = date(year, q_end + 1, 1) - timedelta(days=1)

                # Build seasonal date ranges for this year.
                # For non-wrapping seasons (start_month <= end_month), the range is
                # fully contained within the same calendar year.
                # For wrapping seasons (start_month > end_month), the range spans
                # across the year boundary. In that case, quarters in a given year
                # can overlap either the late-year portion (year, start_month..Dec)
                # or the early-year portion (Jan..end_month in the same year).
                if start_month <= end_month:
                    seasonal_ranges = [
                        (
                            date(year, start_month, start_day),
                            date(year, end_month, end_day),
                        )
                    ]
                else:
                    seasonal_ranges = [
                        # Season starting in the previous year and ending in this year.
                        (
                            date(year - 1, start_month, start_day),
                            date(year, end_month, end_day),
                        ),
                        # Season starting in this year and ending in the next year.
                        (
                            date(year, start_month, start_day),
                            date(year + 1, end_month, end_day),
                        ),
                    ]

                # Only include quarters that overlap with any of the seasonal ranges.
                for season_start, season_end in seasonal_ranges:
                    if q_end_date >= season_start and q_start_date <= season_end:
                        label = f"{year}-Q{q_idx}"
                        dates.append((q_start_date, q_end_date, label))
                        break

    elif frequency == "month":
        for year in range(start_year, end_year + 1):
            for month in range(1, 13, step):
                # Check if month is within seasonal range
                if start_month <= end_month:
                    if month < start_month or month > end_month:
                        continue
                else:  # Wraps around year end
                    if month > end_month and month < start_month:
                        continue

                month_start = date(year, month, 1)
                if month == 12:
                    month_end = date(year, 12, 31)
                else:
                    month_end = date(year, month + 1, 1) - timedelta(days=1)
                label = f"{year}-{month:02d}"
                dates.append((month_start, month_end, label))

    elif frequency == "day":
        current = date(start_year, start_month, start_day)
        end = date(end_year, end_month, end_day)
        while current <= end:
            label = current.strftime("%Y-%m-%d")
            dates.append((current, current, label))
            current += timedelta(days=step)

    return dates


def create_timeseries(
    collection: "ee.ImageCollection",
    start_date: str,
    end_date: str,
    region: "ee.Geometry" = None,
    bands: List[str] = None,
    frequency: str = "year",
    reducer: str = "median",
    date_format: str = None,
    drop_empty: bool = True,
    step: int = 1,
) -> "ee.ImageCollection":
    """Create a time series from an image collection.

    Args:
        collection: Input image collection.
        start_date: Start date in 'YYYY-MM-dd' format.
        end_date: End date in 'YYYY-MM-dd' format.
        region: Region of interest.
        bands: List of band names.
        frequency: Temporal frequency ('year', 'month', 'day').
        reducer: Reducer type ('median', 'mean', 'min', 'max').
        date_format: Output date format.
        drop_empty: Whether to drop empty images.
        step: Step size for date sequence.

    Returns:
        ee.ImageCollection with aggregated images.
    """
    if region is not None:
        collection = collection.filterBounds(region)

    collection = collection.filterDate(start_date, end_date)

    if bands is not None:
        collection = collection.select(bands)

    # Get reducer function
    reducers = {
        "median": ee.Reducer.median(),
        "mean": ee.Reducer.mean(),
        "min": ee.Reducer.min(),
        "max": ee.Reducer.max(),
        "sum": ee.Reducer.sum(),
    }
    selected_reducer = reducers.get(reducer, ee.Reducer.median())

    # Set date format based on frequency
    if date_format is None:
        date_formats = {
            "year": "YYYY",
            "month": "YYYY-MM",
            "day": "YYYY-MM-dd",
        }
        date_format = date_formats.get(frequency, "YYYY-MM-dd")

    # Create date sequence
    start = ee.Date(start_date)
    end = ee.Date(end_date)

    freq_units = {
        "year": "year",
        "month": "month",
        "day": "day",
    }
    unit = freq_units.get(frequency, "year")

    # Generate sequence of dates
    def get_sequence(start, end, unit, step):
        diff = end.difference(start, unit).round()
        sequence = ee.List.sequence(0, diff.subtract(1), step)
        return sequence.map(lambda n: start.advance(n, unit))

    dates = get_sequence(start, end, unit, step)

    def aggregate_images(date):
        date = ee.Date(date)
        end_date = date.advance(1, unit)
        filtered = collection.filterDate(date, end_date)

        if region is not None:
            reduced = filtered.reduce(selected_reducer).clip(region)
        else:
            reduced = filtered.reduce(selected_reducer)

        return reduced.set(
            {
                "system:time_start": date.millis(),
                "system:date": date.format(date_format),
                "empty": filtered.size().eq(0),
            }
        )

    result = ee.ImageCollection(dates.map(aggregate_images))

    if drop_empty:
        result = result.filterMetadata("empty", "equals", 0)

    return result


def naip_timeseries(
    roi: "ee.Geometry",
    start_year: int = 2003,
    end_year: int = None,
    bands: List[str] = None,
    step: int = 1,
) -> "ee.ImageCollection":
    """Create NAIP annual time series.

    Args:
        roi: Region of interest.
        start_year: Starting year (default 2003).
        end_year: Ending year (default current year).
        bands: List of bands to use ('R', 'G', 'B', 'N').
        step: Year step.

    Returns:
        ee.ImageCollection of annual NAIP mosaics.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    if bands is None:
        bands = ["R", "G", "B"]

    # Check if NIR band is requested
    use_nir = "N" in bands

    def get_annual_naip(year):
        year = ee.Number(year)
        collection = ee.ImageCollection("USDA/NAIP/DOQQ")

        if roi is not None:
            collection = collection.filterBounds(roi)

        start_date = ee.Date.fromYMD(year, 1, 1)
        end_date = ee.Date.fromYMD(year, 12, 31)
        naip = collection.filterDate(start_date, end_date)

        # Filter for 4-band imagery if NIR is requested
        if use_nir:
            naip = naip.filter(ee.Filter.listContains("system:band_names", "N"))

        if roi is not None:
            image = naip.mosaic().clip(roi)
        else:
            image = naip.mosaic()

        return image.set(
            {
                "system:time_start": start_date.millis(),
                "system:time_end": end_date.millis(),
                "system:date": start_date.format("YYYY"),
                "empty": naip.size().eq(0),
            }
        )

    years = ee.List.sequence(start_year, end_year, step)
    collection = ee.ImageCollection(years.map(get_annual_naip))

    return collection.filterMetadata("empty", "equals", 0)


def sentinel2_timeseries(
    roi: "ee.Geometry",
    start_year: int = 2015,
    end_year: int = None,
    start_date: str = "06-10",
    end_date: str = "09-20",
    bands: List[str] = None,
    apply_fmask: bool = True,
    cloud_pct: int = 30,
    frequency: str = "year",
    reducer: str = "median",
    step: int = 1,
) -> "ee.ImageCollection":
    """Create Sentinel-2 time series with configurable frequency.

    Args:
        roi: Region of interest.
        start_year: Starting year.
        end_year: Ending year.
        start_date: Start date within year (MM-dd).
        end_date: End date within year (MM-dd).
        bands: List of bands to include.
        apply_fmask: Whether to apply cloud masking.
        cloud_pct: Maximum cloud percentage.
        frequency: Temporal frequency ('year', 'quarter', 'month', 'day').
        reducer: Reducer type.
        step: Step size.

    Returns:
        ee.ImageCollection of Sentinel-2 composites.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    # Band mapping
    band_mapping = {
        "Blue": "B2",
        "Green": "B3",
        "Red": "B4",
        "Red Edge 1": "B5",
        "Red Edge 2": "B6",
        "Red Edge 3": "B7",
        "NIR": "B8",
        "Red Edge 4": "B8A",
        "SWIR1": "B11",
        "SWIR2": "B12",
        "QA60": "QA60",
    }

    if bands is None:
        bands = ["B8", "B4", "B3"]  # NIR, Red, Green
    else:
        bands = [band_mapping.get(b, b) for b in bands]

    def mask_clouds(image):
        """Apply cloud mask to Sentinel-2 image."""
        qa = image.select("QA60")
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mask = (
            qa.bitwiseAnd(cloud_bit_mask)
            .eq(0)
            .And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        )
        return image.updateMask(mask).divide(10000)

    # Generate date sequence based on frequency
    dates = date_sequence(start_year, end_year, start_date, end_date, frequency, step)

    def get_s2_composite(date_info):
        start_dt, end_dt, label = date_info
        start = ee.Date(start_dt.isoformat())
        end = ee.Date(end_dt.isoformat()).advance(1, "day")

        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(roi)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
        )

        if apply_fmask:
            collection = collection.map(mask_clouds)
        else:
            collection = collection.map(lambda img: img.divide(10000))

        # Select bands (excluding QA60 for final output)
        select_bands = [b for b in bands if b != "QA60"]
        collection = collection.select(select_bands)

        composite = collection.median()

        if roi is not None:
            composite = composite.clip(roi)

        return composite.set(
            {
                "system:time_start": start.millis(),
                "system:date": label,
                "empty": collection.size().eq(0),
            }
        )

    images = [get_s2_composite(d) for d in dates]
    result = ee.ImageCollection(images)

    return result.filterMetadata("empty", "equals", 0)


def sentinel1_timeseries(
    roi: "ee.Geometry",
    start_year: int = 2015,
    end_year: int = None,
    start_date: str = "01-01",
    end_date: str = "12-31",
    bands: List[str] = None,
    orbit: List[str] = None,
    frequency: str = "year",
    reducer: str = "median",
    step: int = 1,
) -> "ee.ImageCollection":
    """Create Sentinel-1 time series with configurable frequency.

    Args:
        roi: Region of interest.
        start_year: Starting year.
        end_year: Ending year.
        start_date: Start date within year (MM-dd).
        end_date: End date within year (MM-dd).
        bands: List of bands (VV, VH, HH, HV).
        orbit: Orbit direction ('ascending', 'descending', or both).
        frequency: Temporal frequency ('year', 'quarter', 'month', 'day').
        reducer: Reducer type.
        step: Step size.

    Returns:
        ee.ImageCollection of Sentinel-1 composites.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    if bands is None:
        bands = ["VV"]

    if orbit is None:
        orbit = ["ASCENDING", "DESCENDING"]
    else:
        orbit = [o.upper() for o in orbit]

    # Generate date sequence based on frequency
    dates = date_sequence(start_year, end_year, start_date, end_date, frequency, step)

    def get_s1_composite(date_info):
        start_dt, end_dt, label = date_info
        start = ee.Date(start_dt.isoformat())
        end = ee.Date(end_dt.isoformat()).advance(1, "day")

        collection = (
            ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(roi)
            .filterDate(start, end)
            .filter(ee.Filter.inList("orbitProperties_pass", orbit))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", bands[0]))
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .select(bands)
        )

        composite = collection.median()

        if roi is not None:
            composite = composite.clip(roi)

        return composite.set(
            {
                "system:time_start": start.millis(),
                "system:date": label,
                "empty": collection.size().eq(0),
            }
        )

    images = [get_s1_composite(d) for d in dates]
    result = ee.ImageCollection(images)

    return result.filterMetadata("empty", "equals", 0)


def landsat_timeseries(
    roi: "ee.Geometry",
    start_year: int = 1984,
    end_year: int = None,
    start_date: str = "06-10",
    end_date: str = "09-20",
    apply_fmask: bool = True,
    frequency: str = "year",
    step: int = 1,
) -> "ee.ImageCollection":
    """Create Landsat time series with configurable frequency.

    Combines Landsat 4, 5, 7, 8, and 9 surface reflectance data
    with consistent band naming: Blue, Green, Red, NIR, SWIR1, SWIR2.

    Args:
        roi: Region of interest.
        start_year: Starting year (default 1984).
        end_year: Ending year (default current year).
        start_date: Start date within year (MM-dd).
        end_date: End date within year (MM-dd).
        apply_fmask: Whether to apply cloud/shadow masking.
        frequency: Temporal frequency ('year', 'quarter', 'month', 'day').
        step: Step size.

    Returns:
        ee.ImageCollection of Landsat composites.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    # Landsat collections
    LC09col = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
    LC08col = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
    LE07col = ee.ImageCollection("LANDSAT/LE07/C02/T1_L2")
    LT05col = ee.ImageCollection("LANDSAT/LT05/C02/T1_L2")
    LT04col = ee.ImageCollection("LANDSAT/LT04/C02/T1_L2")

    def col_filter(col, roi, start_dt, end_dt):
        return col.filterBounds(roi).filterDate(start_dt, end_dt)

    def rename_oli(img):
        """Rename OLI bands (Landsat 8, 9)."""
        return img.select(
            ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"],
            ["Blue", "Green", "Red", "NIR", "SWIR1", "SWIR2"],
        )

    def rename_etm(img):
        """Rename ETM+/TM bands (Landsat 4, 5, 7)."""
        return img.select(
            ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"],
            ["Blue", "Green", "Red", "NIR", "SWIR1", "SWIR2"],
        )

    def apply_scale_factors(img):
        """Apply scaling factors to Landsat SR data."""
        optical = img.select("SR_B.").multiply(0.0000275).add(-0.2)
        return img.addBands(optical, None, True)

    def fmask(image):
        """Apply quality mask to Landsat image."""
        qa_mask = image.select("QA_PIXEL").bitwiseAnd(int("11111", 2)).eq(0)
        return image.updateMask(qa_mask)

    def prep_oli(img):
        """Prepare OLI image (Landsat 8, 9)."""
        orig = img
        if apply_fmask:
            img = fmask(img)
        img = apply_scale_factors(img)
        img = rename_oli(img)
        return ee.Image(img.copyProperties(orig, orig.propertyNames())).resample(
            "bicubic"
        )

    def prep_etm(img):
        """Prepare ETM+/TM image (Landsat 4, 5, 7)."""
        orig = img
        if apply_fmask:
            img = fmask(img)
        img = apply_scale_factors(img)
        img = rename_etm(img)
        return ee.Image(img.copyProperties(orig, orig.propertyNames())).resample(
            "bicubic"
        )

    # Dummy image for missing periods
    band_names = ee.List(["Blue", "Green", "Red", "NIR", "SWIR1", "SWIR2"])
    filler_values = ee.List.repeat(0, band_names.size())
    dummy_img = ee.Image.constant(filler_values).rename(band_names).selfMask().float()

    # Generate date sequence based on frequency
    dates = date_sequence(start_year, end_year, start_date, end_date, frequency, step)

    def get_composite(date_info):
        start_dt, end_dt, label = date_info
        start = ee.Date(start_dt.isoformat())
        end = ee.Date(end_dt.isoformat()).advance(1, "day")

        # Filter and prepare each collection
        lc09 = col_filter(LC09col, roi, start, end).map(prep_oli)
        lc08 = col_filter(LC08col, roi, start, end).map(prep_oli)
        le07 = col_filter(LE07col, roi, start, end).map(prep_etm)
        lt05 = col_filter(LT05col, roi, start, end).map(prep_etm)
        lt04 = col_filter(LT04col, roi, start, end).map(prep_etm)

        # Merge collections
        col = lc09.merge(lc08).merge(le07).merge(lt05).merge(lt04)

        composite = col.median()
        n_bands = composite.bandNames().size()
        composite = ee.Image(ee.Algorithms.If(n_bands, composite, dummy_img))

        if roi is not None:
            composite = composite.clip(roi)

        return composite.set(
            {
                "system:time_start": start.millis(),
                "system:date": label,
                "nBands": n_bands,
                "empty": n_bands.eq(0),
            }
        )

    images = [get_composite(d) for d in dates]
    result = ee.ImageCollection(images)

    return result.filterMetadata("empty", "equals", 0)


def download_ee_video(
    collection: "ee.ImageCollection",
    video_args: dict,
    out_gif: str,
) -> str:
    """Download Earth Engine video/animation.

    Args:
        collection: Image collection to animate.
        video_args: Video parameters dict.
        out_gif: Output GIF path.

    Returns:
        Path to output GIF.
    """
    import urllib.request
    import urllib.error

    try:
        url = collection.getVideoThumbURL(video_args)
        print(f"[DEBUG] Video URL generated successfully")
    except Exception as e:
        raise RuntimeError(f"Failed to generate video URL: {e}") from e

    # Download the GIF
    try:
        urllib.request.urlretrieve(url, out_gif)
    except urllib.error.HTTPError as e:
        # Read the error response body for more details
        error_body = ""
        if hasattr(e, "read"):
            try:
                error_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
        raise RuntimeError(
            f"Failed to download video: HTTP {e.code} {e.reason}. "
            f"Details: {error_body[:500] if error_body else 'No details'}"
        ) from e

    return out_gif


def make_gif(
    images: Union[List[str], str],
    out_gif: str,
    ext: str = "jpg",
    fps: int = 10,
    loop: int = 0,
    clean_up: bool = False,
) -> None:
    """Create a GIF from a list of images.

    Args:
        images: List of image paths or directory.
        out_gif: Output GIF path.
        ext: Image extension.
        fps: Frames per second.
        loop: Number of loops (0 = infinite).
        clean_up: Whether to delete source images.
    """
    # Check if PIL is available
    if Image is None:
        raise RuntimeError(
            "PIL (Pillow) is not available. Cannot create GIF from images."
        )

    if isinstance(images, str) and os.path.isdir(images):
        images = list(glob.glob(os.path.join(images, f"*.{ext}")))

    if not images:
        raise ValueError("No images found.")

    images.sort()

    frames = [Image.open(img) for img in images]
    frame_one = frames[0]
    frame_one.save(
        out_gif,
        format="GIF",
        append_images=frames[1:],
        save_all=True,
        duration=int(1000 / fps),
        loop=loop,
    )

    if clean_up:
        for image in images:
            os.remove(image)


def add_text_to_gif(
    in_gif: str,
    out_gif: str,
    text_sequence: Union[str, List[str]],
    xy: tuple = ("2%", "2%"),
    font_size: int = 20,
    font_color: str = "white",
    add_progress_bar: bool = True,
    progress_bar_color: str = "white",
    progress_bar_height: int = 5,
    loop: int = 0,
) -> None:
    """Add text overlay to each frame of a GIF.

    Args:
        in_gif: Input GIF path.
        out_gif: Output GIF path.
        text_sequence: Text for each frame.
        xy: Position of text.
        font_size: Font size.
        font_color: Font color.
        add_progress_bar: Whether to add progress bar.
        progress_bar_color: Progress bar color.
        progress_bar_height: Progress bar height.
        loop: Loop count.
    """
    # Check if PIL is available
    if Image is None:
        print("Warning: PIL (Pillow) is not available. Skipping text overlay.")
        return

    gif = Image.open(in_gif)

    frames = []
    n_frames = gif.n_frames

    if isinstance(text_sequence, str):
        text_sequence = [text_sequence] * n_frames
    elif len(text_sequence) < n_frames:
        text_sequence = text_sequence + [text_sequence[-1]] * (
            n_frames - len(text_sequence)
        )

    # Try to load a font
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size
            )
        except:
            font = ImageFont.load_default()

    for i in range(n_frames):
        gif.seek(i)
        frame = gif.copy().convert("RGBA")
        draw = ImageDraw.Draw(frame)

        # Calculate position
        width, height = frame.size
        if isinstance(xy[0], str) and "%" in xy[0]:
            x = int(width * float(xy[0].strip("%")) / 100)
        else:
            x = int(xy[0])

        if isinstance(xy[1], str) and "%" in xy[1]:
            y = int(height * float(xy[1].strip("%")) / 100)
        else:
            y = int(xy[1])

        # Draw text
        text = text_sequence[i] if i < len(text_sequence) else ""
        draw.text((x, y), text, font=font, fill=font_color)

        # Add progress bar
        if add_progress_bar:
            progress = (i + 1) / n_frames
            bar_width = int(width * progress)
            bar_y = height - progress_bar_height
            draw.rectangle([(0, bar_y), (bar_width, height)], fill=progress_bar_color)

        frames.append(frame.convert("P", palette=Image.ADAPTIVE))

    # Get original duration
    duration = gif.info.get("duration", 100)

    # Save new GIF
    frames[0].save(
        out_gif,
        format="GIF",
        append_images=frames[1:],
        save_all=True,
        duration=duration,
        loop=loop,
    )


def gif_to_mp4(in_gif: str, out_mp4: str) -> bool:
    """Convert GIF to MP4 using ffmpeg.

    Args:
        in_gif: Input GIF path.
        out_mp4: Output MP4 path.

    Returns:
        True if successful, False otherwise.
    """
    import subprocess
    import shutil

    # Check if PIL is available
    if Image is None:
        print(
            "Warning: PIL (Pillow) is not available. Cannot determine GIF dimensions for MP4 conversion."
        )
        return False

    if not shutil.which("ffmpeg"):
        return False

    if not os.path.exists(in_gif):
        return False

    out_mp4 = os.path.abspath(out_mp4)
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)

    # Get dimensions
    img = Image.open(in_gif)
    width, height = img.size
    img.close()

    # Ensure even dimensions for h264
    width = width + (width % 2)
    height = height + (height % 2)

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        in_gif,
        "-vf",
        f"scale={width}:{height}",
        "-vcodec",
        "libx264",
        "-crf",
        "25",
        "-pix_fmt",
        "yuv420p",
        out_mp4,
    ]

    try:
        subprocess.run(cmd, check=True)
        return os.path.exists(out_mp4)
    except subprocess.CalledProcessError:
        return False


def create_naip_timelapse(
    roi: "ee.Geometry",
    start_year: int = 2003,
    end_year: int = None,
    out_gif: str = None,
    bands: List[str] = None,
    vis_params: dict = None,
    dimensions: int = 768,
    frames_per_second: int = 3,
    crs: str = "EPSG:3857",
    title: str = None,
    add_text: bool = True,
    font_size: int = 20,
    font_color: str = "white",
    add_progress_bar: bool = True,
    progress_bar_color: str = "white",
    progress_bar_height: int = 5,
    loop: int = 0,
    mp4: bool = False,
    step: int = 1,
    overlay_data: "ee.FeatureCollection" = None,
    overlay_color: str = "black",
    overlay_width: int = 1,
) -> str:
    """Create a timelapse from NAIP imagery.

    Args:
        roi: Region of interest geometry.
        start_year: Starting year.
        end_year: Ending year.
        out_gif: Output GIF path.
        bands: Bands to visualize ('R', 'G', 'B', 'N').
        vis_params: Visualization parameters.
        dimensions: Output dimensions.
        frames_per_second: Animation speed.
        crs: Coordinate reference system.
        title: Title text.
        add_text: Whether to add date text.
        font_size: Font size.
        font_color: Font color.
        add_progress_bar: Whether to add progress bar.
        progress_bar_color: Progress bar color.
        progress_bar_height: Progress bar height.
        loop: Loop count.
        mp4: Whether to also create MP4.
        step: Year step.

    Returns:
        Path to output GIF.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    if out_gif is None:
        out_gif = os.path.join(tempfile.gettempdir(), "naip_timelapse.gif")

    out_gif = os.path.abspath(out_gif)
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)

    if bands is None:
        bands = ["R", "G", "B"]

    if vis_params is None:
        vis_params = {"min": 0, "max": 255, "bands": bands}

    # Create time series
    collection = naip_timeseries(roi, start_year, end_year, bands=bands, step=step)

    # Visualize collection
    vis_collection = collection.map(
        lambda img: img.visualize(**vis_params).set(
            {
                "system:time_start": img.get("system:time_start"),
                "system:date": img.get("system:date"),
            }
        )
    )

    # Add overlay if provided
    if overlay_data is not None:
        vis_collection = add_overlay(
            vis_collection, overlay_data, overlay_color, overlay_width, region=roi
        )

    # Video arguments
    video_args = {
        "dimensions": dimensions,
        "region": roi,
        "framesPerSecond": frames_per_second,
        "crs": crs,
        "min": 0,
        "max": 255,
        "bands": ["vis-red", "vis-green", "vis-blue"],
    }

    # Download video
    download_ee_video(vis_collection, video_args, out_gif)

    # Add text overlay
    if add_text:
        dates = vis_collection.aggregate_array("system:date").getInfo()
        add_text_to_gif(
            out_gif,
            out_gif,
            dates,
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=add_progress_bar,
            progress_bar_color=progress_bar_color,
            progress_bar_height=progress_bar_height,
            loop=loop,
        )

    # Add title overlay if specified
    if title is not None and isinstance(title, str) and title.strip():
        add_text_to_gif(
            out_gif,
            out_gif,
            title,
            xy=("2%", "93%"),
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=False,
            loop=loop,
        )

    # Convert to MP4 if requested
    if mp4:
        out_mp4 = out_gif.replace(".gif", ".mp4")
        gif_to_mp4(out_gif, out_mp4)

    return out_gif


def create_sentinel2_timelapse(
    roi: "ee.Geometry",
    start_year: int = 2015,
    end_year: int = None,
    start_date: str = "06-10",
    end_date: str = "09-20",
    out_gif: str = None,
    bands: List[str] = None,
    vis_params: dict = None,
    dimensions: int = 768,
    frames_per_second: int = 5,
    crs: str = "EPSG:3857",
    apply_fmask: bool = True,
    cloud_pct: int = 30,
    title: str = None,
    add_text: bool = True,
    font_size: int = 20,
    font_color: str = "white",
    add_progress_bar: bool = True,
    progress_bar_color: str = "white",
    progress_bar_height: int = 5,
    loop: int = 0,
    mp4: bool = False,
    frequency: str = "year",
    step: int = 1,
    overlay_data: "ee.FeatureCollection" = None,
    overlay_color: str = "black",
    overlay_width: int = 1,
) -> str:
    """Create a timelapse from Sentinel-2 imagery.

    Args:
        roi: Region of interest geometry.
        start_year: Starting year.
        end_year: Ending year.
        start_date: Start date within each year (MM-dd).
        end_date: End date within each year (MM-dd).
        out_gif: Output GIF path.
        bands: Bands to visualize.
        vis_params: Visualization parameters.
        dimensions: Output dimensions.
        frames_per_second: Animation speed.
        crs: Coordinate reference system.
        apply_fmask: Whether to apply cloud masking.
        cloud_pct: Maximum cloud percentage.
        title: Title text.
        add_text: Whether to add date text.
        font_size: Font size.
        font_color: Font color.
        add_progress_bar: Whether to add progress bar.
        progress_bar_color: Progress bar color.
        progress_bar_height: Progress bar height.
        loop: Loop count.
        mp4: Whether to also create MP4.
        frequency: Temporal frequency ('year', 'quarter', 'month', 'day').
        step: Step size.

    Returns:
        Path to output GIF.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    if out_gif is None:
        out_gif = os.path.join(tempfile.gettempdir(), "sentinel2_timelapse.gif")

    out_gif = os.path.abspath(out_gif)
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)

    if bands is None:
        bands = ["NIR", "Red", "Green"]

    # Band mapping for visualization
    band_mapping = {
        "Blue": "B2",
        "Green": "B3",
        "Red": "B4",
        "NIR": "B8",
        "SWIR1": "B11",
        "SWIR2": "B12",
    }
    ee_bands = [band_mapping.get(b, b) for b in bands]

    if vis_params is None:
        vis_params = {"min": 0, "max": 0.4, "bands": ee_bands}

    # Create time series
    collection = sentinel2_timeseries(
        roi,
        start_year,
        end_year,
        start_date,
        end_date,
        bands=bands,
        apply_fmask=apply_fmask,
        cloud_pct=cloud_pct,
        frequency=frequency,
        step=step,
    )

    # Visualize collection
    vis_collection = collection.map(
        lambda img: img.visualize(**vis_params).set(
            {
                "system:time_start": img.get("system:time_start"),
                "system:date": img.get("system:date"),
            }
        )
    )

    # Add overlay if provided
    if overlay_data is not None:
        vis_collection = add_overlay(
            vis_collection, overlay_data, overlay_color, overlay_width, region=roi
        )

    # Video arguments
    video_args = {
        "dimensions": dimensions,
        "region": roi,
        "framesPerSecond": frames_per_second,
        "crs": crs,
        "min": 0,
        "max": 255,
        "bands": ["vis-red", "vis-green", "vis-blue"],
    }

    # Download video
    download_ee_video(vis_collection, video_args, out_gif)

    # Add text overlay
    if add_text:
        dates = vis_collection.aggregate_array("system:date").getInfo()
        add_text_to_gif(
            out_gif,
            out_gif,
            dates,
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=add_progress_bar,
            progress_bar_color=progress_bar_color,
            progress_bar_height=progress_bar_height,
            loop=loop,
        )

    # Add title overlay if specified
    if title is not None and isinstance(title, str) and title.strip():
        add_text_to_gif(
            out_gif,
            out_gif,
            title,
            xy=("2%", "93%"),
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=False,
            loop=loop,
        )

    # Convert to MP4 if requested
    if mp4:
        out_mp4 = out_gif.replace(".gif", ".mp4")
        gif_to_mp4(out_gif, out_mp4)

    return out_gif


def create_sentinel1_timelapse(
    roi: "ee.Geometry",
    start_year: int = 2015,
    end_year: int = None,
    start_date: str = "01-01",
    end_date: str = "12-31",
    out_gif: str = None,
    bands: List[str] = None,
    vis_params: dict = None,
    palette: str = "Greys",
    dimensions: int = 768,
    frames_per_second: int = 5,
    crs: str = "EPSG:3857",
    orbit: List[str] = None,
    title: str = None,
    add_text: bool = True,
    font_size: int = 20,
    font_color: str = "white",
    add_progress_bar: bool = True,
    progress_bar_color: str = "white",
    progress_bar_height: int = 5,
    loop: int = 0,
    mp4: bool = False,
    frequency: str = "year",
    step: int = 1,
    overlay_data: "ee.FeatureCollection" = None,
    overlay_color: str = "black",
    overlay_width: int = 1,
) -> str:
    """Create a timelapse from Sentinel-1 imagery.

    Args:
        roi: Region of interest geometry.
        start_year: Starting year.
        end_year: Ending year.
        start_date: Start date within each year (MM-dd).
        end_date: End date within each year (MM-dd).
        out_gif: Output GIF path.
        bands: Bands to visualize (VV, VH, HH, HV).
        vis_params: Visualization parameters.
        palette: Color palette for visualization.
        dimensions: Output dimensions.
        frames_per_second: Animation speed.
        crs: Coordinate reference system.
        orbit: Orbit directions to include.
        title: Title text.
        add_text: Whether to add date text.
        font_size: Font size.
        font_color: Font color.
        add_progress_bar: Whether to add progress bar.
        progress_bar_color: Progress bar color.
        progress_bar_height: Progress bar height.
        loop: Loop count.
        mp4: Whether to also create MP4.
        frequency: Temporal frequency ('year', 'quarter', 'month', 'day').
        step: Step size.

    Returns:
        Path to output GIF.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    if out_gif is None:
        out_gif = os.path.join(tempfile.gettempdir(), "sentinel1_timelapse.gif")

    out_gif = os.path.abspath(out_gif)
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)

    if bands is None:
        bands = ["VV"]

    if orbit is None:
        orbit = ["ascending", "descending"]

    # For single band, use a grayscale palette
    if vis_params is None:
        vis_params = {"min": -30, "max": 0}
        if len(bands) == 1:
            vis_params["bands"] = bands
            vis_params["palette"] = ["000000", "ffffff"]
        else:
            vis_params["bands"] = bands

    # Create time series
    collection = sentinel1_timeseries(
        roi,
        start_year,
        end_year,
        start_date,
        end_date,
        bands=bands,
        orbit=orbit,
        frequency=frequency,
        step=step,
    )

    # Visualize collection - always outputs vis-red, vis-green, vis-blue
    vis_collection = collection.map(
        lambda img: img.visualize(**vis_params).set(
            {
                "system:time_start": img.get("system:time_start"),
                "system:date": img.get("system:date"),
            }
        )
    )

    # Add overlay if provided
    if overlay_data is not None:
        vis_collection = add_overlay(
            vis_collection, overlay_data, overlay_color, overlay_width, region=roi
        )

    # Video arguments - visualize() always creates RGB output
    video_args = {
        "dimensions": dimensions,
        "region": roi,
        "framesPerSecond": frames_per_second,
        "crs": crs,
        "min": 0,
        "max": 255,
        "bands": ["vis-red", "vis-green", "vis-blue"],
    }

    # Download video
    download_ee_video(vis_collection, video_args, out_gif)

    # Add text overlay
    if add_text:
        dates = vis_collection.aggregate_array("system:date").getInfo()
        add_text_to_gif(
            out_gif,
            out_gif,
            dates,
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=add_progress_bar,
            progress_bar_color=progress_bar_color,
            progress_bar_height=progress_bar_height,
            loop=loop,
        )

    # Add title overlay if specified
    if title is not None and isinstance(title, str) and title.strip():
        add_text_to_gif(
            out_gif,
            out_gif,
            title,
            xy=("2%", "93%"),
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=False,
            loop=loop,
        )

    # Convert to MP4 if requested
    if mp4:
        out_mp4 = out_gif.replace(".gif", ".mp4")
        gif_to_mp4(out_gif, out_mp4)

    return out_gif


def create_landsat_timelapse(
    roi: "ee.Geometry",
    start_year: int = 1984,
    end_year: int = None,
    start_date: str = "06-10",
    end_date: str = "09-20",
    out_gif: str = None,
    bands: List[str] = None,
    vis_params: dict = None,
    dimensions: int = 768,
    frames_per_second: int = 5,
    crs: str = "EPSG:3857",
    apply_fmask: bool = True,
    title: str = None,
    add_text: bool = True,
    font_size: int = 20,
    font_color: str = "white",
    add_progress_bar: bool = True,
    progress_bar_color: str = "white",
    progress_bar_height: int = 5,
    loop: int = 0,
    mp4: bool = False,
    frequency: str = "year",
    step: int = 1,
    overlay_data: "ee.FeatureCollection" = None,
    overlay_color: str = "black",
    overlay_width: int = 1,
) -> str:
    """Create a timelapse from Landsat imagery.

    Combines Landsat 4, 5, 7, 8, and 9 for long-term time series (1984-present).

    Args:
        roi: Region of interest geometry.
        start_year: Starting year (1984 or later).
        end_year: Ending year.
        start_date: Start date within each year (MM-dd).
        end_date: End date within each year (MM-dd).
        out_gif: Output GIF path.
        bands: Bands to visualize (Blue, Green, Red, NIR, SWIR1, SWIR2).
        vis_params: Visualization parameters.
        dimensions: Output dimensions.
        frames_per_second: Animation speed.
        crs: Coordinate reference system.
        apply_fmask: Whether to apply cloud masking.
        title: Title text.
        add_text: Whether to add date text.
        font_size: Font size.
        font_color: Font color.
        add_progress_bar: Whether to add progress bar.
        progress_bar_color: Progress bar color.
        progress_bar_height: Progress bar height.
        loop: Loop count.
        mp4: Whether to also create MP4.
        frequency: Temporal frequency ('year', 'quarter', 'month', 'day').
        step: Step size.

    Returns:
        Path to output GIF.
    """
    if end_year is None:
        end_year = datetime.datetime.now().year

    if out_gif is None:
        out_gif = os.path.join(tempfile.gettempdir(), "landsat_timelapse.gif")

    out_gif = os.path.abspath(out_gif)
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)

    if bands is None:
        bands = ["NIR", "Red", "Green"]

    if vis_params is None:
        vis_params = {"min": 0, "max": 0.4, "bands": bands, "gamma": [1, 1, 1]}

    # Create time series
    collection = landsat_timeseries(
        roi,
        start_year,
        end_year,
        start_date,
        end_date,
        apply_fmask=apply_fmask,
        frequency=frequency,
        step=step,
    )

    # Select bands and visualize
    vis_collection = collection.select(bands).map(
        lambda img: img.visualize(**vis_params).set(
            {
                "system:time_start": img.get("system:time_start"),
                "system:date": img.get("system:date"),
            }
        )
    )

    # Add overlay if provided
    if overlay_data is not None:
        vis_collection = add_overlay(
            vis_collection, overlay_data, overlay_color, overlay_width, region=roi
        )

    # Video arguments
    video_args = {
        "dimensions": dimensions,
        "region": roi,
        "framesPerSecond": frames_per_second,
        "crs": crs,
        "min": 0,
        "max": 255,
        "bands": ["vis-red", "vis-green", "vis-blue"],
    }

    # Download video
    download_ee_video(vis_collection, video_args, out_gif)

    # Add text overlay
    if add_text:
        dates = vis_collection.aggregate_array("system:date").getInfo()
        add_text_to_gif(
            out_gif,
            out_gif,
            dates,
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=add_progress_bar,
            progress_bar_color=progress_bar_color,
            progress_bar_height=progress_bar_height,
            loop=loop,
        )

    # Add title overlay if specified
    if title is not None and isinstance(title, str) and title.strip():
        add_text_to_gif(
            out_gif,
            out_gif,
            title,
            xy=("2%", "93%"),
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=False,
            loop=loop,
        )

    # Convert to MP4 if requested
    if mp4:
        out_mp4 = out_gif.replace(".gif", ".mp4")
        gif_to_mp4(out_gif, out_mp4)

    return out_gif


def modis_ndvi_timeseries(
    roi: "ee.Geometry",
    data: str = "Terra",
    band: str = "NDVI",
    start_date: str = None,
    end_date: str = None,
) -> "ee.ImageCollection":
    """Create MODIS NDVI time series by day of year."""
    if data == "Terra":
        col = ee.ImageCollection("MODIS/061/MOD13A2").select(band)
    else:
        col = ee.ImageCollection("MODIS/061/MYD13A2").select(band)

    if start_date and end_date:
        col = col.filterDate(start_date, end_date)

    if roi is not None:
        col = col.filterBounds(roi)

    def set_doy(img):
        doy = ee.Date(img.get("system:time_start")).getRelative("day", "year")
        return img.set("doy", doy)

    col = col.map(set_doy)
    distinct_doy = col.filterDate("2013-01-01", "2014-01-01")
    filter_eq = ee.Filter.equals(leftField="doy", rightField="doy")
    join = ee.Join.saveAll("doy_matches")
    join_col = ee.ImageCollection(join.apply(distinct_doy, col, filter_eq))

    def match_doy(img):
        doy_col = ee.ImageCollection.fromImages(img.get("doy_matches"))
        return doy_col.reduce(ee.Reducer.median()).set(
            {
                "system:index": img.get("system:index"),
                "system:time_start": img.get("system:time_start"),
            }
        )

    comp = join_col.map(match_doy)
    if roi is not None:
        comp = comp.map(lambda img: img.clip(roi))
    return comp


def create_modis_ndvi_timelapse(
    roi: "ee.Geometry",
    out_gif: str = None,
    data: str = "Terra",
    band: str = "NDVI",
    start_date: str = None,
    end_date: str = None,
    dimensions: int = 768,
    frames_per_second: int = 10,
    crs: str = "EPSG:3857",
    title: str = None,
    add_text: bool = True,
    font_size: int = 20,
    font_color: str = "white",
    add_progress_bar: bool = True,
    progress_bar_color: str = "white",
    progress_bar_height: int = 5,
    loop: int = 0,
    mp4: bool = False,
    overlay_data: "ee.FeatureCollection" = None,
    overlay_color: str = "black",
    overlay_width: int = 1,
) -> str:
    """Create MODIS NDVI/EVI timelapse showing vegetation phenology."""
    if out_gif is None:
        out_gif = os.path.join(tempfile.gettempdir(), "modis_ndvi_timelapse.gif")

    out_gif = os.path.abspath(out_gif)
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)

    collection = modis_ndvi_timeseries(roi, data, band, start_date, end_date)

    vis_params = {
        "min": 0.0,
        "max": 9000.0,
        "palette": [
            "FFFFFF",
            "CE7E45",
            "DF923D",
            "F1B555",
            "FCD163",
            "99B718",
            "74A901",
            "66A000",
            "529400",
            "3E8601",
            "207401",
            "056201",
            "004C00",
            "023B01",
            "012E01",
            "011D01",
            "011301",
        ],
    }

    vis_collection = collection.map(
        lambda img: img.visualize(**vis_params).set(
            {
                "system:index": img.get("system:index"),
                "system:time_start": img.get("system:time_start"),
            }
        )
    )

    # Add overlay if provided
    if overlay_data is not None:
        vis_collection = add_overlay(
            vis_collection, overlay_data, overlay_color, overlay_width, region=roi
        )

    video_args = {
        "dimensions": dimensions,
        "region": roi,
        "framesPerSecond": frames_per_second,
        "crs": crs,
    }

    download_ee_video(vis_collection, video_args, out_gif)

    if add_text:
        text = vis_collection.aggregate_array("system:index").getInfo()
        text_sequence = []
        for t in text:
            try:
                parts = t.replace("_", "-")[5:]
                month = int(parts[:2])
                day = int(parts[3:5])
                months = [
                    "Jan",
                    "Feb",
                    "Mar",
                    "Apr",
                    "May",
                    "Jun",
                    "Jul",
                    "Aug",
                    "Sep",
                    "Oct",
                    "Nov",
                    "Dec",
                ]
                text_sequence.append(f"{months[month-1]} {day:02d}")
            except:
                text_sequence.append(t)

        add_text_to_gif(
            out_gif,
            out_gif,
            text_sequence,
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=add_progress_bar,
            progress_bar_color=progress_bar_color,
            progress_bar_height=progress_bar_height,
            loop=loop,
        )

    # Add title overlay if specified
    if title is not None and isinstance(title, str) and title.strip():
        add_text_to_gif(
            out_gif,
            out_gif,
            title,
            xy=("2%", "93%"),
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=False,
            loop=loop,
        )

    if mp4:
        gif_to_mp4(out_gif, out_gif.replace(".gif", ".mp4"))

    return out_gif


def goes_timeseries(
    start_date: str,
    end_date: str,
    data: str = "GOES-19",
    scan: str = "full_disk",
    region: "ee.Geometry" = None,
    band_combination: str = "true_color",
    custom_bands: List[str] = None,
) -> "ee.ImageCollection":
    """Create GOES satellite time series.

    Args:
        start_date: Start datetime (e.g., "2021-10-24T14:00:00").
        end_date: End datetime.
        data: GOES satellite ("GOES-16", "GOES-17", "GOES-18", "GOES-19").
        scan: Scan type ("full_disk", "conus", or "mesoscale").
        region: Region of interest.
        band_combination: GOES RGB composite ("true_color", "volcanic_ash", "volcanic_gases", "custom_rgb").
        custom_bands: Custom GOES RGB bands [R, G, B] when band_combination is "custom_rgb".

    Returns:
        ee.ImageCollection of processed GOES images.
    """
    scan_types = {
        "full_disk": "MCMIPF",
        "conus": "MCMIPC",
        "mesoscale": "MCMIPM",
    }

    satellite_num = data[-2:]  # "16", "17", "18", "19"
    col = ee.ImageCollection(f"NOAA/GOES/{satellite_num}/{scan_types[scan.lower()]}")

    def apply_scale_and_offset(img):
        def get_factor_img(factor_names):
            factor_list = img.toDictionary().select(factor_names).values()
            return ee.Image.constant(factor_list)

        scale_img = get_factor_img(["CMI_C.._scale"])
        offset_img = get_factor_img(["CMI_C.._offset"])
        scaled = img.select("CMI_C..").multiply(scale_img).add(offset_img)
        return img.addBands(srcImg=scaled, overwrite=True)

    def add_green_band(img):
        green = img.expression(
            "CMI_GREEN = 0.45 * red + 0.10 * nir + 0.45 * blue",
            {
                "blue": img.select("CMI_C01"),
                "red": img.select("CMI_C02"),
                "nir": img.select("CMI_C03"),
            },
        )
        return img.addBands(green)

    def scale_for_vis(img):
        return (
            img.select(["CMI_C01", "CMI_GREEN", "CMI_C02", "CMI_C03", "CMI_C05"])
            .resample("bicubic")
            .log10()
            .interpolate([-1.6, 0.176], [0, 1], "clamp")
            .unmask(0)
            .set("system:time_start", img.get("system:time_start"))
        )

    def create_thermal_composite(img, mode: str):
        red = img.select("CMI_C15").subtract(img.select("CMI_C13")).rename("GOES_RED")

        if mode == "volcanic_gases":
            green = (
                img.select("CMI_C13")
                .subtract(img.select("CMI_C07"))
                .rename("GOES_GREEN")
            )
        else:  # volcanic_ash
            green = (
                img.select("CMI_C13")
                .subtract(img.select("CMI_C11"))
                .rename("GOES_GREEN")
            )

        blue = img.select("CMI_C13").rename("GOES_BLUE")
        return ee.Image.cat([red, green, blue]).set(
            "system:time_start", img.get("system:time_start")
        )

    mode = band_combination.lower().strip()

    def process_for_vis(img):
        scaled = apply_scale_and_offset(img)
        if mode == "true_color":
            return scale_for_vis(add_green_band(scaled))
        if mode in ["volcanic_ash", "volcanic_gases"]:
            return create_thermal_composite(scaled, mode)
        if mode == "custom_rgb":
            selected = custom_bands or ["CMI_C02", "CMI_C03", "CMI_C01"]
            if len(selected) != 3:
                raise ValueError("custom_bands must contain exactly three GOES bands [R, G, B].")
            return scaled.select(selected).rename(["GOES_RED", "GOES_GREEN", "GOES_BLUE"]).set("system:time_start", img.get("system:time_start"))
        raise ValueError(
            f"Unsupported GOES band_combination: {band_combination}. "
            "Use true_color, volcanic_ash, volcanic_gases, or custom_rgb."
        )

    result = col.filterDate(start_date, end_date)
    if region is not None:
        result = result.filterBounds(region)

    return result.map(process_for_vis)


def create_goes_timelapse(
    roi: "ee.Geometry",
    out_gif: str = None,
    start_date: str = "2021-10-24T14:00:00",
    end_date: str = "2021-10-25T01:00:00",
    data: str = "GOES-19",
    scan: str = "full_disk",
    band_combination: str = "true_color",
    custom_bands: List[str] = None,
    dimensions: int = 768,
    frames_per_second: int = 10,
    crs: str = None,
    title: str = None,
    add_text: bool = True,
    font_size: int = 20,
    font_color: str = "white",
    add_progress_bar: bool = True,
    progress_bar_color: str = "white",
    progress_bar_height: int = 5,
    loop: int = 0,
    mp4: bool = False,
    overlay_data: "ee.FeatureCollection" = None,
    overlay_color: str = "black",
    overlay_width: int = 1,
) -> str:
    """Create GOES satellite timelapse.

    Great for weather/storm visualization.

    Args:
        roi: Region of interest geometry.
        out_gif: Output GIF path.
        start_date: Start datetime (e.g., "2021-10-24T14:00:00").
        end_date: End datetime.
        data: GOES satellite ("GOES-16", "GOES-17", "GOES-18", "GOES-19").
        scan: Scan type ("full_disk", "conus", or "mesoscale").
        band_combination: GOES RGB composite ("true_color", "volcanic_ash", "volcanic_gases", "custom_rgb").
        custom_bands: Custom GOES RGB bands [R, G, B] when band_combination is "custom_rgb".
        dimensions: Output dimensions.
        frames_per_second: Animation speed.
        crs: Coordinate reference system.
        add_text: Whether to add datetime text.
        font_size: Font size.
        font_color: Font color.
        add_progress_bar: Whether to add progress bar.
        progress_bar_color: Progress bar color.
        progress_bar_height: Progress bar height.
        loop: Loop count.
        mp4: Whether to also create MP4.

    Returns:
        Path to output GIF.
    """
    if out_gif is None:
        out_gif = os.path.join(tempfile.gettempdir(), "goes_timelapse.gif")

    out_gif = os.path.abspath(out_gif)
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)

    # Create time series
    collection = goes_timeseries(
        start_date, end_date, data, scan, roi, band_combination, custom_bands
    )

    # Visualization params
    mode = band_combination.lower().strip()
    if mode == "true_color":
        bands = ["CMI_C02", "CMI_GREEN", "CMI_C01"]
        vis_params = {"bands": bands, "min": 0, "max": 0.8}
    elif mode == "volcanic_ash":
        bands = ["GOES_RED", "GOES_GREEN", "GOES_BLUE"]
        vis_params = {
            "bands": bands,
            "min": [-6.7, -6.0, 243.6],
            "max": [2.6, 6.3, 302.4],
        }
    elif mode == "volcanic_gases":
        bands = ["GOES_RED", "GOES_GREEN", "GOES_BLUE"]
        vis_params = {
            "bands": bands,
            "min": [-4.0, -4.0, 243.6],
            "max": [2.0, 5.0, 302.4],
        }
    elif mode == "custom_rgb":
        bands = ["GOES_RED", "GOES_GREEN", "GOES_BLUE"]
        selected = custom_bands or ["CMI_C02", "CMI_C03", "CMI_C01"]

        def _band_range(name: str):
            if name.startswith("CMI_C"):
                try:
                    idx = int(name.split("CMI_C", 1)[1])
                except Exception:
                    idx = 2
                if idx <= 6:
                    return 0.0, 1.0
                return 180.0, 330.0
            return 0.0, 1.0

        mins, maxs = zip(*[_band_range(b) for b in selected])
        vis_params = {"bands": bands, "min": list(mins), "max": list(maxs)}
    else:
        raise ValueError(
            f"Unsupported GOES band_combination: {band_combination}. "
            "Use true_color, volcanic_ash, volcanic_gases, or custom_rgb."
        )

    # Visualize collection and preserve original projection
    vis_collection = collection.select(bands).map(
        lambda img: img.visualize(**vis_params)
        .setDefaultProjection(img.projection())
        .set(
            {
                "system:time_start": img.get("system:time_start"),
            }
        )
    )

    # Add overlay if provided
    if overlay_data is not None:
        vis_collection = add_overlay(
            vis_collection, overlay_data, overlay_color, overlay_width, region=roi
        )
        # Force EPSG:3857 when overlay is used to avoid projection issues
        # GOES uses geostationary projection which can't transform overlay coordinates
        if crs is None:
            crs = "EPSG:3857"

    # Use native CRS if not specified
    if crs is None:
        crs = collection.first().projection()

    # Video arguments
    video_args = {
        "dimensions": dimensions,
        "region": roi,
        "framesPerSecond": frames_per_second,
        "crs": crs,
        "bands": ["vis-red", "vis-green", "vis-blue"],
        "min": 0,
        "max": 255,
    }

    # Download video
    download_ee_video(vis_collection, video_args, out_gif)

    # Add text overlay with datetime
    if add_text:
        # Get timestamps and format them
        def format_date(img):
            return ee.Date(img.get("system:time_start")).format("YYYY-MM-dd HH:mm")

        dates = (
            vis_collection.map(lambda img: ee.Feature(None, {"date": format_date(img)}))
            .aggregate_array("date")
            .getInfo()
        )

        dates = [f"{date} UTC" for date in dates]

        add_text_to_gif(
            out_gif,
            out_gif,
            dates,
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=add_progress_bar,
            progress_bar_color=progress_bar_color,
            progress_bar_height=progress_bar_height,
            loop=loop,
        )

    # Add title overlay if specified
    if title is not None and isinstance(title, str) and title.strip():
        add_text_to_gif(
            out_gif,
            out_gif,
            title,
            xy=("2%", "93%"),
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=False,
            loop=loop,
        )

    if mp4:
        gif_to_mp4(out_gif, out_gif.replace(".gif", ".mp4"))

    return out_gif
