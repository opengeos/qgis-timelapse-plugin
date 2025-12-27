"""
Timelapse Dock Widget Module

This module provides the user interface for creating timelapse animations.
Uses a dockable panel for better integration with QGIS.
"""

import os
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QUrl, QTimer
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QFileDialog,
    QProgressBar,
    QTextEdit,
    QMessageBox,
    QFrame,
    QColorDialog,
    QSizePolicy,
    QScrollArea,
)
from qgis.PyQt.QtGui import QColor, QFont, QIcon
from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsWkbTypes,
    QgsGeometry,
    QgsPointXY,
)
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand

from ..core import timelapse_core


class TimelapseWorker(QThread):
    """Worker thread for generating timelapse animations."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(str, dict)  # path, params (including bbox)
    error = pyqtSignal(str)

    def __init__(self, params):
        super().__init__()
        self.params = params
        self.cancelled = False

    def run(self):
        """Execute the timelapse generation."""
        try:
            imagery_type = self.params.get("imagery_type", "Landsat")

            # Check if EE is already initialized
            if not timelapse_core.is_ee_initialized():
                self.progress.emit(f"Initializing Google Earth Engine...")
                project_id = self.params.get("gee_project", None)
                if not timelapse_core.initialize_ee(project_id):
                    self.error.emit(
                        "Failed to initialize Google Earth Engine. Please authenticate first."
                    )
                    return

            self.progress.emit(f"Creating {imagery_type} timelapse...")

            # Build ROI from bounding box
            bbox = self.params.get("bbox")
            roi = timelapse_core.bbox_to_ee_geometry(
                bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]
            )

            # Common visualization parameters
            vis_params = {
                "out_gif": self.params.get("output_path"),
                "dimensions": self.params.get("dimensions", 768),
                "frames_per_second": self.params.get("fps", 5),
                "add_text": self.params.get("add_text", True),
                "font_size": self.params.get("font_size", 20),
                "font_color": self.params.get("font_color", "white"),
                "add_progress_bar": self.params.get("add_progress_bar", True),
                "progress_bar_color": self.params.get("progress_bar_color", "white"),
                "progress_bar_height": self.params.get("progress_bar_height", 5),
                "title": self.params.get("title"),
                "mp4": self.params.get("create_mp4", False),
            }

            if imagery_type == "NAIP":
                # NAIP only supports annual composites, no frequency parameter
                naip_params = {
                    "roi": roi,
                    **vis_params,
                    "start_year": self.params.get("start_year", 2010),
                    "end_year": self.params.get("end_year", datetime.now().year),
                    "bands": self.params.get("naip_bands", ["R", "G", "B"]),
                    "step": self.params.get("step", 1),
                }
                result = timelapse_core.create_naip_timelapse(**naip_params)

            elif imagery_type == "Sentinel-2":
                s2_params = {
                    "roi": roi,
                    **vis_params,
                    "start_year": self.params.get("start_year", 2018),
                    "end_year": self.params.get("end_year", datetime.now().year),
                    "start_date": self.params.get("start_date", "06-10"),
                    "end_date": self.params.get("end_date", "09-20"),
                    "bands": self.params.get("bands", ["NIR", "Red", "Green"]),
                    "apply_fmask": self.params.get("apply_fmask", True),
                    "cloud_pct": self.params.get("cloud_pct", 30),
                    "frequency": self.params.get("frequency", "year"),
                    "step": self.params.get("step", 1),
                }
                result = timelapse_core.create_sentinel2_timelapse(**s2_params)

            elif imagery_type == "Sentinel-1":
                s1_params = {
                    "roi": roi,
                    **vis_params,
                    "start_year": self.params.get("start_year", 2018),
                    "end_year": self.params.get("end_year", datetime.now().year),
                    "start_date": self.params.get("start_date", "01-01"),
                    "end_date": self.params.get("end_date", "12-31"),
                    "bands": self.params.get("s1_bands", ["VV"]),
                    "orbit": self.params.get("orbit", ["ascending", "descending"]),
                    "frequency": self.params.get("frequency", "year"),
                    "step": self.params.get("step", 1),
                }
                result = timelapse_core.create_sentinel1_timelapse(**s1_params)

            elif imagery_type == "Landsat":
                landsat_params = {
                    "roi": roi,
                    **vis_params,
                    "start_year": self.params.get("start_year", 1990),
                    "end_year": self.params.get("end_year", datetime.now().year),
                    "start_date": self.params.get("start_date", "06-10"),
                    "end_date": self.params.get("end_date", "09-20"),
                    "bands": self.params.get("landsat_bands", ["NIR", "Red", "Green"]),
                    "apply_fmask": self.params.get("apply_fmask", True),
                    "frequency": self.params.get("frequency", "year"),
                    "step": self.params.get("step", 1),
                }
                result = timelapse_core.create_landsat_timelapse(**landsat_params)

            elif imagery_type == "MODIS NDVI":
                modis_params = {
                    "roi": roi,
                    **vis_params,
                    "data": self.params.get("modis_satellite", "Terra"),
                    "band": self.params.get("modis_band", "NDVI"),
                    "start_date": f"{self.params.get('start_year', 2010)}-01-01",
                    "end_date": f"{self.params.get('end_year', 2020)}-12-31",
                }
                result = timelapse_core.create_modis_ndvi_timelapse(**modis_params)

            elif imagery_type == "GOES":
                # GOES uses full datetime strings, not year/frequency
                goes_params = {
                    "roi": roi,
                    **vis_params,
                    "start_date": self.params.get(
                        "goes_start_datetime", "2021-10-24T14:00:00"
                    ),
                    "end_date": self.params.get(
                        "goes_end_datetime", "2021-10-25T01:00:00"
                    ),
                    "data": self.params.get("goes_satellite", "GOES-17"),
                    "scan": self.params.get("goes_scan", "full_disk"),
                    "frames_per_second": self.params.get("fps", 10),
                }
                result = timelapse_core.create_goes_timelapse(**goes_params)

            self.progress.emit("Timelapse generation complete!")
            self.finished.emit(result, self.params)

        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the operation."""
        self.cancelled = True


class BboxMapTool(QgsMapToolEmitPoint):
    """Map tool for drawing a bounding box."""

    bbox_drawn = pyqtSignal(QgsRectangle)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubber_band = None
        self.start_point = None
        self.end_point = None
        self.is_drawing = False

    def canvasPressEvent(self, event):
        """Handle mouse press event."""
        self.start_point = self.toMapCoordinates(event.pos())
        self.end_point = self.start_point
        self.is_drawing = True

        if self.rubber_band is None:
            self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
            self.rubber_band.setColor(QColor(255, 0, 0, 255))  # Red outline
            self.rubber_band.setFillColor(QColor(0, 0, 0, 0))  # Transparent fill
            self.rubber_band.setWidth(2)

        self.show_rect()

    def canvasMoveEvent(self, event):
        """Handle mouse move event."""
        if not self.is_drawing:
            return

        self.end_point = self.toMapCoordinates(event.pos())
        self.show_rect()

    def canvasReleaseEvent(self, event):
        """Handle mouse release event."""
        self.is_drawing = False

        if self.start_point and self.end_point:
            rect = QgsRectangle(self.start_point, self.end_point)
            self.bbox_drawn.emit(rect)

    def show_rect(self):
        """Display the rectangle on the canvas."""
        if self.rubber_band and self.start_point and self.end_point:
            rect = QgsRectangle(self.start_point, self.end_point)
            self.rubber_band.setToGeometry(QgsGeometry.fromRect(rect), None)
            self.rubber_band.show()

    def reset(self):
        """Reset the drawing tool."""
        if self.rubber_band:
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.start_point = None
        self.end_point = None


class TimelapseDockWidget(QDockWidget):
    """Dockable widget for timelapse configuration."""

    closed = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__("Timelapse Animation Creator", parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.bbox_tool = None
        self.current_bbox = None
        self.worker = None
        self.progress_timer = None
        self.ee_initialized = False

        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumWidth(400)

        # Create main widget with scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        main_widget = QWidget()
        self.setup_ui(main_widget)

        scroll.setWidget(main_widget)
        self.setWidget(scroll)

        self.connect_signals()

    def setup_ui(self, parent):
        """Set up the user interface."""
        layout = QVBoxLayout(parent)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Create tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # Area of Interest tab
        aoi_tab = self.create_aoi_tab()
        self.tabs.addTab(aoi_tab, "AOI")

        # Imagery tab
        imagery_tab = self.create_imagery_tab()
        self.tabs.addTab(imagery_tab, "Imagery")

        # Output tab
        output_tab = self.create_output_tab()
        self.tabs.addTab(output_tab, "Output")

        # Visualization tab
        vis_tab = self.create_visualization_tab()
        self.tabs.addTab(vis_tab, "Style")

        layout.addWidget(self.tabs)

        # Initialize imagery options after all tabs are created
        self.update_imagery_options()

        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(4)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(8)
        progress_layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(80)
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Monospace", 8))
        progress_layout.addWidget(self.log_text)

        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        # Buttons
        button_layout = QHBoxLayout()

        self.run_button = QPushButton("Create Timelapse")
        self.run_button.setMinimumHeight(36)
        self.run_button.setStyleSheet(
            """
            QPushButton {
                background-color: #2e7d32;
                color: white;
                font-weight: bold;
                font-size: 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #388e3c;
            }
            QPushButton:disabled {
                background-color: #9e9e9e;
            }
        """
        )

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumHeight(36)

        button_layout.addWidget(self.run_button, 2)
        button_layout.addWidget(self.cancel_button, 1)

        layout.addLayout(button_layout)

    def create_aoi_tab(self):
        """Create the Area of Interest tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # AOI source selection
        source_group = QGroupBox("Define Area of Interest")
        source_layout = QVBoxLayout()
        source_layout.setSpacing(6)

        # Method selection
        method_layout = QHBoxLayout()
        method_layout.addWidget(QLabel("Method:"))
        self.aoi_method = QComboBox()
        self.aoi_method.addItems(
            ["Draw bounding box", "Current map extent", "Vector layer extent"]
        )
        method_layout.addWidget(self.aoi_method)
        source_layout.addLayout(method_layout)

        # Draw and Clear buttons
        bbox_btn_layout = QHBoxLayout()

        self.draw_bbox_btn = QPushButton("Draw Bounding Box")
        self.draw_bbox_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1976d2;
                color: white;
                font-weight: bold;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1e88e5;
            }
        """
        )
        bbox_btn_layout.addWidget(self.draw_bbox_btn)

        self.clear_bbox_btn = QPushButton("Clear")
        self.clear_bbox_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #d32f2f;
                color: white;
                font-weight: bold;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e53935;
            }
        """
        )
        self.clear_bbox_btn.setMaximumWidth(60)
        bbox_btn_layout.addWidget(self.clear_bbox_btn)

        source_layout.addLayout(bbox_btn_layout)

        # Vector layer selection
        vector_layout = QHBoxLayout()
        self.vector_layer_combo = QComboBox()
        self.update_vector_layers()
        vector_layout.addWidget(self.vector_layer_combo, 1)

        self.refresh_layers_btn = QPushButton("↻")
        self.refresh_layers_btn.setMaximumWidth(30)
        vector_layout.addWidget(self.refresh_layers_btn)
        source_layout.addLayout(vector_layout)

        source_group.setLayout(source_layout)
        layout.addWidget(source_group)

        # Current extent display
        extent_group = QGroupBox("Extent (WGS84)")
        extent_layout = QFormLayout()
        extent_layout.setSpacing(4)

        self.xmin_edit = QLineEdit()
        self.ymin_edit = QLineEdit()
        self.xmax_edit = QLineEdit()
        self.ymax_edit = QLineEdit()

        for edit in [self.xmin_edit, self.ymin_edit, self.xmax_edit, self.ymax_edit]:
            edit.setPlaceholderText("0.0")

        extent_layout.addRow("West:", self.xmin_edit)
        extent_layout.addRow("South:", self.ymin_edit)
        extent_layout.addRow("East:", self.xmax_edit)
        extent_layout.addRow("North:", self.ymax_edit)

        self.use_map_extent_btn = QPushButton("Use Current Map Extent")
        extent_layout.addRow(self.use_map_extent_btn)

        extent_group.setLayout(extent_layout)
        layout.addWidget(extent_group)

        # GEE Project
        gee_group = QGroupBox("Google Earth Engine")
        gee_layout = QFormLayout()

        self.gee_project_edit = QLineEdit()
        self.gee_project_edit.setPlaceholderText("Uses EE_PROJECT_ID env var if empty")
        gee_layout.addRow("Project ID:", self.gee_project_edit)

        gee_group.setLayout(gee_layout)
        layout.addWidget(gee_group)

        layout.addStretch()
        return widget

    def create_imagery_tab(self):
        """Create the Imagery Settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # Imagery type selection
        type_group = QGroupBox("Imagery Type")
        type_layout = QVBoxLayout()

        self.imagery_type = QComboBox()
        self.imagery_type.addItems(
            ["Landsat", "Sentinel-2", "Sentinel-1", "MODIS NDVI", "GOES", "NAIP"]
        )
        self.imagery_type.setStyleSheet("font-size: 12px; padding: 4px;")
        type_layout.addWidget(self.imagery_type)

        type_group.setLayout(type_layout)
        layout.addWidget(type_group)

        # Date range (will be hidden for GOES)
        self.date_group = QGroupBox("Date Range")
        date_layout = QFormLayout()
        date_layout.setSpacing(4)

        # Year range widget
        self.year_range_widget = QWidget()
        year_layout = QHBoxLayout(self.year_range_widget)
        year_layout.setContentsMargins(0, 0, 0, 0)
        self.start_year = QSpinBox()
        self.start_year.setRange(1984, datetime.now().year)
        self.start_year.setValue(2015)

        self.end_year = QSpinBox()
        self.end_year.setRange(1984, datetime.now().year)
        self.end_year.setValue(datetime.now().year)

        year_layout.addWidget(QLabel("From:"))
        year_layout.addWidget(self.start_year)
        year_layout.addWidget(QLabel("To:"))
        year_layout.addWidget(self.end_year)
        date_layout.addRow(self.year_range_widget)

        # Seasonal date range
        self.season_widget = QWidget()
        season_layout = QHBoxLayout(self.season_widget)
        season_layout.setContentsMargins(0, 0, 0, 0)
        self.start_date = QLineEdit("06-10")
        self.start_date.setMaximumWidth(60)
        self.end_date = QLineEdit("09-20")
        self.end_date.setMaximumWidth(60)
        season_layout.addWidget(QLabel("Season:"))
        season_layout.addWidget(self.start_date)
        season_layout.addWidget(QLabel("to"))
        season_layout.addWidget(self.end_date)
        season_layout.addStretch()
        date_layout.addRow(self.season_widget)

        # Frequency selection
        self.freq_widget = QWidget()
        freq_layout = QHBoxLayout(self.freq_widget)
        freq_layout.setContentsMargins(0, 0, 0, 0)
        freq_layout.addWidget(QLabel("Frequency:"))
        self.frequency = QComboBox()
        self.frequency.addItems(["year", "quarter", "month", "day"])
        self.frequency.setToolTip(
            "Temporal frequency for compositing:\n"
            "• year: One composite per year\n"
            "• quarter: One composite per quarter (3 months)\n"
            "• month: One composite per month\n"
            "• day: Daily composites (more data intensive)"
        )
        freq_layout.addWidget(self.frequency)
        freq_layout.addStretch()
        date_layout.addRow(self.freq_widget)

        # Step widget
        self.step_widget = QWidget()
        step_layout = QHBoxLayout(self.step_widget)
        step_layout.setContentsMargins(0, 0, 0, 0)
        step_layout.addWidget(QLabel("Step:"))
        self.year_step = QSpinBox()
        self.year_step.setRange(1, 10)
        self.year_step.setValue(1)
        step_layout.addWidget(self.year_step)
        step_layout.addStretch()
        date_layout.addRow(self.step_widget)

        self.date_group.setLayout(date_layout)
        layout.addWidget(self.date_group)

        # NAIP options
        self.naip_group = QGroupBox("NAIP Options")
        naip_layout = QFormLayout()

        self.naip_bands = QComboBox()
        self.naip_bands.addItems(
            [
                "R, G, B (True Color)",
                "N, R, G (Color Infrared)",
                "N, G, B (NIR Highlight)",
            ]
        )
        naip_layout.addRow("Bands:", self.naip_bands)

        self.naip_group.setLayout(naip_layout)
        layout.addWidget(self.naip_group)

        # Landsat options
        self.landsat_group = QGroupBox("Landsat Options")
        landsat_layout = QFormLayout()

        self.landsat_bands = QComboBox()
        self.landsat_bands.addItems(
            [
                "NIR, Red, Green (False Color)",
                "Red, Green, Blue (True Color)",
                "SWIR1, NIR, Red",
                "SWIR2, SWIR1, NIR",
            ]
        )
        landsat_layout.addRow("Bands:", self.landsat_bands)

        self.landsat_fmask = QCheckBox("Apply Cloud Masking")
        self.landsat_fmask.setChecked(True)
        landsat_layout.addRow(self.landsat_fmask)

        self.landsat_group.setLayout(landsat_layout)
        layout.addWidget(self.landsat_group)

        # Sentinel-2 options
        self.s2_group = QGroupBox("Sentinel-2 Options")
        s2_layout = QFormLayout()

        self.s2_bands = QComboBox()
        self.s2_bands.addItems(
            [
                "NIR, Red, Green (False Color)",
                "Red, Green, Blue (True Color)",
                "SWIR1, NIR, Red",
                "SWIR2, SWIR1, NIR",
            ]
        )
        s2_layout.addRow("Bands:", self.s2_bands)

        self.cloud_pct = QSpinBox()
        self.cloud_pct.setRange(0, 100)
        self.cloud_pct.setValue(30)
        s2_layout.addRow("Max Cloud %:", self.cloud_pct)

        self.apply_fmask = QCheckBox("Apply Cloud Masking")
        self.apply_fmask.setChecked(True)
        s2_layout.addRow(self.apply_fmask)

        self.s2_group.setLayout(s2_layout)
        layout.addWidget(self.s2_group)

        # Sentinel-1 options
        self.s1_group = QGroupBox("Sentinel-1 Options")
        s1_layout = QFormLayout()

        self.s1_bands = QComboBox()
        self.s1_bands.addItems(["VV", "VH", "VV, VH"])
        s1_layout.addRow("Polarization:", self.s1_bands)

        self.orbit_ascending = QCheckBox("Ascending")
        self.orbit_ascending.setChecked(True)
        self.orbit_descending = QCheckBox("Descending")
        self.orbit_descending.setChecked(True)

        orbit_layout = QHBoxLayout()
        orbit_layout.addWidget(self.orbit_ascending)
        orbit_layout.addWidget(self.orbit_descending)
        s1_layout.addRow("Orbit:", orbit_layout)

        self.s1_group.setLayout(s1_layout)
        layout.addWidget(self.s1_group)

        # MODIS NDVI options
        self.modis_group = QGroupBox("MODIS NDVI Options")
        modis_layout = QFormLayout()

        self.modis_satellite = QComboBox()
        self.modis_satellite.addItems(["Terra", "Aqua"])
        modis_layout.addRow("Satellite:", self.modis_satellite)

        self.modis_band = QComboBox()
        self.modis_band.addItems(["NDVI", "EVI"])
        modis_layout.addRow("Index:", self.modis_band)

        self.modis_group.setLayout(modis_layout)
        layout.addWidget(self.modis_group)

        # GOES options
        self.goes_group = QGroupBox("GOES Options")
        goes_layout = QFormLayout()

        self.goes_satellite = QComboBox()
        self.goes_satellite.addItems(["GOES-18", "GOES-17", "GOES-16"])
        goes_layout.addRow("Satellite:", self.goes_satellite)

        self.goes_scan = QComboBox()
        self.goes_scan.addItems(["full_disk", "conus", "mesoscale"])
        goes_layout.addRow("Scan:", self.goes_scan)

        # GOES uses full datetime instead of year range
        goes_layout.addRow(QLabel("GOES uses datetime (high temporal frequency):"))
        self.goes_start_datetime = QLineEdit("2021-10-24T14:00:00")
        self.goes_start_datetime.setPlaceholderText("YYYY-MM-DDTHH:MM:SS")
        goes_layout.addRow("Start:", self.goes_start_datetime)

        self.goes_end_datetime = QLineEdit("2021-10-25T01:00:00")
        self.goes_end_datetime.setPlaceholderText("YYYY-MM-DDTHH:MM:SS")
        goes_layout.addRow("End:", self.goes_end_datetime)

        self.goes_group.setLayout(goes_layout)
        layout.addWidget(self.goes_group)

        layout.addStretch()
        return widget

    def create_output_tab(self):
        """Create the Output Settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # Output file
        file_group = QGroupBox("Output File")
        file_layout = QVBoxLayout()

        path_layout = QHBoxLayout()
        self.output_path = QLineEdit()
        default_path = os.path.join(
            os.path.expanduser("~"), "Downloads", "timelapse.gif"
        )
        self.output_path.setText(default_path)
        path_layout.addWidget(self.output_path)

        self.browse_btn = QPushButton("...")
        self.browse_btn.setMaximumWidth(30)
        path_layout.addWidget(self.browse_btn)
        file_layout.addLayout(path_layout)

        self.create_mp4 = QCheckBox("Also create MP4 (requires ffmpeg)")
        file_layout.addWidget(self.create_mp4)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Animation settings
        anim_group = QGroupBox("Animation Settings")
        anim_layout = QFormLayout()

        self.dimensions = QSpinBox()
        self.dimensions.setRange(256, 2048)
        self.dimensions.setValue(768)
        self.dimensions.setSingleStep(64)
        anim_layout.addRow("Dimensions:", self.dimensions)

        self.fps = QSpinBox()
        self.fps.setRange(1, 30)
        self.fps.setValue(5)
        anim_layout.addRow("FPS:", self.fps)

        self.loop_count = QSpinBox()
        self.loop_count.setRange(0, 100)
        self.loop_count.setValue(0)
        self.loop_count.setSpecialValueText("Infinite")
        anim_layout.addRow("Loops:", self.loop_count)

        anim_group.setLayout(anim_layout)
        layout.addWidget(anim_group)

        # CRS
        crs_group = QGroupBox("CRS")
        crs_layout = QFormLayout()

        self.crs_combo = QComboBox()
        self.crs_combo.addItems(
            [
                "EPSG:3857 (Web Mercator)",
                "EPSG:4326 (WGS 84)",
            ]
        )
        crs_layout.addRow("CRS:", self.crs_combo)

        crs_group.setLayout(crs_layout)
        layout.addWidget(crs_group)

        layout.addStretch()
        return widget

    def create_visualization_tab(self):
        """Create the Visualization Settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # Text overlay
        text_group = QGroupBox("Text Overlay")
        text_layout = QFormLayout()

        self.add_text = QCheckBox("Add Date Text")
        self.add_text.setChecked(True)
        text_layout.addRow(self.add_text)

        self.font_size = QSpinBox()
        self.font_size.setRange(8, 72)
        self.font_size.setValue(20)
        text_layout.addRow("Size:", self.font_size)

        font_color_layout = QHBoxLayout()
        self.font_color_btn = QPushButton()
        self.font_color_btn.setFixedSize(40, 24)
        self.font_color = "white"
        self.update_color_button(self.font_color_btn, self.font_color)
        font_color_layout.addWidget(self.font_color_btn)
        font_color_layout.addStretch()
        text_layout.addRow("Color:", font_color_layout)

        text_group.setLayout(text_layout)
        layout.addWidget(text_group)

        # Progress bar
        progress_group = QGroupBox("Progress Bar")
        progress_layout = QFormLayout()

        self.add_progress = QCheckBox("Add Progress Bar")
        self.add_progress.setChecked(True)
        progress_layout.addRow(self.add_progress)

        self.progress_height = QSpinBox()
        self.progress_height.setRange(1, 20)
        self.progress_height.setValue(5)
        progress_layout.addRow("Height:", self.progress_height)

        bar_color_layout = QHBoxLayout()
        self.bar_color_btn = QPushButton()
        self.bar_color_btn.setFixedSize(40, 24)
        self.bar_color = "white"
        self.update_color_button(self.bar_color_btn, self.bar_color)
        bar_color_layout.addWidget(self.bar_color_btn)
        bar_color_layout.addStretch()
        progress_layout.addRow("Color:", bar_color_layout)

        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        # Title overlay
        title_group = QGroupBox("Title")
        title_layout = QFormLayout()

        self.title_text = QLineEdit()
        self.title_text.setPlaceholderText("Optional title text")
        title_layout.addRow("Title:", self.title_text)

        title_group.setLayout(title_layout)
        layout.addWidget(title_group)

        layout.addStretch()
        return widget

    def connect_signals(self):
        """Connect UI signals to slots."""
        self.draw_bbox_btn.clicked.connect(self.start_bbox_drawing)
        self.clear_bbox_btn.clicked.connect(self.clear_bbox)
        self.use_map_extent_btn.clicked.connect(self.use_map_extent)
        self.refresh_layers_btn.clicked.connect(self.update_vector_layers)
        self.browse_btn.clicked.connect(self.browse_output)
        self.run_button.clicked.connect(self.run_timelapse)
        self.cancel_button.clicked.connect(self.cancel_timelapse)

        self.imagery_type.currentIndexChanged.connect(self.update_imagery_options)
        self.aoi_method.currentIndexChanged.connect(self.update_aoi_method)

        self.font_color_btn.clicked.connect(lambda: self.pick_color("font"))
        self.bar_color_btn.clicked.connect(lambda: self.pick_color("bar"))

        self.vector_layer_combo.currentIndexChanged.connect(self.use_layer_extent)

    def update_color_button(self, button, color_name):
        """Update a color button's appearance."""
        button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {color_name};
                border: 2px solid #333;
                border-radius: 3px;
            }}
        """
        )

    def pick_color(self, color_type):
        """Open color picker dialog."""
        color = QColorDialog.getColor()
        if color.isValid():
            color_name = color.name()
            if color_type == "font":
                self.font_color = color_name
                self.update_color_button(self.font_color_btn, color_name)
            elif color_type == "bar":
                self.bar_color = color_name
                self.update_color_button(self.bar_color_btn, color_name)

    def update_imagery_options(self):
        """Show/hide imagery-specific options."""
        imagery = self.imagery_type.currentText()

        self.naip_group.setVisible(imagery == "NAIP")
        self.landsat_group.setVisible(imagery == "Landsat")
        self.s2_group.setVisible(imagery == "Sentinel-2")
        self.s1_group.setVisible(imagery == "Sentinel-1")
        self.modis_group.setVisible(imagery == "MODIS NDVI")
        self.goes_group.setVisible(imagery == "GOES")

        # Show/hide date range controls based on imagery type
        # GOES uses its own datetime fields, not year range
        is_goes = imagery == "GOES"
        self.date_group.setVisible(not is_goes)

        # Update start year based on imagery
        if imagery == "NAIP":
            self.start_year.setMinimum(2003)
            self.start_year.setValue(2010)
        elif imagery == "Landsat":
            self.start_year.setMinimum(1984)
            self.start_year.setValue(1990)
        elif imagery in ["Sentinel-2", "Sentinel-1"]:
            self.start_year.setMinimum(2015)
            self.start_year.setValue(2018)
        elif imagery == "MODIS NDVI":
            self.start_year.setMinimum(2000)
            self.start_year.setValue(2010)

        # Update output filename based on imagery type
        self.update_output_filename(imagery)

    def update_output_filename(self, imagery_type):
        """Update output filename based on imagery type."""
        filename_map = {
            "Landsat": "landsat_timelapse.gif",
            "Sentinel-2": "sentinel2_timelapse.gif",
            "Sentinel-1": "sentinel1_timelapse.gif",
            "MODIS NDVI": "modis_ndvi_timelapse.gif",
            "GOES": "goes_timelapse.gif",
            "NAIP": "naip_timelapse.gif",
        }
        filename = filename_map.get(imagery_type, "timelapse.gif")
        output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.output_path.setText(os.path.join(output_dir, filename))

    def update_aoi_method(self):
        """Update AOI controls based on selected method."""
        method = self.aoi_method.currentIndex()

        self.draw_bbox_btn.setEnabled(method == 0)
        self.clear_bbox_btn.setEnabled(method == 0)
        self.vector_layer_combo.setEnabled(method == 2)

        if method == 1:
            self.use_map_extent()
        elif method == 2:
            self.use_layer_extent()

    def update_vector_layers(self):
        """Update the vector layer combo box."""
        self.vector_layer_combo.clear()
        self.vector_layer_combo.addItem("-- Select Layer --")

        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if isinstance(layer, QgsVectorLayer):
                self.vector_layer_combo.addItem(layer.name(), layer_id)

    def start_bbox_drawing(self):
        """Start the bounding box drawing tool."""
        self.bbox_tool = BboxMapTool(self.canvas)
        self.bbox_tool.bbox_drawn.connect(self.on_bbox_drawn)
        self.canvas.setMapTool(self.bbox_tool)

        self.log("Click and drag on the map to draw a bounding box...")

    def clear_bbox(self):
        """Clear the drawn bounding box from the map."""
        # Reset the bbox tool's rubber band
        if self.bbox_tool:
            self.bbox_tool.reset()

        # Clear the extent fields
        self.xmin_edit.clear()
        self.ymin_edit.clear()
        self.xmax_edit.clear()
        self.ymax_edit.clear()

        # Clear stored bbox
        self.current_bbox = None

        # Refresh the canvas
        self.canvas.refresh()

        self.log("Bounding box cleared")

    def on_bbox_drawn(self, rect):
        """Handle bounding box drawn event."""
        # Transform to WGS84
        source_crs = self.canvas.mapSettings().destinationCrs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())

        rect_wgs84 = transform.transformBoundingBox(rect)

        self.xmin_edit.setText(f"{rect_wgs84.xMinimum():.6f}")
        self.ymin_edit.setText(f"{rect_wgs84.yMinimum():.6f}")
        self.xmax_edit.setText(f"{rect_wgs84.xMaximum():.6f}")
        self.ymax_edit.setText(f"{rect_wgs84.yMaximum():.6f}")

        self.current_bbox = {
            "xmin": rect_wgs84.xMinimum(),
            "ymin": rect_wgs84.yMinimum(),
            "xmax": rect_wgs84.xMaximum(),
            "ymax": rect_wgs84.yMaximum(),
        }

        self.log(f"Bounding box set")

    def use_map_extent(self):
        """Use the current map extent as AOI."""
        extent = self.canvas.extent()
        source_crs = self.canvas.mapSettings().destinationCrs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())

        extent_wgs84 = transform.transformBoundingBox(extent)

        self.xmin_edit.setText(f"{extent_wgs84.xMinimum():.6f}")
        self.ymin_edit.setText(f"{extent_wgs84.yMinimum():.6f}")
        self.xmax_edit.setText(f"{extent_wgs84.xMaximum():.6f}")
        self.ymax_edit.setText(f"{extent_wgs84.yMaximum():.6f}")

        self.current_bbox = {
            "xmin": extent_wgs84.xMinimum(),
            "ymin": extent_wgs84.yMinimum(),
            "xmax": extent_wgs84.xMaximum(),
            "ymax": extent_wgs84.yMaximum(),
        }

        self.log(f"Using map extent")

    def use_layer_extent(self):
        """Use the selected layer's extent as AOI."""
        layer_id = self.vector_layer_combo.currentData()
        if not layer_id:
            return

        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return

        extent = layer.extent()
        source_crs = layer.crs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())

        extent_wgs84 = transform.transformBoundingBox(extent)

        self.xmin_edit.setText(f"{extent_wgs84.xMinimum():.6f}")
        self.ymin_edit.setText(f"{extent_wgs84.yMinimum():.6f}")
        self.xmax_edit.setText(f"{extent_wgs84.xMaximum():.6f}")
        self.ymax_edit.setText(f"{extent_wgs84.yMaximum():.6f}")

        self.current_bbox = {
            "xmin": extent_wgs84.xMinimum(),
            "ymin": extent_wgs84.yMinimum(),
            "xmax": extent_wgs84.xMaximum(),
            "ymax": extent_wgs84.yMaximum(),
        }

        self.log(f"Using layer extent: {layer.name()}")

    def browse_output(self):
        """Open file browser for output path."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Timelapse",
            self.output_path.text(),
            "GIF Files (*.gif);;All Files (*)",
        )
        if path:
            if not path.endswith(".gif"):
                path += ".gif"
            self.output_path.setText(path)

    def validate_inputs(self):
        """Validate all inputs before running."""
        # Check bbox
        try:
            bbox = {
                "xmin": float(self.xmin_edit.text()),
                "ymin": float(self.ymin_edit.text()),
                "xmax": float(self.xmax_edit.text()),
                "ymax": float(self.ymax_edit.text()),
            }

            if bbox["xmin"] >= bbox["xmax"] or bbox["ymin"] >= bbox["ymax"]:
                raise ValueError("Invalid bounding box coordinates")

            self.current_bbox = bbox
        except (ValueError, TypeError):
            QMessageBox.warning(
                self, "Invalid Input", "Please specify a valid bounding box."
            )
            return False

        # Check output path
        output_path = self.output_path.text()
        if not output_path:
            QMessageBox.warning(
                self, "Invalid Input", "Please specify an output file path."
            )
            return False

        # Check date range
        if self.start_year.value() > self.end_year.value():
            QMessageBox.warning(
                self, "Invalid Input", "Start year must be before or equal to end year."
            )
            return False

        return True

    def get_naip_bands(self):
        """Get selected NAIP bands."""
        band_options = {
            "R, G, B (True Color)": ["R", "G", "B"],
            "N, R, G (Color Infrared)": ["N", "R", "G"],
            "N, G, B (NIR Highlight)": ["N", "G", "B"],
        }
        return band_options.get(self.naip_bands.currentText(), ["R", "G", "B"])

    def get_landsat_bands(self):
        """Get selected Landsat bands."""
        band_options = {
            "NIR, Red, Green (False Color)": ["NIR", "Red", "Green"],
            "Red, Green, Blue (True Color)": ["Red", "Green", "Blue"],
            "SWIR1, NIR, Red": ["SWIR1", "NIR", "Red"],
            "SWIR2, SWIR1, NIR": ["SWIR2", "SWIR1", "NIR"],
        }
        return band_options.get(
            self.landsat_bands.currentText(), ["NIR", "Red", "Green"]
        )

    def get_s2_bands(self):
        """Get selected Sentinel-2 bands."""
        band_options = {
            "NIR, Red, Green (False Color)": ["NIR", "Red", "Green"],
            "Red, Green, Blue (True Color)": ["Red", "Green", "Blue"],
            "SWIR1, NIR, Red": ["SWIR1", "NIR", "Red"],
            "SWIR2, SWIR1, NIR": ["SWIR2", "SWIR1", "NIR"],
        }
        return band_options.get(self.s2_bands.currentText(), ["NIR", "Red", "Green"])

    def get_s1_bands(self):
        """Get selected Sentinel-1 bands."""
        band_text = self.s1_bands.currentText()
        if band_text == "VV, VH":
            return ["VV", "VH"]
        return [band_text]

    def get_orbit_directions(self):
        """Get selected orbit directions."""
        orbits = []
        if self.orbit_ascending.isChecked():
            orbits.append("ascending")
        if self.orbit_descending.isChecked():
            orbits.append("descending")
        return orbits if orbits else ["ascending", "descending"]

    def get_crs(self):
        """Get selected CRS."""
        crs_text = self.crs_combo.currentText()
        return crs_text.split(" ")[0]

    def run_timelapse(self):
        """Start timelapse generation."""
        if not self.validate_inputs():
            return

        # Collect parameters
        params = {
            "imagery_type": self.imagery_type.currentText(),
            "bbox": self.current_bbox,
            "start_year": self.start_year.value(),
            "end_year": self.end_year.value(),
            "start_date": self.start_date.text(),
            "end_date": self.end_date.text(),
            "frequency": self.frequency.currentText(),
            "step": self.year_step.value(),
            "output_path": self.output_path.text(),
            "dimensions": self.dimensions.value(),
            "fps": self.fps.value(),
            "crs": self.get_crs(),
            "gee_project": self.gee_project_edit.text() or None,
            # NAIP specific
            "naip_bands": self.get_naip_bands(),
            # Landsat specific
            "landsat_bands": self.get_landsat_bands(),
            # Sentinel-2 specific
            "bands": self.get_s2_bands(),
            "cloud_pct": self.cloud_pct.value(),
            "apply_fmask": self.apply_fmask.isChecked(),
            # Sentinel-1 specific
            "s1_bands": self.get_s1_bands(),
            "orbit": self.get_orbit_directions(),
            # MODIS specific
            "modis_satellite": self.modis_satellite.currentText(),
            "modis_band": self.modis_band.currentText(),
            # GOES specific
            "goes_satellite": self.goes_satellite.currentText(),
            "goes_scan": self.goes_scan.currentText(),
            "goes_start_datetime": self.goes_start_datetime.text(),
            "goes_end_datetime": self.goes_end_datetime.text(),
            # Visualization
            "add_text": self.add_text.isChecked(),
            "font_size": self.font_size.value(),
            "font_color": self.font_color,
            "add_progress_bar": self.add_progress.isChecked(),
            "progress_bar_color": self.bar_color,
            "progress_bar_height": self.progress_height.value(),
            "title": self.title_text.text() or None,
            "create_mp4": self.create_mp4.isChecked(),
        }

        # Start worker thread
        self.worker = TimelapseWorker(params)
        self.worker.progress.connect(self.log)
        self.worker.finished.connect(self.on_timelapse_finished)
        self.worker.error.connect(self.on_timelapse_error)

        self.run_button.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.start_progress_animation()

        self.worker.start()

    def cancel_timelapse(self):
        """Cancel the running timelapse generation."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.log("Cancelling...")

    def on_timelapse_finished(self, output_path, params):
        """Handle successful timelapse generation."""
        self.run_button.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stop_progress_animation()

        self.log(f"Saved to: {output_path}")

        if not os.path.exists(output_path):
            return

        # Open the GIF file in external viewer
        QDesktopServices.openUrl(QUrl.fromLocalFile(output_path))

    def on_timelapse_error(self, error_msg):
        """Handle timelapse generation error."""
        self.run_button.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stop_progress_animation()

        self.log(f"Error: {error_msg}")

        QMessageBox.critical(
            self, "Error", f"Failed to create timelapse:\n\n{error_msg}"
        )

    def start_progress_animation(self):
        """Start animated progress bar."""
        self.progress_value = 0
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress_animation)
        self.progress_timer.start(100)  # Update every 100ms

    def update_progress_animation(self):
        """Update the progress bar animation."""
        self.progress_value = (self.progress_value + 2) % 90  # Animate 0-90%
        self.progress_bar.setValue(self.progress_value)

    def stop_progress_animation(self):
        """Stop the progress bar animation."""
        if hasattr(self, "progress_timer") and self.progress_timer:
            self.progress_timer.stop()
            self.progress_timer = None

    def log(self, message):
        """Add a message to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def closeEvent(self, event):
        """Handle dock widget close event."""
        if self.bbox_tool:
            self.bbox_tool.reset()
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        self.stop_progress_animation()
        self.closed.emit()
        event.accept()


# Backward compatibility alias
TimelapseDialog = TimelapseDockWidget
