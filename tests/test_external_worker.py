from timelapse.core import external_sources, timelapse_core
from timelapse.dialogs.timelapse_dock import TimelapseWorker


def test_external_worker_does_not_initialize_earth_engine(monkeypatch):
    called = {"render": False}

    def fail_initialize(*args, **kwargs):
        raise AssertionError("External imagery must not initialize Earth Engine")

    def fake_frames(**kwargs):
        return [
            external_sources.ExternalFrame(
                label="2026-01-01",
                url_template="https://example.test/{z}/{x}/{y}.png",
                layer_name="test",
            )
        ]

    def fake_render(**kwargs):
        called["render"] = True
        assert kwargs["frames"][0].label == "2026-01-01"
        assert kwargs["bbox"]["xmin"] == -1.0
        return "/tmp/external.gif"

    monkeypatch.setattr(timelapse_core, "_ee_initialized", False)
    monkeypatch.setattr(timelapse_core, "initialize_ee", fail_initialize)
    monkeypatch.setattr(external_sources, "esri_wayback_frames", fake_frames)
    monkeypatch.setattr(external_sources, "create_external_timelapse", fake_render)

    worker = TimelapseWorker(
        {
            "imagery_type": "ESRI Wayback",
            "bbox": {"xmin": -1.0, "ymin": -1.0, "xmax": 1.0, "ymax": 1.0},
            "output_path": "/tmp/external.gif",
            "start_year": 2026,
            "end_year": 2026,
            "step": 1,
        }
    )

    worker.run()

    assert called["render"] is True
