"""
Virtual Environment Manager for Timelapse Plugin.

Creates and manages an isolated virtual environment for installing
the plugin's Python dependencies (earthengine-api, numpy, Pillow) without
modifying QGIS's built-in Python environment.
"""

import importlib
import importlib.metadata
import os
import platform
import re
import shutil
import subprocess  # nosec B404 (validated list-form calls only; commands are pinned, not user input)
import sys
import time
from typing import Callable, Optional, Tuple

from qgis.core import QgsMessageLog, Qgis

CACHE_DIR = os.path.expanduser("~/.qgis_timelapse")
VENV_DIR = os.path.join(CACHE_DIR, "venv")

REQUIRED_PACKAGES = [
    ("earthengine-api", ""),
    ("numpy", ""),
    ("Pillow", ""),
    ("google-auth-oauthlib", ""),
]

PACKAGE_IMPORT_DIRS = {
    "earthengine-api": ("ee",),
    "Pillow": ("PIL",),
    "google-auth-oauthlib": ("google_auth_oauthlib",),
}


def _log(message, level=Qgis.MessageLevel.Info):
    """Log a message to the QGIS message log.

    Args:
        message: The message to log.
        level: The log level (Qgis.MessageLevel.Info, Qgis.MessageLevel.Warning, Qgis.MessageLevel.Critical).
    """
    QgsMessageLog.logMessage(str(message), "Timelapse", level=level)


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _get_clean_env_for_venv():
    """Create a clean environment dict for subprocess calls.

    Strips QGIS-specific variables that would interfere with the
    standalone Python or venv operations.

    Returns:
        A dict of environment variables.
    """
    env = os.environ.copy()

    vars_to_remove = [
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
        # SSL/CA certificate variables -- QGIS may set these to
        # QGIS-internal paths that do not exist outside QGIS.
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    ]
    for key in vars_to_remove:
        env.pop(key, None)

    env["PYTHONIOENCODING"] = "utf-8"

    return env


def _get_subprocess_kwargs():
    """Get platform-specific subprocess keyword arguments.

    Returns:
        Dict of kwargs to pass to subprocess.run/Popen.
    """
    kwargs = {}
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _strip_stderr_warnings(stderr):
    """Remove known non-fatal warning lines from stderr.

    Some tools (e.g., uv) emit warnings to stderr that are not actual errors.
    Stripping these ensures the real error message is visible when stderr is
    truncated for display.

    Args:
        stderr: Raw stderr string from a subprocess.

    Returns:
        The stderr string with known warning lines removed.
    """
    if not stderr:
        return stderr
    warning_prefixes = (
        "warning: Ignoring invalid",
        "warning: Failed to query",
    )
    lines = stderr.splitlines()
    filtered = [
        line
        for line in lines
        if not any(line.strip().startswith(prefix) for prefix in warning_prefixes)
    ]
    return "\n".join(filtered).strip()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_venv_python_path(venv_dir=None):
    """Get the path to the Python binary inside the venv.

    Args:
        venv_dir: Optional venv directory path. Defaults to VENV_DIR.

    Returns:
        The absolute path to the venv Python executable.
    """
    if venv_dir is None:
        venv_dir = VENV_DIR
    if platform.system() == "Windows":
        primary = os.path.join(venv_dir, "Scripts", "python.exe")
        if os.path.isfile(primary):
            return primary
        fallback = os.path.join(venv_dir, "Scripts", "python3.exe")
        if os.path.isfile(fallback):
            return fallback
        return primary  # Return expected path even if missing
    path = os.path.join(venv_dir, "bin", "python3")
    if os.path.isfile(path):
        return path
    return os.path.join(venv_dir, "bin", "python")


def get_venv_pip_path(venv_dir=None):
    """Get the path to pip inside the venv.

    Args:
        venv_dir: Optional venv directory path. Defaults to VENV_DIR.

    Returns:
        The absolute path to the venv pip executable.
    """
    if venv_dir is None:
        venv_dir = VENV_DIR
    if platform.system() == "Windows":
        return os.path.join(venv_dir, "Scripts", "pip.exe")
    return os.path.join(venv_dir, "bin", "pip")


def get_venv_site_packages(venv_dir=None):
    """Get the path to the site-packages directory inside the venv.

    Args:
        venv_dir: Optional venv directory path. Defaults to VENV_DIR.

    Returns:
        The path to the venv site-packages directory, or None if not found.
    """
    if venv_dir is None:
        venv_dir = VENV_DIR

    if platform.system() == "Windows":
        sp = os.path.join(venv_dir, "Lib", "site-packages")
        return sp if os.path.isdir(sp) else None

    # On Unix, detect the actual Python version directory in the venv
    lib_dir = os.path.join(venv_dir, "lib")
    if not os.path.isdir(lib_dir):
        return None
    for entry in sorted(os.listdir(lib_dir), reverse=True):
        if entry.startswith("python"):
            sp = os.path.join(lib_dir, entry, "site-packages")
            if os.path.isdir(sp):
                return sp
    return None


def venv_exists(venv_dir=None):
    """Check if the virtual environment exists.

    Args:
        venv_dir: Optional venv directory path. Defaults to VENV_DIR.

    Returns:
        True if the venv Python executable exists.
    """
    return os.path.exists(get_venv_python_path(venv_dir))


def _normalize_distribution_name(name):
    """Normalize a Python distribution name for case-insensitive comparison."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _get_installed_version_from_site_packages(package_name, site_packages):
    """Return an installed distribution version from a specific site-packages path."""
    normalized_name = _normalize_distribution_name(package_name)
    for distribution in importlib.metadata.distributions(path=[site_packages]):
        distribution_name = distribution.metadata.get("Name")
        if (
            distribution_name
            and _normalize_distribution_name(distribution_name) == normalized_name
        ):
            return distribution.version
    return None


def _package_exists_in_site_packages(package_name, site_packages):
    """Check whether a package appears to be installed in site-packages.

    Prefer distribution metadata. Fall back to import package directories for
    packages whose distribution name differs from their import name, such as
    Pillow -> PIL.
    """
    if _get_installed_version_from_site_packages(package_name, site_packages):
        return True

    import_dirs = PACKAGE_IMPORT_DIRS.get(
        package_name, (package_name.replace("-", "_"),)
    )
    for import_dir in import_dirs:
        if os.path.exists(os.path.join(site_packages, import_dir)):
            return True

    normalized_name = _normalize_distribution_name(package_name)
    try:
        entries = os.listdir(site_packages)
    except OSError:
        return False

    return any(
        entry.endswith((".dist-info", ".egg-info"))
        and _normalize_distribution_name(entry.rsplit(".", 1)[0]).startswith(
            f"{normalized_name}-"
        )
        for entry in entries
    )


# ---------------------------------------------------------------------------
# System Python resolution
# ---------------------------------------------------------------------------


def _is_python_executable_name(path: str) -> bool:
    """Return True when a path name looks like a Python interpreter."""
    name = os.path.basename(path).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name in ("python", "python3"):
        return True
    if not name.startswith("python"):
        return False
    suffix = name[6:]
    if "-" in suffix:
        return False
    return suffix.isdigit() or (
        suffix.count(".") == 1 and all(part.isdigit() for part in suffix.split("."))
    )


def _python_candidate_matches_runtime(path: str) -> bool:
    """Return True when a candidate is executable and matches QGIS Python."""
    if not path or not os.path.isfile(path) or not _is_python_executable_name(path):
        return False
    try:
        result = subprocess.run(  # nosec B603
            [
                path,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=_get_clean_env_for_venv(),
            **_get_subprocess_kwargs(),
        )
    except Exception:
        return False
    runtime_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return result.returncode == 0 and result.stdout.strip() == runtime_version


def _contents_dir_from_path(path: str) -> Optional[str]:
    """Return the containing macOS app Contents directory for a path."""
    if not path:
        return None
    current = path if os.path.isdir(path) else os.path.dirname(path)
    for _ in range(8):
        if os.path.basename(current) == "Contents":
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _candidate_python_paths():
    """Return possible Python interpreter paths for QGIS-bundled Python."""
    candidates = []
    exe_dir = os.path.dirname(sys.executable)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    names = (f"python{py_ver}", f"python{sys.version_info.major}", "python3", "python")

    for attr in ("_base_executable", "executable"):
        value = getattr(sys, attr, None)
        if value:
            candidates.append(value)

    for attr in ("_base_prefix", "base_prefix", "prefix", "exec_prefix"):
        prefix = getattr(sys, attr, None)
        if not prefix:
            continue
        candidates.extend([os.path.join(prefix, "python.exe")])
        candidates.extend(os.path.join(prefix, "bin", name) for name in names)
        candidates.extend(
            [
                os.path.join(prefix, "Versions", py_ver, "bin", "python3"),
                os.path.join(prefix, "Versions", "Current", "bin", "python3"),
            ]
        )

    candidates.extend(os.path.join(exe_dir, name) for name in names)
    candidates.extend(
        [os.path.join(exe_dir, "python.exe"), os.path.join(exe_dir, "python3.exe")]
    )

    apps_dir = os.path.join(os.path.dirname(exe_dir), "apps")
    if os.path.isdir(apps_dir):
        for entry in sorted(os.listdir(apps_dir), reverse=True):
            if entry.lower().startswith("python"):
                candidates.append(os.path.join(apps_dir, entry, "python.exe"))

    for root in [sys.executable, getattr(sys, "_base_executable", None), sys.prefix]:
        contents_dir = _contents_dir_from_path(root)
        if not contents_dir:
            continue
        candidates.extend(os.path.join(contents_dir, "MacOS", name) for name in names)
        candidates.extend(
            os.path.join(contents_dir, "MacOS", "bin", name) for name in names
        )
        candidates.extend(
            [
                os.path.join(
                    contents_dir,
                    "Frameworks",
                    "Python.framework",
                    "Versions",
                    py_ver,
                    "bin",
                    "python3",
                ),
                os.path.join(
                    contents_dir,
                    "Frameworks",
                    "Python.framework",
                    "Versions",
                    "Current",
                    "bin",
                    "python3",
                ),
                os.path.join(contents_dir, "Resources", "python", "bin", "python3"),
                os.path.join(
                    contents_dir,
                    "Resources",
                    "Python.app",
                    "Contents",
                    "MacOS",
                    "Python",
                ),
            ]
        )

    unique = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def _find_python_executable():
    """Find a real Python executable for venv creation."""
    candidates = _candidate_python_paths()
    for candidate in candidates:
        if _python_candidate_matches_runtime(candidate):
            return candidate

    candidates_text = "\n".join(f"  - {path}" for path in candidates)
    raise RuntimeError(
        "Could not find a Python executable matching the QGIS Python runtime.\n"
        f"QGIS sys.executable: {sys.executable}\n"
        f"Python version: {sys.version_info.major}.{sys.version_info.minor}\n"
        "Checked candidates:\n"
        f"{candidates_text or '  - none'}"
    )


def _get_system_python():
    """Get the path to the Python executable for creating venvs.

    Uses the standalone Python downloaded by python_manager if available.
    On Windows, falls back to QGIS's bundled Python using multi-strategy
    detection.

    Returns:
        The path to a usable Python executable.

    Raises:
        RuntimeError: If no usable Python is found.
    """
    from .python_manager import standalone_python_exists, get_standalone_python_path

    if standalone_python_exists():
        python_path = get_standalone_python_path()
        _log(f"Using standalone Python: {python_path}")
        return python_path

    # Fallback: find QGIS's bundled Python
    python_path = _find_python_executable()
    if python_path and os.path.isfile(python_path):
        _log(
            f"Standalone Python unavailable, using system Python: {python_path}",
            Qgis.MessageLevel.Warning,
        )
        return python_path

    raise RuntimeError(
        "Python standalone not installed. "
        "Please click 'Install Dependencies' to download Python automatically."
    )


# ---------------------------------------------------------------------------
# Venv creation
# ---------------------------------------------------------------------------


def _cleanup_partial_venv(venv_dir):
    """Remove a partially-created venv directory.

    Args:
        venv_dir: The venv directory to remove.
    """
    if os.path.exists(venv_dir):
        try:
            shutil.rmtree(venv_dir, ignore_errors=True)
            _log(f"Cleaned up partial venv: {venv_dir}")
        except Exception:
            _log(
                f"Could not clean up partial venv: {venv_dir}",
                Qgis.MessageLevel.Warning,
            )


def create_venv(venv_dir=None, progress_callback=None):
    """Create a virtual environment using uv (preferred) or stdlib venv.

    Args:
        venv_dir: Optional venv directory path. Defaults to VENV_DIR.
        progress_callback: Function called with (percent, message).

    Returns:
        A tuple of (success: bool, message: str).
    """
    if venv_dir is None:
        venv_dir = VENV_DIR

    _log(f"Creating virtual environment at: {venv_dir}")

    if progress_callback:
        progress_callback(10, "Creating virtual environment...")

    system_python = _get_system_python()
    _log(f"Using Python: {system_python}")

    from .uv_manager import uv_exists, get_uv_path

    use_uv = uv_exists()

    if use_uv:
        uv_path = get_uv_path()
        cmd = [uv_path, "venv", "--python", system_python, venv_dir]
        _log("Creating venv with uv")
    else:
        cmd = [system_python, "-m", "venv", venv_dir]
        _log("Creating venv with stdlib venv")

    try:
        env = _get_clean_env_for_venv()
        kwargs = _get_subprocess_kwargs()

        os.makedirs(os.path.dirname(venv_dir), exist_ok=True)

        result = subprocess.run(  # nosec B603 (cmd is built from validated python path + fixed venv args)
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            **kwargs,
        )

        if result.returncode == 0:
            _log("Virtual environment created successfully", Qgis.MessageLevel.Success)

            # When using stdlib venv, ensure pip is available
            if not use_uv:
                pip_path = get_venv_pip_path(venv_dir)
                if not os.path.exists(pip_path):
                    _log("pip not found in venv, bootstrapping with ensurepip...")
                    python_in_venv = get_venv_python_path(venv_dir)
                    ensurepip_cmd = [
                        python_in_venv,
                        "-m",
                        "ensurepip",
                        "--upgrade",
                    ]
                    try:
                        ensurepip_result = subprocess.run(  # nosec B603 (list-form, fixed ensurepip args)
                            ensurepip_cmd,
                            capture_output=True,
                            text=True,
                            timeout=120,
                            env=env,
                            **kwargs,
                        )
                        if ensurepip_result.returncode == 0:
                            _log(
                                "pip bootstrapped via ensurepip",
                                Qgis.MessageLevel.Success,
                            )
                        else:
                            err = ensurepip_result.stderr or ensurepip_result.stdout
                            _log(
                                f"ensurepip failed: {err[:200]}",
                                Qgis.MessageLevel.Warning,
                            )
                            _cleanup_partial_venv(venv_dir)
                            user_err = _strip_stderr_warnings(err) or err
                            return False, f"Failed to bootstrap pip: {user_err[:300]}"
                    except Exception as e:
                        _log(f"ensurepip exception: {e}", Qgis.MessageLevel.Warning)
                        _cleanup_partial_venv(venv_dir)
                        return False, f"Failed to bootstrap pip: {str(e)[:200]}"

            if progress_callback:
                progress_callback(20, "Virtual environment created")
            return True, "Virtual environment created"
        else:
            error_msg = (
                result.stderr or result.stdout or f"Return code {result.returncode}"
            )
            _log(f"Failed to create venv: {error_msg}", Qgis.MessageLevel.Critical)
            _cleanup_partial_venv(venv_dir)
            user_msg = _strip_stderr_warnings(error_msg) or error_msg
            return False, f"Failed to create venv: {user_msg[:300]}"

    except subprocess.TimeoutExpired:
        _log("Virtual environment creation timed out", Qgis.MessageLevel.Critical)
        _cleanup_partial_venv(venv_dir)
        return False, "Virtual environment creation timed out"
    except FileNotFoundError:
        _log(
            f"Python executable not found: {system_python}", Qgis.MessageLevel.Critical
        )
        return False, f"Python not found: {system_python}"
    except Exception as e:
        _log(f"Exception during venv creation: {str(e)}", Qgis.MessageLevel.Critical)
        _cleanup_partial_venv(venv_dir)
        return False, f"Error: {str(e)[:200]}"


# ---------------------------------------------------------------------------
# Package installation
# ---------------------------------------------------------------------------


def _is_ssl_error(stderr):
    """Check if a pip error is SSL-related.

    Args:
        stderr: The stderr output from pip.

    Returns:
        True if the error is SSL-related.
    """
    ssl_markers = ["ssl", "certificate", "CERTIFICATE_VERIFY_FAILED"]
    lower = stderr.lower()
    return any(m.lower() in lower for m in ssl_markers)


def _is_network_error(stderr):
    """Check if a pip error is network-related.

    Args:
        stderr: The stderr output from pip.

    Returns:
        True if the error is network-related.
    """
    network_markers = [
        "ConnectionError",
        "connection refused",
        "connection reset",
        "timed out",
        "RemoteDisconnected",
        "NewConnectionError",
    ]
    return any(m.lower() in stderr.lower() for m in network_markers)


def install_dependencies(venv_dir=None, progress_callback=None, cancel_check=None):
    """Install required packages into the virtual environment.

    Uses uv when available for significantly faster installation,
    falling back to pip otherwise.

    Args:
        venv_dir: Optional venv directory path. Defaults to VENV_DIR.
        progress_callback: Function called with (percent, message).
        cancel_check: Function that returns True if operation should be cancelled.

    Returns:
        A tuple of (success: bool, message: str).
    """
    if venv_dir is None:
        venv_dir = VENV_DIR

    python_path = get_venv_python_path(venv_dir)
    if not os.path.exists(python_path):
        return False, "Virtual environment Python not found"

    env = _get_clean_env_for_venv()
    kwargs = _get_subprocess_kwargs()

    from .uv_manager import uv_exists, get_uv_path

    use_uv = uv_exists()
    if use_uv:
        uv_path = get_uv_path()
        _log("Installing dependencies with uv")
    else:
        _log("Installing dependencies with pip")

    # Build the full list of package specs for batch installation
    pkg_specs = []
    pkg_names = []
    for package_name, version_spec in REQUIRED_PACKAGES:
        pkg_spec = f"{package_name}{version_spec}" if version_spec else package_name
        pkg_specs.append(pkg_spec)
        pkg_names.append(package_name)

    if cancel_check and cancel_check():
        return False, "Installation cancelled."

    # Scale timeout with number of packages (600s per package)
    total = len(REQUIRED_PACKAGES)
    timeout = 600 * total

    if progress_callback:
        progress_callback(20, f"Installing {', '.join(pkg_names)}...")

    if use_uv:
        cmd = [
            uv_path,
            "pip",
            "install",
            "--python",
            python_path,
            "--upgrade",
        ] + pkg_specs
        success, error_msg = _run_install(
            cmd,
            env,
            kwargs,
            timeout=timeout,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            installer="uv",
        )
    else:
        cmd = [
            python_path,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--prefer-binary",
            "--disable-pip-version-check",
            "--no-warn-script-location",
        ] + pkg_specs
        success, error_msg = _run_install(
            cmd,
            env,
            kwargs,
            timeout=timeout,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            installer="pip",
        )

    if not success:
        return False, error_msg

    _log(f"Installed {total} package(s)", Qgis.MessageLevel.Success)

    if progress_callback:
        progress_callback(90, "All packages installed")

    return True, f"Successfully installed {total} package(s)"


def _run_install_subprocess(
    cmd, env, kwargs, timeout, progress_callback=None, cancel_check=None
):
    """Run an install command with progress polling and cancellation support.

    Args:
        cmd: The command list to execute.
        env: Environment dict for the subprocess.
        kwargs: Additional subprocess kwargs.
        timeout: Timeout in seconds.
        progress_callback: Optional callback for progress updates (percent, msg).
        cancel_check: Optional function that returns True to cancel.

    Returns:
        A tuple of (returncode: int, stdout: str, stderr: str).
            returncode is -1 if cancelled, -2 if timed out.
    """
    proc = subprocess.Popen(  # nosec B603 (cmd is list-form, no shell, args validated upstream)
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        **kwargs,
    )
    start = time.time()
    poll_interval = 2  # seconds
    # Progress ticks from 25% to 85% over the timeout period
    while True:
        try:
            proc.wait(timeout=poll_interval)
            # Process finished
            break
        except subprocess.TimeoutExpired:
            pass

        # Check cancellation
        if cancel_check and cancel_check():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            return -1, "", "Installation cancelled by user."

        # Check overall timeout
        elapsed = time.time() - start
        if elapsed >= timeout:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            return -2, "", f"Timed out after {timeout // 60} minutes."

        # Emit intermediate progress (25-85% range based on elapsed time)
        if progress_callback:
            fraction = min(elapsed / timeout, 1.0)
            percent = int(25 + fraction * 60)
            progress_callback(percent, "Installing packages...")

    stdout = proc.stdout.read() if proc.stdout else ""
    stderr = proc.stderr.read() if proc.stderr else ""
    return proc.returncode, stdout, stderr


def _run_install(
    cmd,
    env,
    kwargs,
    timeout=600,
    progress_callback=None,
    cancel_check=None,
    installer="pip",
):
    """Run a pip/uv install command with retry logic.

    Args:
        cmd: The command list to execute.
        env: Environment dict for the subprocess.
        kwargs: Additional subprocess kwargs.
        timeout: Timeout in seconds.
        progress_callback: Optional callback for progress updates (percent, msg).
        cancel_check: Optional function that returns True to cancel.
        installer: "pip" or "uv", used for retry flags and logging.

    Returns:
        A tuple of (success: bool, error_message: str).
    """
    try:
        returncode, stdout, stderr = _run_install_subprocess(
            cmd,
            env,
            kwargs,
            timeout,
            progress_callback,
            cancel_check,
        )

        if returncode == -1:
            return False, "Installation cancelled."
        if returncode == -2:
            return False, f"Installation timed out after {timeout // 60} minutes."
        if returncode == 0:
            return True, ""

        stderr = stderr or stdout or ""

        # Retry on SSL errors
        if _is_ssl_error(stderr):
            if installer == "uv":
                ssl_flags = [
                    "--allow-insecure-host",
                    "pypi.org",
                    "--allow-insecure-host",
                    "files.pythonhosted.org",
                ]
            else:
                ssl_flags = [
                    "--trusted-host",
                    "pypi.org",
                    "--trusted-host",
                    "files.pythonhosted.org",
                ]
            _log(
                f"SSL error installing dependencies via {installer}, "
                f"retrying with trusted hosts",
                Qgis.MessageLevel.Warning,
            )
            retry_cmd = cmd + ssl_flags
            returncode, stdout, retry_stderr = _run_install_subprocess(
                retry_cmd,
                env,
                kwargs,
                timeout,
                progress_callback,
                cancel_check,
            )
            if returncode == -1:
                return False, "Installation cancelled."
            if returncode == 0:
                return True, ""
            stderr = retry_stderr or stderr

        # Retry on network errors with a delay
        if _is_network_error(stderr):
            _log(
                f"Network error installing dependencies via {installer}, "
                f"retrying in 5s...",
                Qgis.MessageLevel.Warning,
            )
            time.sleep(5)
            returncode, stdout, retry_stderr = _run_install_subprocess(
                cmd,
                env,
                kwargs,
                timeout,
                progress_callback,
                cancel_check,
            )
            if returncode == -1:
                return False, "Installation cancelled."
            if returncode == 0:
                return True, ""
            stderr = retry_stderr or stderr

        # Classify the error for a user-friendly message
        return False, _classify_pip_error(stderr)

    except FileNotFoundError:
        if installer == "uv":
            return False, "uv executable not found."
        return False, "Python executable not found in virtual environment."
    except Exception as e:
        return False, f"Unexpected error installing dependencies: {str(e)}"


def _classify_pip_error(stderr):
    """Classify a pip/uv error into a user-friendly message.

    Args:
        stderr: The stderr output from pip/uv.

    Returns:
        A user-friendly error message string.
    """
    stderr_lower = stderr.lower()

    if "no matching distribution" in stderr_lower:
        return (
            "A required package was not found. "
            "Check your internet connection and try again."
        )
    if "permission" in stderr_lower or "denied" in stderr_lower:
        return (
            "Permission denied installing dependencies. "
            "Try running QGIS as administrator."
        )
    if "no space left" in stderr_lower:
        return "Not enough disk space to install dependencies."

    return f"Failed to install dependencies: {stderr[:300]}"


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _get_verification_code(package_name):
    """Get functional test code for a package.

    Args:
        package_name: The package to generate test code for.

    Returns:
        A Python code string that tests the package.
    """
    if package_name == "earthengine-api":
        return "import ee; print(ee.__version__)"
    elif package_name == "numpy":
        return "import numpy; print(numpy.__version__)"
    elif package_name == "Pillow":
        return "from PIL import Image; print(Image.__version__)"
    elif package_name == "google-auth-oauthlib":
        return "import google_auth_oauthlib; print('ok')"
    else:
        import_name = package_name.replace("-", "_")
        return f"import {import_name}"


def verify_venv(venv_dir=None, progress_callback=None):
    """Verify that all required packages work in the venv.

    Runs functional test code for each package in a subprocess to
    verify the venv is properly set up.

    Args:
        venv_dir: Optional venv directory path. Defaults to VENV_DIR.
        progress_callback: Function called with (percent, message).

    Returns:
        A tuple of (success: bool, message: str).
    """
    if venv_dir is None:
        venv_dir = VENV_DIR

    if not venv_exists(venv_dir):
        return False, "Virtual environment not found"

    python_path = get_venv_python_path(venv_dir)
    env = _get_clean_env_for_venv()
    kwargs = _get_subprocess_kwargs()

    total = len(REQUIRED_PACKAGES)
    for i, (package_name, _) in enumerate(REQUIRED_PACKAGES):
        if progress_callback:
            percent = int((i / total) * 100)
            progress_callback(percent, f"Verifying {package_name}... ({i + 1}/{total})")

        verify_code = _get_verification_code(package_name)
        cmd = [python_path, "-c", verify_code]

        try:
            result = subprocess.run(  # nosec B603 (list-form; verify_code is internal-controlled)
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                **kwargs,
            )

            if result.returncode != 0:
                error_detail = (
                    result.stderr[:300] if result.stderr else result.stdout[:300]
                )
                _log(
                    f"Package {package_name} verification failed: {error_detail}",
                    Qgis.MessageLevel.Warning,
                )
                return False, (
                    f"Package {package_name} is broken: {error_detail[:200]}"
                )

        except subprocess.TimeoutExpired:
            _log(f"Verification of {package_name} timed out", Qgis.MessageLevel.Warning)
            return False, f"Verification of {package_name} timed out"
        except Exception as e:
            _log(
                f"Failed to verify {package_name}: {str(e)}", Qgis.MessageLevel.Warning
            )
            return False, f"Verification error: {package_name}"

    if progress_callback:
        progress_callback(100, "Verification complete")

    _log("Virtual environment verified successfully", Qgis.MessageLevel.Success)
    return True, "Virtual environment ready"


# ---------------------------------------------------------------------------
# Runtime integration
# ---------------------------------------------------------------------------


def ensure_venv_packages_available():
    """Make venv packages importable by adding site-packages to sys.path.

    This should be called before importing any venv-installed packages
    (ee, geemap, etc.). Safe to call multiple times.

    Returns:
        True if venv packages are available, False otherwise.
    """
    if not venv_exists():
        python_path = get_venv_python_path()
        _log(
            f"Venv does not exist: expected Python at {python_path}",
            Qgis.MessageLevel.Warning,
        )
        return False

    site_packages = get_venv_site_packages()
    if site_packages is None:
        _log(f"Venv site-packages not found in: {VENV_DIR}", Qgis.MessageLevel.Warning)
        return False

    path_was_missing = site_packages not in sys.path
    if path_was_missing:
        # Append (not insert at 0) so QGIS's built-in packages (numpy,
        # etc.) keep priority.  Venv-only packages (ee) are still
        # found because QGIS doesn't ship them.
        sys.path.append(site_packages)
        _log(f"Added venv site-packages to sys.path: {site_packages}")

        # Re-import ee into modules that cached ``ee = None`` at startup
        _refresh_ee_in_modules()

    return True


def _refresh_ee_in_modules():
    """Re-import the ``ee`` module into plugin modules that cached it as None.

    Several plugin modules use a top-level ``try: import ee / except: ee = None``
    pattern.  If the venv site-packages path was not yet on ``sys.path`` when
    those modules were first imported, their module-level ``ee`` stays ``None``
    even after the path is added.  This function performs a fresh import and
    patches the reference in every affected module.
    """
    try:
        import ee  # noqa: F811 — intentional re-import
    except ImportError:
        return  # ee not installable yet; nothing to patch

    # Modules that cache ``ee`` at module level.
    _module_names = [
        "timelapse.core.timelapse_core",
        "timelapse.dialogs.timelapse_dock",
        "timelapse.dialogs.settings_dock",
    ]
    for name in _module_names:
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, "ee", None) is None:
            mod.ee = ee
            _log(f"Refreshed 'ee' reference in {name}")


# ---------------------------------------------------------------------------
# Status checking
# ---------------------------------------------------------------------------


def get_venv_status():
    """Get the status of the virtual environment installation.

    Returns:
        A tuple of (is_ready: bool, message: str).
    """
    from .python_manager import standalone_python_exists

    if not standalone_python_exists():
        return False, "Dependencies not installed"

    if not venv_exists():
        return False, "Virtual environment not configured"

    site_packages = get_venv_site_packages()
    if site_packages is None:
        return False, "Virtual environment incomplete"

    for package_name, _ in REQUIRED_PACKAGES:
        if not _package_exists_in_site_packages(package_name, site_packages):
            return False, f"Package {package_name} not found in venv"

    return True, "Virtual environment ready"


def check_dependencies():
    """Check if all required packages are installed and importable.

    Reads package metadata from the plugin venv site-packages path. This is a
    lightweight check suitable for UI display.

    Returns:
        A tuple of (all_ok, missing, installed) where:
            all_ok: True if all required packages are installed.
            missing: List of (package_name, version_spec) for missing packages.
            installed: List of (package_name, version_string) for installed packages.
    """
    site_packages = get_venv_site_packages()
    if site_packages is None:
        return False, REQUIRED_PACKAGES.copy(), []

    ensure_venv_packages_available()

    missing = []
    installed = []

    for package_name, version_spec in REQUIRED_PACKAGES:
        version = _get_installed_version_from_site_packages(package_name, site_packages)
        if version:
            installed.append((package_name, version))
        elif _package_exists_in_site_packages(package_name, site_packages):
            installed.append((package_name, "unknown"))
        else:
            missing.append((package_name, version_spec))

    all_ok = len(missing) == 0
    return all_ok, missing, installed


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def create_venv_and_install(progress_callback=None, cancel_check=None):
    """Complete installation: download Python + download uv + create venv + install.

    Progress breakdown:
        0-35%: Download Python standalone
        35-40%: Download uv package installer
        40-50%: Create virtual environment
        50-90%: Install packages
        90-100%: Verify installation

    Args:
        progress_callback: Function called with (percent, message).
        cancel_check: Function that returns True if operation should be cancelled.

    Returns:
        A tuple of (success: bool, message: str).
    """
    from .python_manager import (
        standalone_python_exists,
        download_python_standalone,
    )
    from .uv_manager import uv_exists, download_uv

    start_time = time.time()

    # Step 1: Download Python standalone if needed (0-35%)
    if not standalone_python_exists():
        _log("Downloading Python standalone...")

        def python_progress(percent, msg):
            if progress_callback:
                progress_callback(int(percent * 0.35), msg)

        success, msg = download_python_standalone(
            progress_callback=python_progress,
            cancel_check=cancel_check,
        )

        if not success:
            # Fallback: use QGIS's bundled Python
            fallback = _find_python_executable()
            if fallback and os.path.isfile(fallback):
                _log(
                    f"Standalone download failed, using system Python: {fallback}",
                    Qgis.MessageLevel.Warning,
                )
            else:
                return False, f"Failed to download Python: {msg}"

        if cancel_check and cancel_check():
            return False, "Installation cancelled"
    else:
        _log("Python standalone already installed")
        if progress_callback:
            progress_callback(35, "Python standalone ready")

    # Step 1b: Download uv package installer if needed (35-40%)
    if not uv_exists():
        _log("Downloading uv package installer...")

        def uv_progress(percent, msg):
            if progress_callback:
                progress_callback(35 + int(percent * 0.05), msg)

        success, msg = download_uv(
            progress_callback=uv_progress,
            cancel_check=cancel_check,
        )

        if not success:
            # Non-fatal: fall back to pip for venv creation and installation
            _log(
                f"uv download failed ({msg}), will use pip instead",
                Qgis.MessageLevel.Warning,
            )
        else:
            _log("uv package installer ready")

        if cancel_check and cancel_check():
            return False, "Installation cancelled"
    else:
        _log("uv already installed")
        if progress_callback:
            progress_callback(40, "uv ready")

    # Step 2: Create venv if needed (40-50%)
    if venv_exists():
        _log("Virtual environment already exists")
        if progress_callback:
            progress_callback(50, "Virtual environment ready")
    else:

        def venv_progress(percent, msg):
            if progress_callback:
                progress_callback(40 + int(percent * 0.10), msg)

        success, msg = create_venv(progress_callback=venv_progress)
        if not success:
            return False, msg

        if cancel_check and cancel_check():
            return False, "Installation cancelled"

    # Step 3: Install dependencies (50-90%)
    def deps_progress(percent, msg):
        if progress_callback:
            # Map 20-90 range from install_dependencies to 50-90
            mapped = 50 + int((percent - 20) * (40.0 / 70.0))
            progress_callback(min(mapped, 90), msg)

    success, msg = install_dependencies(
        progress_callback=deps_progress,
        cancel_check=cancel_check,
    )

    if not success:
        return False, msg

    # Step 4: Verify installation (90-100%)
    def verify_progress(percent, msg):
        if progress_callback:
            mapped = 90 + int(percent * 0.10)
            progress_callback(min(mapped, 99), msg)

    is_valid, verify_msg = verify_venv(progress_callback=verify_progress)

    if not is_valid:
        return False, f"Verification failed: {verify_msg}"

    elapsed = time.time() - start_time
    if elapsed >= 60:
        minutes, seconds = divmod(int(elapsed), 60)
        elapsed_str = f"{minutes}:{seconds:02d}"
    else:
        elapsed_str = f"{elapsed:.1f}s"

    if progress_callback:
        progress_callback(100, f"All dependencies installed in {elapsed_str}")

    _log(
        f"All dependencies installed and verified in {elapsed_str}",
        Qgis.MessageLevel.Success,
    )
    return True, f"All dependencies installed successfully in {elapsed_str}"


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def remove_venv(venv_dir=None):
    """Remove the virtual environment directory.

    Args:
        venv_dir: Path to the virtual environment. Defaults to VENV_DIR.

    Returns:
        A tuple of (success, message).
    """
    if venv_dir is None:
        venv_dir = VENV_DIR

    if not os.path.exists(venv_dir):
        return True, "Virtual environment does not exist"

    try:
        shutil.rmtree(venv_dir)
        _log(f"Removed venv: {venv_dir}")
        return True, "Virtual environment removed"
    except Exception as e:
        _log(f"Failed to remove venv: {e}", Qgis.MessageLevel.Warning)
        return False, f"Failed to remove virtual environment:\n{e}"


def cleanup_old_venv_directories():
    """Remove old venv at CACHE_DIR root from previous plugin layout.

    The plugin now uses CACHE_DIR/venv/ instead of CACHE_DIR as the venv.
    This helper detects and removes leftover venv artifacts at the root.

    Returns:
        A list of removed items.
    """
    removed = []
    if not os.path.exists(CACHE_DIR):
        return removed

    # Check for old-style venv markers at the CACHE_DIR root
    old_markers = [
        os.path.join(CACHE_DIR, "pyvenv.cfg"),
        os.path.join(CACHE_DIR, "Scripts"),
        os.path.join(CACHE_DIR, "bin"),
        os.path.join(CACHE_DIR, "Lib"),
        os.path.join(CACHE_DIR, "lib"),
    ]
    has_old_venv = any(os.path.exists(m) for m in old_markers)

    if has_old_venv:
        _log("Detected old venv layout at CACHE_DIR root, cleaning up...")
        for marker in old_markers:
            if os.path.exists(marker):
                try:
                    if os.path.isdir(marker):
                        shutil.rmtree(marker)
                    else:
                        os.remove(marker)
                    removed.append(marker)
                    _log(f"Removed old venv artifact: {marker}")
                except Exception as e:
                    _log(f"Failed to remove {marker}: {e}", Qgis.MessageLevel.Warning)

        # Also remove other venv artifacts
        for name in ("deps_hash.txt", "include", "share"):
            path = os.path.join(CACHE_DIR, name)
            if os.path.exists(path):
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    removed.append(path)
                except (
                    Exception
                ):  # nosec B110 (best-effort cache cleanup; missing files are not actionable)
                    pass

    return removed


# ---------------------------------------------------------------------------
# Earth Engine authentication
# ---------------------------------------------------------------------------


def ee_credentials_exist() -> bool:
    """Check if Earth Engine credentials file exists.

    Returns:
        True if credentials file exists, False otherwise.
    """
    credentials_path = os.path.expanduser("~/.config/earthengine/credentials")
    return os.path.exists(credentials_path)


def authenticate_ee(
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Tuple[bool, str]:
    """Run ee.Authenticate() in the venv Python as a subprocess.

    This opens a browser window for the user to complete OAuth authentication.
    The subprocess is non-blocking — the user interacts with the browser, and
    the process waits for them to complete.

    Args:
        progress_callback: Optional callback for status updates.

    Returns:
        A tuple of (success, message).
    """
    if not venv_exists():
        return False, "Virtual environment not found"

    python_path = get_venv_python_path()
    env = _get_clean_env_for_venv()
    kwargs = _get_subprocess_kwargs()

    # Use auth_mode='localhost:0' so ee's local OAuth callback server
    # binds an ephemeral kernel-assigned port instead of the default
    # 8085 — that fixed port collides with anything already listening
    # there (issue #49 reproduced as "OSError: [Errno 48] Address
    # already in use"). 'localhost' (without ':0') was the prior choice
    # to avoid ee's gcloud default, which requires the Google Cloud SDK
    # on PATH; the ':0' suffix is documented in ee.oauth.authenticate.
    auth_code = "import ee; ee.Authenticate(auth_mode='localhost:0')"

    if progress_callback:
        progress_callback(50, "Waiting for browser authentication...")

    _log("Running ee.Authenticate(auth_mode='localhost:0') in venv...")

    try:
        result = subprocess.run(  # nosec B603
            [python_path, "-c", auth_code],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes for user to complete browser auth
            env=env,
            **kwargs,
        )

        if result.returncode == 0:
            _log("Earth Engine authentication completed")
            if progress_callback:
                progress_callback(100, "Authentication complete!")
            return True, "Earth Engine authentication completed successfully"
        else:
            error = result.stderr or result.stdout or "Unknown error"
            # Log the *full* error so users (and #49-style bug reports)
            # can see the real traceback. The user-facing return value
            # stays compact for the message bar, with the log channel as
            # the source of truth.
            _log(
                f"EE authentication failed:\n{error}",
                Qgis.MessageLevel.Warning,
            )
            return False, (
                f"Authentication failed: {error[:500]}"
                "\n\n(Full traceback in the QGIS Message Log → Timelapse channel.)"
            )

    except subprocess.TimeoutExpired:
        return False, "Authentication timed out (5 minutes)"
    except Exception as e:
        return False, f"Authentication error: {str(e)[:500]}"
