"""Tests for virtual environment dependency status checks."""

from timelapse.core import python_manager, venv_manager


def _write_dist_info(site_packages, directory_name, package_name, version):
    dist_info = site_packages / directory_name
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "\n".join(
            [
                "Metadata-Version: 2.1",
                f"Name: {package_name}",
                f"Version: {version}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_get_venv_status_accepts_pillow_import_and_lowercase_dist_info(
    tmp_path, monkeypatch
):
    """Pillow installs as PIL plus lowercase pillow-*.dist-info on Unix."""
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()

    _write_dist_info(
        site_packages,
        "earthengine_api-1.7.4.dist-info",
        "earthengine-api",
        "1.7.4",
    )
    _write_dist_info(site_packages, "numpy-2.3.5.dist-info", "numpy", "2.3.5")
    _write_dist_info(site_packages, "pillow-12.1.1.dist-info", "Pillow", "12.1.1")
    _write_dist_info(
        site_packages,
        "google_auth_oauthlib-1.2.3.dist-info",
        "google-auth-oauthlib",
        "1.2.3",
    )
    (site_packages / "PIL").mkdir()

    monkeypatch.setattr(python_manager, "standalone_python_exists", lambda: True)
    monkeypatch.setattr(venv_manager, "venv_exists", lambda venv_dir=None: True)
    monkeypatch.setattr(
        venv_manager,
        "get_venv_site_packages",
        lambda venv_dir=None: str(site_packages),
    )

    assert venv_manager.get_venv_status() == (True, "Virtual environment ready")


def test_check_dependencies_reports_versions_from_venv_site_packages(
    tmp_path, monkeypatch
):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()

    _write_dist_info(
        site_packages,
        "earthengine_api-1.7.4.dist-info",
        "earthengine-api",
        "1.7.4",
    )
    _write_dist_info(site_packages, "numpy-2.3.5.dist-info", "numpy", "2.3.5")
    _write_dist_info(site_packages, "pillow-12.1.1.dist-info", "Pillow", "12.1.1")
    _write_dist_info(
        site_packages,
        "google_auth_oauthlib-1.2.3.dist-info",
        "google-auth-oauthlib",
        "1.2.3",
    )

    monkeypatch.setattr(venv_manager, "venv_exists", lambda venv_dir=None: True)
    monkeypatch.setattr(
        venv_manager,
        "get_venv_site_packages",
        lambda venv_dir=None: str(site_packages),
    )
    monkeypatch.setattr(venv_manager, "ensure_venv_packages_available", lambda: True)

    all_ok, missing, installed = venv_manager.check_dependencies()

    assert all_ok is True
    assert missing == []
    assert dict(installed)["Pillow"] == "12.1.1"
