# QGIS Timelapse Animation Creator

![QGIS Version](https://img.shields.io/badge/QGIS-3.22+-green.svg)
![License](https://img.shields.io/badge/License-MIT-blue.svg)

A QGIS plugin for creating timelapse animations from satellite and aerial imagery using Google Earth Engine. Supports NAIP, Landsat, Sentinel-2, Sentinel-1, MODIS NDVI, and GOES weather satellite imagery.


![Timelapse Plugin](https://github.com/user-attachments/assets/d4672809-5235-43f1-8971-42d7f73e3205)

## Features

- **Multiple Imagery Sources**:

  - **NAIP**: US National Agriculture Imagery Program (2003-present)
  - **Landsat**: Long-term satellite archive (1984-present)
  - **Sentinel-2**: ESA multispectral satellite imagery (2015-present)
  - **Sentinel-1**: ESA SAR satellite imagery (2014-present)
  - **MODIS NDVI**: Vegetation phenology animations
  - **GOES**: Weather satellite animations

- **Flexible Area of Interest Selection**:

  - Draw a bounding box directly on the map
  - Use the current map extent
  - Use the extent of a loaded vector layer

- **Customizable Output**:

  - GIF animations with adjustable dimensions and frame rate
  - Optional MP4 video export (requires ffmpeg)
  - Date text overlay with customizable font and color
  - Progress bar visualization
  - Configurable loop settings

- **Advanced Options**:

  - Cloud masking for Sentinel-2 and Landsat
  - Orbit selection for Sentinel-1 (ascending/descending)
  - Multiple band combinations
  - Adjustable temporal range and step size

- **Plugin Management**:
  - Built-in update checker with automatic installation
  - About dialog with version info and links

## Installation

### Prerequisites

1. **QGIS 3.28 or higher**
2. **Google Earth Engine Account**: Sign up at [earthengine.google.com](https://earthengine.google.com/)

### Install QGIS and Google Earth Engine

#### 1) Install Pixi

#### Linux/macOS (bash/zsh)

```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

Close and re-open your terminal (or reload your shell) so `pixi` is on your `PATH`. Then confirm:

```bash
pixi --version
```

#### Windows (PowerShell)

Open **PowerShell** (preferably as a normal user, Admin not required), then run:

```powershell
powershell -ExecutionPolicy Bypass -c "irm -useb https://pixi.sh/install.ps1 | iex"
```

Close and re-open PowerShell, then confirm:

```powershell
pixi --version
```

---

#### 2) Create a Pixi project

Navigate to a directory where you want to create the project and run:

```bash
pixi init geo
cd geo
```

#### 3) Install the environment

From the `geo` folder:

```bash
pixi add qgis geemap earthengine-api pillow ffmpeg
```

#### 4) Authenticate Earth Engine

```bash
pixi run earthengine authenticate
```

### Installing the Plugin

#### Method 1: From QGIS Plugin Manager (Recommended)

1. Open QGIS using `pixi run qgis`
2. Go to **Plugins** → **Manage and Install Plugins...**
3. Go to the **Settings** tab
4. Click **Add...** under "Plugin Repositories"
5. Give a name for the repository, e.g., "OpenGeos"
6. Enter the URL of the repository: <https://qgis.gishub.org/plugins.xml>
7. Click **OK**
8. Go to the **All** tab
9. Search for "Timelapse"
10. Select "Timelapse" from the list and click **Install Plugin**

#### Method 2: From ZIP File

1. Download the latest release ZIP from <https://qgis.gishub.org>
2. In QGIS, go to `Plugins` → `Manage and Install Plugins`
3. Click `Install from ZIP` and select the downloaded file
4. Enable the plugin in the `Installed` tab

#### Method 3: Manual Installation

1. Clone or download this repository
2. Copy the `timelapse` folder to your QGIS plugins directory:
   - **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Windows**: `C:\Users\<username>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   - **macOS**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
3. Restart QGIS and enable the plugin

### Uninstalling

```bash
python install.py --uninstall
# or
./install.sh --uninstall
```

## Plugin Structure

```
qgis-timelapse-plugin/
├── timelapse/                    # Plugin folder (installed to QGIS)
│   ├── __init__.py
│   ├── timelapse_plugin.py       # Main plugin class
│   ├── metadata.txt
│   ├── core/                     # Core functionality
│   │   ├── __init__.py
│   │   └── timelapse_core.py     # Earth Engine processing
│   ├── dialogs/                  # UI dialogs
│   │   ├── __init__.py
│   │   ├── timelapse_dock.py     # Main dock widget
│   │   ├── update_checker.py     # Plugin update checker
│   │   └── about_dialog.py       # About dialog
│   └── icons/                    # Plugin icons
├── install.py                    # Cross-platform installer
├── install.sh                    # Unix/Mac installer
├── package_plugin.py             # Package for distribution
├── requirements.txt
└── README.md
```

## Usage

### Quick Start

1. Click the **Timelapse** button in the toolbar or go to the `Timelapse` menu → `Create Timelapse`

2. **Define Area of Interest** (AOI tab):

   - Choose a method (draw on map, use map extent, or use vector layer)
   - For drawing: Click the "Draw Bounding Box" button, then click and drag on the map

    ![](https://github.com/user-attachments/assets/3ab196d8-7ad9-4f29-839e-a3869c1d79d6)

3. **Configure Imagery Settings** (Imagery tab):

   - Select imagery type (NAIP, Landsat, Sentinel-2, Sentinel-1, MODIS NDVI, or GOES)
   - Set the date range (start year to end year)
   - Adjust imagery-specific options (bands, cloud filtering, etc.)

    ![](https://github.com/user-attachments/assets/7cb9eaa2-1687-4d37-b64b-8810e680bc2a)

4. **Set Output Options** (Output tab):

   - Choose output file path
   - Set animation dimensions and frame rate
   - Enable MP4 conversion if needed

    ![](https://github.com/user-attachments/assets/df2207ce-db83-4d5e-ae08-031180730de1)

5. **Customize Visualization** (Style tab):

   - Configure text overlay and progress bar

    ![](https://github.com/user-attachments/assets/eeb9ee1c-a159-43b3-a124-41a6b486fd69)

6. Click **Create Timelapse** and wait for processing to complete

### Detailed Settings

#### Area of Interest Tab

| Setting            | Description                                    |
| ------------------ | ---------------------------------------------- |
| Method             | How to define the area of interest             |
| Draw Bounding Box  | Click to start drawing on the map              |
| Vector Layer       | Select a loaded vector layer to use its extent |
| Extent Coordinates | Manually enter coordinates (WGS84)             |
| GEE Project ID     | Optional Google Earth Engine project ID        |

#### Imagery Settings Tab

| Setting          | Description                                                |
| ---------------- | ---------------------------------------------------------- |
| Imagery Type     | NAIP, Landsat, Sentinel-2, Sentinel-1, MODIS NDVI, or GOES |
| Start/End Year   | Temporal range for the timelapse                           |
| Start/End Date   | Seasonal filter (MM-dd format)                             |
| Year Step        | Interval between frames                                    |
| Band Combination | Visualization bands                                        |
| Max Cloud %      | Cloud coverage threshold (Sentinel-2)                      |
| Polarization     | VV, VH, or both (Sentinel-1)                               |
| Orbit            | Ascending and/or descending (Sentinel-1)                   |

#### Output Settings Tab

| Setting           | Description                              |
| ----------------- | ---------------------------------------- |
| Output Path       | File path for the GIF animation          |
| Create MP4        | Also export as MP4 video                 |
| Dimensions        | Output image size in pixels              |
| Frames per Second | Animation speed                          |
| Loop Count        | Number of animation loops (0 = infinite) |
| CRS               | Coordinate reference system for output   |

#### Visualization Tab

| Setting          | Description             |
| ---------------- | ----------------------- |
| Add Date Text    | Show date on each frame |
| Font Size/Color  | Text styling options    |
| Add Progress Bar | Show animation progress |
| Bar Height/Color | Progress bar styling    |
| Title            | Optional title text     |

## Examples

### NAIP Timelapse (US Only)

```
Imagery Type: NAIP
Start Year: 2010
End Year: 2023
Year Step: 2
```

NAIP provides high-resolution (1m) aerial imagery for the United States. Images are typically captured during the agricultural growing season.

### Landsat Long-term Timelapse

```
Imagery Type: Landsat
Start Year: 1990
End Year: 2024
Start Date: 06-01
End Date: 09-30
Bands: NIR, Red, Green (False Color)
Apply Cloud Masking: Yes
```

This configuration creates a 34-year timelapse combining Landsat 4, 5, 7, 8, and 9 data.

### Sentinel-2 False Color Timelapse

```
Imagery Type: Sentinel-2
Start Year: 2018
End Year: 2024
Start Date: 06-01
End Date: 09-30
Bands: NIR, Red, Green (False Color)
Max Cloud: 20%
Apply Cloud Masking: Yes
```

This configuration creates a summer timelapse with vegetation highlighted in red.

### Sentinel-1 SAR Timelapse

```
Imagery Type: Sentinel-1
Start Year: 2018
End Year: 2024
Polarization: VV
Orbit: Both Ascending and Descending
```

SAR imagery is useful for monitoring changes regardless of cloud cover or lighting conditions.

### MODIS NDVI Vegetation Timelapse

```
Imagery Type: MODIS NDVI
Satellite: Terra
Index: NDVI
Start Year: 2010
End Year: 2023
```

Creates an animation showing vegetation phenology over time.

### GOES Weather Satellite Timelapse

```
Imagery Type: GOES
Satellite: GOES-17
Scan: full_disk
Start Date: 2021-10-24
End Date: 2021-10-25
```

Great for visualizing weather patterns and storms.

## Updating the Plugin

The plugin includes a built-in update checker:

1. Go to `Timelapse` menu → `Check for Updates...`
2. Click "Check for Updates" to see if a new version is available
3. If an update is found, click "Download and Install Update"
4. Restart QGIS to apply the update

## Troubleshooting

### Common Issues

**"Failed to initialize Google Earth Engine"**

- Ensure you have an active Earth Engine account
- Try running `earthengine authenticate` in the terminal
- Check your internet connection

**"No images found"**

- Verify the area of interest is within the imagery coverage
- For NAIP: Only covers the United States
- For Sentinel: Expand the date range
- Check that coordinates are in WGS84 format

**"Module not found" errors**

- Ensure required dependencies are installed (see the Installation section above)
- Ensure you're using QGIS's Python environment

**MP4 not created**

- Install ffmpeg: `sudo apt install ffmpeg` (Linux) or download from ffmpeg.org

### Performance Tips

- Start with smaller areas for testing
- Use lower dimensions (512-768px) for faster processing
- Limit the date range initially
- Higher cloud percentage thresholds reduce processing time

## Packaging for Distribution

To create a distributable ZIP file:

```bash
python package_plugin.py
```

This creates `dist/timelapse-{version}.zip` ready for upload to the QGIS plugin repository.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Based on the [geemap](https://github.com/gee-community/geemap) timelapse module by Qiusheng Wu
- Uses [Google Earth Engine](https://earthengine.google.com/) for satellite imagery processing
- Built with [QGIS](https://qgis.org/) and PyQt

## Citation

If you use this plugin in your research, please cite:

```bibtex
@software{qgis_timelapse_plugin,
  author = {Qiusheng Wu},
  title = {QGIS Timelapse Animation Creator},
  year = {2025},
  url = {https://github.com/opengeos/qgis-timelapse-plugin}
}
```

## Support

- **Issues**: [GitHub Issues](https://github.com/opengeos/qgis-timelapse-plugin/issues)
- **Discussions**: [GitHub Discussions](https://github.com/opengeos/qgis-timelapse-plugin/discussions)
