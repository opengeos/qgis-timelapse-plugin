import datetime

import pytest

from timelapse.core import external_sources, timelapse_core

MINIMAL_WAYBACK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Capabilities xmlns="https://www.opengis.net/wmts/1.0"
  xmlns:ows="https://www.opengis.net/ows/1.1" version="1.0.0">
  <Contents>
    <Layer>
      <ows:Title>World Imagery (Wayback 2024-02-29)</ows:Title>
      <ows:Identifier>WB_2024_R02</ows:Identifier>
      <Format>image/jpeg</Format>
      <TileMatrixSetLink><TileMatrixSet>default028mm</TileMatrixSet></TileMatrixSetLink>
      <TileMatrixSetLink><TileMatrixSet>GoogleMapsCompatible</TileMatrixSet></TileMatrixSetLink>
      <ResourceURL format="image/jpeg" resourceType="tile"
        template="https://example.test/{TileMatrixSet}/tile/123/{TileMatrix}/{TileRow}/{TileCol}"/>
    </Layer>
    <Layer>
      <ows:Title>World Imagery (Wayback 2023-12-15)</ows:Title>
      <ows:Identifier>WB_2023_R12</ows:Identifier>
      <Format>image/jpeg</Format>
      <TileMatrixSetLink><TileMatrixSet>GoogleMapsCompatible</TileMatrixSet></TileMatrixSetLink>
      <ResourceURL format="image/jpeg" resourceType="tile"
        template="https://example.test/{TileMatrixSet}/tile/456/{TileMatrix}/{TileRow}/{TileCol}"/>
    </Layer>
  </Contents>
</Capabilities>
"""


def test_parse_esri_wayback_capabilities_https_namespaces():
    layers = external_sources.parse_esri_wayback_capabilities(MINIMAL_WAYBACK_XML)

    assert [layer.identifier for layer in layers] == ["WB_2023_R12", "WB_2024_R02"]
    assert layers[0].date == datetime.date(2023, 12, 15)
    assert layers[0].tile_matrix_set == "GoogleMapsCompatible"
    assert layers[1].tile_template.endswith(
        "/{TileMatrixSet}/tile/123/{TileMatrix}/{TileRow}/{TileCol}"
    )


def test_build_esri_wayback_xyz_url_converts_wmts_tokens():
    layer = external_sources.parse_esri_wayback_capabilities(MINIMAL_WAYBACK_XML)[0]

    assert external_sources.build_esri_wayback_xyz_url(layer) == (
        "https://example.test/GoogleMapsCompatible/tile/456/{z}/{y}/{x}"
    )


def test_filter_esri_wayback_layers_year_step_and_max_frames():
    layers = external_sources.parse_esri_wayback_capabilities(MINIMAL_WAYBACK_XML)

    selected = external_sources.filter_esri_wayback_layers(
        layers, 2023, 2024, step=2, max_frames=1
    )

    assert [layer.identifier for layer in selected] == ["WB_2023_R12"]


def test_expand_custom_template_keeps_tile_tokens():
    url = external_sources.expand_custom_template(
        "https://tiles.planet.com/global_monthly_{yyyy}_{MM}_mosaic/{z}/{x}/{y}.png",
        datetime.date(2026, 3, 5),
    )

    assert url == (
        "https://tiles.planet.com/global_monthly_2026_03_mosaic/{z}/{x}/{y}.png"
    )


def test_parse_explicit_dates_rejects_bad_dates():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        external_sources.parse_explicit_dates("2026-01-01\nnot-a-date\n")


def test_custom_xyz_frames_uses_explicit_dates_before_generated_dates():
    frames = external_sources.custom_xyz_frames(
        template="https://example.test/{date}/{z}/{x}/{y}.png",
        explicit_dates="2026-01-05\n2026-02-06",
        start_year=2020,
        end_year=2020,
        start_date="01-01",
        end_date="12-31",
        frequency="year",
        step=1,
    )

    assert [frame.label for frame in frames] == ["2026-01-05", "2026-02-06"]
    assert frames[0].url_template == "https://example.test/2026-01-05/{z}/{x}/{y}.png"


def test_qgis_xyz_uri_encodes_query_delimiters_inside_template():
    uri = external_sources.qgis_xyz_uri(
        "https://example.test/{z}/{x}/{y}.png?api_key=a&style=b"
    )

    assert uri.startswith("type=xyz&url=")
    assert "%26style%3Db" in uri


def test_is_effectively_black_image_detects_black_renders(tmp_path):
    black_path = tmp_path / "black.png"
    color_path = tmp_path / "color.png"
    timelapse_core.Image.new("RGB", (10, 10), (0, 0, 0)).save(black_path)
    timelapse_core.Image.new("RGB", (10, 10), (0, 128, 0)).save(color_path)

    assert external_sources.is_effectively_black_image(str(black_path)) is True
    assert external_sources.is_effectively_black_image(str(color_path)) is False


def test_create_external_timelapse_skips_black_frames_and_forces_fps(
    monkeypatch, tmp_path
):
    colors = [(0, 0, 0), (40, 80, 120)]

    def fake_render(
        frame, bbox, out_path, dimensions, crs="EPSG:3857", overlay_path=None
    ):
        color = colors.pop(0)
        timelapse_core.Image.new("RGB", (16, 16), color).save(out_path)

    monkeypatch.setattr(external_sources, "render_xyz_frame", fake_render)

    frames = [
        external_sources.ExternalFrame("black", "https://example.test/{z}", "black"),
        external_sources.ExternalFrame("color", "https://example.test/{z}", "color"),
    ]
    out_gif = tmp_path / "external.gif"
    messages = []

    external_sources.create_external_timelapse(
        frames=frames,
        bbox={"xmin": -1, "ymin": -1, "xmax": 1, "ymax": 1},
        out_gif=str(out_gif),
        frames_per_second=2,
        add_text=True,
        progress_callback=messages.append,
    )

    with timelapse_core.Image.open(out_gif) as gif:
        assert gif.n_frames == 1
        assert gif.info["duration"] == 500
    assert messages[-1] == (
        "Frame summary: kept 1/2 frames; skipped 1 black frames; "
        "skipped 0 duplicate frames."
    )


def test_create_external_timelapse_skips_duplicate_frames(monkeypatch, tmp_path):
    colors = [(40, 80, 120), (40, 80, 120), (120, 80, 40)]

    def fake_render(
        frame, bbox, out_path, dimensions, crs="EPSG:3857", overlay_path=None
    ):
        color = colors.pop(0)
        timelapse_core.Image.new("RGB", (16, 16), color).save(out_path)

    monkeypatch.setattr(external_sources, "render_xyz_frame", fake_render)

    frames = [
        external_sources.ExternalFrame("first", "https://example.test/{z}", "first"),
        external_sources.ExternalFrame("duplicate", "https://example.test/{z}", "dup"),
        external_sources.ExternalFrame(
            "changed", "https://example.test/{z}", "changed"
        ),
    ]
    out_gif = tmp_path / "external.gif"
    messages = []

    external_sources.create_external_timelapse(
        frames=frames,
        bbox={"xmin": -1, "ymin": -1, "xmax": 1, "ymax": 1},
        out_gif=str(out_gif),
        add_text=False,
        progress_callback=messages.append,
    )

    with timelapse_core.Image.open(out_gif) as gif:
        assert gif.n_frames == 2
    assert "Skipping duplicate frame: duplicate" in messages
    assert messages[-1] == (
        "Frame summary: kept 2/3 frames; skipped 0 black frames; "
        "skipped 1 duplicate frames."
    )


def test_force_gif_frame_duration_updates_existing_gif(tmp_path):
    out_gif = tmp_path / "timing.gif"
    frame = timelapse_core.Image.new("RGB", (16, 16), (40, 80, 120))
    frame.save(out_gif, format="GIF", save_all=True, duration=1000, loop=0)

    external_sources.force_gif_frame_duration(str(out_gif), str(out_gif), fps=10)

    with timelapse_core.Image.open(out_gif) as gif:
        assert gif.info["duration"] == 100
