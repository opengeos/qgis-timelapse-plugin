"""
Virtual Environment Manager for Timelapse Plugin

This module manages an isolated Python virtual environment at ~/.qgis_timelapse
for installing plugin dependencies (earthengine-api, numpy, Pillow) without
contaminating the QGIS built-in Python environment.
"""

import os
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Optional

try:
    from qgis.core import Qgis, QgsMessageLog
except ImportError:
    QgsMessageLog = None
    Qgis = None

VENV_DIR = os.path.expanduser("~/.qgis_timelapse")

REQUIRED_PACKAGES = [
    "earthengine-api>=0.1.300",
    "numpy>=1.20.0",
    "Pillow>=9.0.0",
]


def _log(message: str, level: int = 0) -> None:
    """Log a message to the QGIS message log.

    Args:
        message: The message to log.
        level: QGIS log level (0=Info, 1=Warning, 2=Critical).
    """
    if QgsMessageLog is not None and Qgis is not None:
        qgis_level = {0: Qgis.Info, 1: Qgis.Warning, 2: Qgis.Critical}.get(
            level, Qgis.Info
        )
        QgsMessageLog.logMessage(message, "Timelapse", qgis_level)
    else:
        print(f"[Timelapse] {message}")


def _get_system_python() -> str:
    """Find a usable Python executable for creating the virtual environment.

    In QGIS, sys.executable often points to the QGIS binary, not Python.
    This function locates a suitable Python interpreter.

    Returns:
        Path to a Python executable.

    Raises:
        FileNotFoundError: If no suitable Python can be found.
    """
    if sys.platform == "win32":
        # QGIS on Windows bundles Python under sys.prefix
        candidate = os.path.join(sys.prefix, "python.exe")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(sys.prefix, "python3.exe")
        if os.path.isfile(candidate):
            return candidate
        found = shutil.which("python3") or shutil.which("python")
        if found:
            return found
    else:
        # Linux / macOS
        for name in ("python3", "python"):
            found = shutil.which(name)
            if found:
                return found

    # Last resort
    if os.path.isfile(sys.executable):
        return sys.executable

    raise FileNotFoundError(
        "Cannot find a Python interpreter to create the virtual environment. "
        "Please ensure python3 is installed and available on your PATH."
    )


def _get_clean_env_for_venv() -> dict:
    """Create a clean environment dict for subprocess calls.

    Removes QGIS-specific environment variables that would cause the venv
    Python to pick up QGIS's own site-packages or fail with path confusion.

    Returns:
        A copy of os.environ with problematic keys removed.
    """
    env = os.environ.copy()
    for key in [
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "QGIS_PREFIX_PATH",
        "QGIS_PLUGINPATH",
        "QT_PLUGIN_PATH",
        "PYQGIS_STARTUP",
        "PROJ_DATA",
        "PROJ_LIB",
        "GDAL_DATA",
        "GDAL_DRIVER_PATH",
    ]:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _get_subprocess_kwargs() -> dict:
    """Get platform-specific subprocess keyword arguments.

    Returns:
        Dict of kwargs to pass to subprocess.run/Popen.
    """
    kwargs = {}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def get_venv_python_path() -> str:
    """Return the path to the Python binary inside the venv.

    Returns:
        Path to the venv Python executable.
    """
    if sys.platform == "win32":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python3")


def get_venv_pip_path() -> str:
    """Return the path to pip inside the venv.

    Returns:
        Path to the venv pip executable.
    """
    if sys.platform == "win32":
        return os.path.join(VENV_DIR, "Scripts", "pip.exe")
    return os.path.join(VENV_DIR, "bin", "pip3")


def get_venv_site_packages() -> Optional[str]:
    """Return the site-packages directory in the venv.

    Uses dynamic version detection by scanning the lib directory for
    a pythonX.Y folder containing site-packages.

    Returns:
        Path to site-packages, or None if not found.
    """
    if sys.platform == "win32":
        sp = os.path.join(VENV_DIR, "Lib", "site-packages")
        return sp if os.path.isdir(sp) else None

    lib_dir = os.path.join(VENV_DIR, "lib")
    if os.path.isdir(lib_dir):
        for entry in os.listdir(lib_dir):
            if entry.startswith("python") and os.path.isdir(
                os.path.join(lib_dir, entry)
            ):
                sp = os.path.join(lib_dir, entry, "site-packages")
                if os.path.isdir(sp):
                    return sp

    # Fallback using current Python version
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    sp = os.path.join(lib_dir, py_ver, "site-packages")
    return sp if os.path.isdir(sp) else None


def venv_exists() -> bool:
    """Check if the virtual environment has been created.

    Returns:
        True if the venv Python binary exists.
    """
    return os.path.isfile(get_venv_python_path())


def dependencies_available() -> bool:
    """Quick filesystem check for installed dependencies.

    Checks for the presence of key package directories in the venv's
    site-packages without importing or running subprocesses.

    Returns:
        True if all required dependencies appear to be installed.
    """
    if not venv_exists():
        return False
    site_packages = get_venv_site_packages()
    if site_packages is None or not os.path.isdir(site_packages):
        return False
    has_ee = os.path.isdir(os.path.join(site_packages, "ee"))
    has_pil = os.path.isdir(os.path.join(site_packages, "PIL"))
    has_numpy = os.path.isdir(os.path.join(site_packages, "numpy"))
    return has_ee and has_pil and has_numpy


def create_venv(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Create the virtual environment at VENV_DIR.

    Args:
        progress_callback: Optional callable(str) for status messages.

    Returns:
        True on success.

    Raises:
        RuntimeError: If venv creation fails.
    """
    if venv_exists():
        if progress_callback:
            progress_callback("Virtual environment already exists.")
        _log("Virtual environment already exists")
        return True

    python_path = _get_system_python()
    _log(f"Using Python: {python_path}")

    if progress_callback:
        progress_callback(f"Creating virtual environment at {VENV_DIR}...")

    env = _get_clean_env_for_venv()
    sp_kwargs = _get_subprocess_kwargs()

    try:
        result = subprocess.run(
            [python_path, "-m", "venv", VENV_DIR],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            **sp_kwargs,
        )
    except subprocess.TimeoutExpired:
        _cleanup_partial_venv()
        raise RuntimeError("Virtual environment creation timed out.")
    except FileNotFoundError:
        raise RuntimeError(f"Python executable not found: {python_path}")

    if result.returncode != 0:
        error_msg = result.stderr or result.stdout or f"Return code {result.returncode}"
        _cleanup_partial_venv()
        raise RuntimeError(f"Failed to create virtual environment:\n{error_msg}")

    _log("Virtual environment created successfully")

    # Ensure pip is available
    pip_path = get_venv_pip_path()
    if not os.path.isfile(pip_path):
        if progress_callback:
            progress_callback("Bootstrapping pip...")
        _log("pip not found in venv, bootstrapping with ensurepip...")
        venv_python = get_venv_python_path()
        try:
            ensurepip_result = subprocess.run(
                [venv_python, "-m", "ensurepip", "--upgrade"],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                **sp_kwargs,
            )
        except Exception as e:
            _cleanup_partial_venv()
            raise RuntimeError(f"Failed to bootstrap pip: {e}")

        if ensurepip_result.returncode != 0:
            err = ensurepip_result.stderr or ensurepip_result.stdout
            _cleanup_partial_venv()
            raise RuntimeError(f"Failed to bootstrap pip:\n{err}")
        _log("pip bootstrapped via ensurepip")

    if progress_callback:
        progress_callback("Virtual environment created.")
    return True


def install_dependencies(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Install required packages into the virtual environment via pip.

    Args:
        progress_callback: Optional callable(str) for status messages.

    Returns:
        True on success.

    Raises:
        RuntimeError: If pip install fails.
    """
    venv_python = get_venv_python_path()
    if not os.path.isfile(venv_python):
        raise RuntimeError(
            f"Venv Python not found at {venv_python}. "
            "Please recreate the virtual environment."
        )

    env = _get_clean_env_for_venv()
    sp_kwargs = _get_subprocess_kwargs()

    # Upgrade pip first
    if progress_callback:
        progress_callback("Upgrading pip...")
    _log("Upgrading pip...")
    try:
        subprocess.run(
            [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            **sp_kwargs,
        )
    except Exception:
        _log("pip upgrade failed, continuing with existing version", level=1)

    # Install packages
    pkg_names = ", ".join(REQUIRED_PACKAGES)
    if progress_callback:
        progress_callback(f"Installing packages: {pkg_names}...")
    _log(f"Installing packages: {pkg_names}")

    try:
        result = subprocess.run(
            [venv_python, "-m", "pip", "install"] + REQUIRED_PACKAGES,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
            **sp_kwargs,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "Package installation timed out after 10 minutes. "
            "Please check your internet connection and try again."
        )

    if result.returncode != 0:
        error_msg = result.stderr or result.stdout or f"Return code {result.returncode}"
        raise RuntimeError(f"Failed to install dependencies:\n{error_msg}")

    if progress_callback:
        progress_callback("All packages installed successfully.")
    _log("Dependencies installed successfully")
    return True


def ensure_venv_packages_available() -> bool:
    """Add the venv's site-packages to sys.path if not already present.

    This makes ``import ee`` and ``from PIL import ...`` resolve from the
    venv. Must be called before importing timelapse_core or after reloading it.

    Returns:
        True if site-packages was added or was already present.
    """
    site_packages = get_venv_site_packages()
    if site_packages is None:
        _log("Cannot find venv site-packages", level=1)
        return False
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
        _log(f"Added venv site-packages to sys.path: {site_packages}")
    return True


def _cleanup_partial_venv() -> None:
    """Remove a partially-created venv directory to prevent broken state."""
    if os.path.exists(VENV_DIR):
        try:
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            _log(f"Cleaned up partial venv: {VENV_DIR}")
        except Exception:
            _log(f"Could not clean up partial venv: {VENV_DIR}", level=1)
