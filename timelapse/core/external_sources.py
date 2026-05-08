"""External imagery source support for non-Earth-Engine timelapses."""

from __future__ import annotations

import datetime
import os
import re
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET  # nosec B405 (parsing trusted ESRI Wayback WMTS XML over https; no DTDs/entities used)
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from . import timelapse_core

ESRI_WAYBACK_CAPABILITIES_URL = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
    "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
)


def _require_https(url: str) -> None:
    """Reject any non-https URL before opening it.

    Args:
        url: The URL to validate.

    Raises:
        ValueError: If the URL does not use the https scheme.
    """
    if not url.startswith("https://"):
        raise ValueError(f"Refusing to open non-https URL: {url}")


@dataclass(frozen=True)
class EsriWaybackLayer:
    """Metadata for one ESRI Wayback WMTS layer."""

    identifier: str
    title: str
    date: datetime.date
    tile_matrix_set: str
    tile_template: str
    image_format: str = "image/jpeg"


@dataclass(frozen=True)
class ExternalFrame:
    """One externally rendered timelapse frame."""

    label: str
    url_template: str
    layer_name: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_child_text(element: ET.Element, local_name: str) -> str:
    for child in element:
        if _local_name(child.tag) == local_name:
            return (child.text or "").strip()
    return ""


def _find_descendant_text(element: ET.Element, local_name: str) -> str:
    for child in element.iter():
        if _local_name(child.tag) == local_name:
            return (child.text or "").strip()
    return ""


def parse_esri_wayback_capabilities(xml_text: str) -> List[EsriWaybackLayer]:
    """Parse ESRI Wayback WMTS capabilities XML.

    The endpoint currently uses HTTPS namespace URIs, while many WMTS
    examples use HTTP URIs. This parser matches elements by local name so
    both forms work.
    """
    root = ET.fromstring(
        xml_text
    )  # nosec B314 (input is fetched from a trusted https endpoint; parser does not resolve external entities)
    layers: List[EsriWaybackLayer] = []

    for element in root.iter():
        if _local_name(element.tag) != "Layer":
            continue

        identifier = _find_descendant_text(element, "Identifier")
        if not identifier.startswith("WB_"):
            continue

        title = _find_descendant_text(element, "Title")
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", title)
        if date_match is None:
            continue

        resource_url = ""
        image_format = _find_child_text(element, "Format") or "image/jpeg"
        for child in element:
            if _local_name(child.tag) == "ResourceURL":
                if child.get("resourceType") in (None, "tile"):
                    resource_url = child.get("template", "")
                    image_format = child.get("format", image_format)
                    break

        if not resource_url:
            continue

        matrix_sets = [
            (child.text or "").strip()
            for child in element.iter()
            if _local_name(child.tag) == "TileMatrixSet" and (child.text or "").strip()
        ]
        tile_matrix_set = (
            "GoogleMapsCompatible"
            if "GoogleMapsCompatible" in matrix_sets
            else (matrix_sets[0] if matrix_sets else "GoogleMapsCompatible")
        )

        layers.append(
            EsriWaybackLayer(
                identifier=identifier,
                title=title,
                date=datetime.date.fromisoformat(date_match.group(1)),
                tile_matrix_set=tile_matrix_set,
                tile_template=resource_url,
                image_format=image_format,
            )
        )

    return sorted(layers, key=lambda layer: layer.date)


def fetch_esri_wayback_layers(
    capabilities_url: str = ESRI_WAYBACK_CAPABILITIES_URL,
    timeout: int = 30,
) -> List[EsriWaybackLayer]:
    """Download and parse the current ESRI Wayback layer list."""
    _require_https(capabilities_url)
    with urllib.request.urlopen(  # nosec B310 (https enforced by _require_https)
        capabilities_url, timeout=timeout
    ) as response:
        xml_text = response.read().decode("utf-8")
    return parse_esri_wayback_capabilities(xml_text)


def filter_esri_wayback_layers(
    layers: Iterable[EsriWaybackLayer],
    start_year: int,
    end_year: int,
    step: int = 1,
    max_frames: Optional[int] = None,
) -> List[EsriWaybackLayer]:
    """Filter ESRI layers by year and downsample irregular releases."""
    if step < 1:
        raise ValueError("step must be 1 or greater")

    selected = [layer for layer in layers if start_year <= layer.date.year <= end_year][
        ::step
    ]

    if max_frames is not None and max_frames > 0:
        selected = selected[:max_frames]

    return selected


def build_esri_wayback_xyz_url(layer: EsriWaybackLayer) -> str:
    """Convert an ESRI WMTS ResourceURL template to a QGIS XYZ template."""
    return (
        layer.tile_template.replace("{TileMatrixSet}", layer.tile_matrix_set)
        .replace("{TileMatrix}", "{z}")
        .replace("{TileRow}", "{y}")
        .replace("{TileCol}", "{x}")
    )


def expand_custom_template(template: str, date_value: datetime.date) -> str:
    """Expand supported custom date tokens while leaving tile tokens intact."""
    replacements = {
        "{date}": date_value.isoformat(),
        "{yyyy}": f"{date_value.year:04d}",
        "{yy}": f"{date_value.year % 100:02d}",
        "{MM}": f"{date_value.month:02d}",
        "{M}": str(date_value.month),
        "{dd}": f"{date_value.day:02d}",
        "{d}": str(date_value.day),
    }
    result = template
    for token, value in replacements.items():
        result = result.replace(token, value)
    return result


def parse_explicit_dates(text: str) -> List[datetime.date]:
    """Parse one YYYY-MM-DD date per non-empty line."""
    dates: List[datetime.date] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            dates.append(datetime.date.fromisoformat(stripped))
        except ValueError as exc:
            raise ValueError(
                f"Invalid custom date {stripped!r}; expected YYYY-MM-DD."
            ) from exc
    return dates


def generated_dates(
    start_year: int,
    end_year: int,
    start_date: str,
    end_date: str,
    frequency: str,
    step: int,
) -> List[datetime.date]:
    """Create representative dates from the existing date sequence controls."""
    ranges = timelapse_core.date_sequence(
        start_year, end_year, start_date, end_date, frequency, step
    )
    return [start for start, _end, _label in ranges]


def qgis_xyz_uri(url_template: str) -> str:
    """Build a QGIS WMS provider URI for an XYZ tile template."""
    encoded_url = urllib.parse.quote(url_template, safe=":/{}?")
    return f"type=xyz&url={encoded_url}&zmin=0&zmax=23"


def is_effectively_black_image(
    image_path: str,
    pixel_threshold: int = 8,
    ratio_threshold: float = 0.995,
) -> bool:
    """Return True when an image is effectively an all-black render."""
    if timelapse_core.Image is None:
        return False

    with timelapse_core.Image.open(image_path) as image:
        width = min(image.width, 64)
        height = min(image.height, 64)
        if width == 0 or height == 0:
            return False
        rgb_image = image.convert("RGB").resize((width, height))
        total_pixels = rgb_image.width * rgb_image.height
        pixel_bytes = rgb_image.tobytes()
        dark_pixels = sum(
            1
            for index in range(0, len(pixel_bytes), 3)
            if (
                pixel_bytes[index] <= pixel_threshold
                and pixel_bytes[index + 1] <= pixel_threshold
                and pixel_bytes[index + 2] <= pixel_threshold
            )
        )
        return dark_pixels / total_pixels >= ratio_threshold


def force_gif_frame_duration(
    in_gif: str,
    out_gif: str,
    fps: int,
    loop: int = 0,
) -> None:
    """Rewrite GIF timing so the requested FPS survives overlay passes."""
    if timelapse_core.Image is None:
        return

    duration = int(1000 / max(fps, 1))
    with timelapse_core.Image.open(in_gif) as gif:
        frames = []
        for index in range(gif.n_frames):
            gif.seek(index)
            frames.append(gif.copy())

    if not frames:
        raise ValueError("No frames found in GIF.")

    frames[0].save(
        out_gif,
        format="GIF",
        append_images=frames[1:],
        save_all=True,
        duration=duration,
        loop=loop,
    )


def esri_wayback_frames(
    start_year: int,
    end_year: int,
    step: int = 1,
    max_frames: Optional[int] = None,
    fetch_layers: Callable[[], List[EsriWaybackLayer]] = fetch_esri_wayback_layers,
) -> List[ExternalFrame]:
    """Build renderable frames for ESRI Wayback."""
    layers = filter_esri_wayback_layers(
        fetch_layers(), start_year, end_year, step=step, max_frames=max_frames
    )
    return [
        ExternalFrame(
            label=layer.date.isoformat(),
            url_template=build_esri_wayback_xyz_url(layer),
            layer_name=layer.identifier,
        )
        for layer in layers
    ]


def custom_xyz_frames(
    template: str,
    explicit_dates: str,
    start_year: int,
    end_year: int,
    start_date: str,
    end_date: str,
    frequency: str,
    step: int,
) -> List[ExternalFrame]:
    """Build renderable frames for a custom XYZ template."""
    if not template.strip():
        raise ValueError("Custom XYZ URL template is required.")

    dates = parse_explicit_dates(explicit_dates)
    if not dates:
        dates = generated_dates(
            start_year, end_year, start_date, end_date, frequency, step
        )

    return [
        ExternalFrame(
            label=date_value.isoformat(),
            url_template=expand_custom_template(template.strip(), date_value),
            layer_name=f"Custom XYZ {date_value.isoformat()}",
        )
        for date_value in dates
    ]


def render_xyz_frame(
    frame: ExternalFrame,
    bbox: Dict[str, float],
    out_path: str,
    dimensions: int,
    crs: str = "EPSG:3857",
    overlay_path: Optional[str] = None,
) -> None:
    """Render one XYZ frame with the QGIS map renderer."""
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsMapRendererSequentialJob,
        QgsMapSettings,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
        QgsVectorLayer,
    )

    source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    dest_crs = QgsCoordinateReferenceSystem(crs)
    extent = QgsRectangle(bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"])
    if source_crs != dest_crs:
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        extent = transform.transformBoundingBox(extent)

    raster_layer = QgsRasterLayer(
        qgis_xyz_uri(frame.url_template), frame.layer_name, "wms"
    )
    if not raster_layer.isValid():
        raise RuntimeError(f"Could not create raster layer for {frame.layer_name}.")

    layers = [raster_layer]
    if overlay_path:
        overlay_layer = QgsVectorLayer(overlay_path, "Vector Overlay", "ogr")
        if not overlay_layer.isValid():
            raise RuntimeError(f"Could not load overlay vector file: {overlay_path}")
        layers.append(overlay_layer)

    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(dest_crs)
    settings.setExtent(extent)
    settings.setOutputSize(QSize(dimensions, dimensions))
    settings.setBackgroundColor(QColor("black"))

    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()

    image = job.renderedImage()
    if image.isNull():
        raise RuntimeError(f"QGIS rendered a blank image for {frame.layer_name}.")
    if not image.save(out_path):
        raise RuntimeError(f"Failed to save rendered frame: {out_path}")


def create_external_timelapse(
    frames: List[ExternalFrame],
    bbox: Dict[str, float],
    out_gif: str,
    dimensions: int = 768,
    frames_per_second: int = 5,
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
    overlay_path: Optional[str] = None,
    skip_black_frames: bool = True,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Render external XYZ frames to GIF and optional MP4."""
    if not frames:
        raise ValueError("No frames matched the selected external imagery settings.")

    out_gif = os.path.abspath(out_gif)
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="qgis_timelapse_frames_") as frame_dir:
        image_paths: List[str] = []
        rendered_frames: List[ExternalFrame] = []
        skipped_black_frames = 0
        for index, frame in enumerate(frames, start=1):
            if progress_callback is not None:
                progress_callback(
                    f"Rendering frame {index}/{len(frames)}: {frame.label}"
                )
            frame_path = os.path.join(frame_dir, f"{index:05d}.png")
            render_xyz_frame(
                frame,
                bbox,
                frame_path,
                dimensions,
                crs=crs,
                overlay_path=overlay_path,
            )
            if skip_black_frames and is_effectively_black_image(frame_path):
                skipped_black_frames += 1
                if progress_callback is not None:
                    progress_callback(f"Skipping black frame: {frame.label}")
                continue
            image_paths.append(frame_path)
            rendered_frames.append(frame)

        if progress_callback is not None:
            progress_callback(
                "Frame summary: "
                f"kept {len(rendered_frames)}/{len(frames)} frames; "
                f"skipped {skipped_black_frames} black frames."
            )

        if not image_paths:
            raise RuntimeError(
                "All rendered frames were black. Try a smaller AOI, different "
                "date range, or fewer ESRI Wayback layers."
            )

        timelapse_core.make_gif(
            image_paths,
            out_gif,
            ext="png",
            fps=frames_per_second,
            loop=loop,
            clean_up=False,
        )

    if add_text:
        timelapse_core.add_text_to_gif(
            out_gif,
            out_gif,
            [frame.label for frame in rendered_frames],
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=add_progress_bar,
            progress_bar_color=progress_bar_color,
            progress_bar_height=progress_bar_height,
            loop=loop,
        )

    if title is not None and isinstance(title, str) and title.strip():
        timelapse_core.add_text_to_gif(
            out_gif,
            out_gif,
            title,
            xy=("2%", "93%"),
            font_size=font_size,
            font_color=font_color,
            add_progress_bar=False,
            loop=loop,
        )

    force_gif_frame_duration(out_gif, out_gif, frames_per_second, loop=loop)

    if mp4:
        timelapse_core.gif_to_mp4(out_gif, out_gif.replace(".gif", ".mp4"))

    return out_gif
