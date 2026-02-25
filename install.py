#!/usr/bin/env python3
"""
Cross-platform installation script for QGIS Timelapse Plugin.

This script automatically detects your operating system and QGIS installation,
then installs the plugin to the appropriate location.

Usage:
    python install.py [options]

Options:
    --profile PROFILE    QGIS profile name (default: 'default')
    --uninstall          Remove the plugin instead of installing
    --qgis-path PATH     Custom QGIS plugins directory path
    --help               Show this help message
"""

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

PLUGIN_NAME = "timelapse"


def get_qgis_plugins_path(profile: str = "default", custom_path: str = None) -> Path:
    """
    Get the QGIS plugins directory path for the current platform.

    Args:
        profile: QGIS profile name.
        custom_path: Custom path override.

    Returns:
        Path to QGIS plugins directory.
    """
    if custom_path:
        return Path(custom_path)

    system = platform.system()
    home = Path.home()

    if system == "Linux":
        # Standard Linux path
        paths = [
            home
            / ".local"
            / "share"
            / "QGIS"
            / "QGIS3"
            / "profiles"
            / profile
            / "python"
            / "plugins",
            # Flatpak installation
            home
            / ".var"
            / "app"
            / "org.qgis.qgis"
            / "data"
            / "QGIS"
            / "QGIS3"
            / "profiles"
            / profile
            / "python"
            / "plugins",
            # Snap installation
            home
            / "snap"
            / "qgis"
            / "current"
            / ".local"
            / "share"
            / "QGIS"
            / "QGIS3"
            / "profiles"
            / profile
            / "python"
            / "plugins",
        ]
    elif system == "Darwin":  # macOS
        paths = [
            home
            / "Library"
            / "Application Support"
            / "QGIS"
            / "QGIS3"
            / "profiles"
            / profile
            / "python"
            / "plugins",
        ]
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        paths = [
            Path(appdata)
            / "QGIS"
            / "QGIS3"
            / "profiles"
            / profile
            / "python"
            / "plugins",
        ]
    else:
        raise OSError(f"Unsupported operating system: {system}")

    # Return first existing path, or first path if none exist
    for path in paths:
        if path.exists():
            return path

    # Return the standard path (will be created)
    return paths[0]


def get_script_directory() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.resolve()


def get_plugin_source_directory() -> Path:
    """Get the source directory containing the plugin files."""
    script_dir = get_script_directory()
    plugin_dir = script_dir / PLUGIN_NAME
    if plugin_dir.exists() and plugin_dir.is_dir():
        return plugin_dir
    # Fallback to script directory if plugin folder doesn't exist
    return script_dir


def install_plugin(plugins_dir: Path, source_dir: Path) -> bool:
    """
    Install the plugin to the QGIS plugins directory.

    Args:
        plugins_dir: Target QGIS plugins directory.
        source_dir: Source directory containing plugin files.

    Returns:
        True if successful, False otherwise.
    """
    plugin_dest = plugins_dir / PLUGIN_NAME

    print(f"\n📂 Installing plugin to: {plugin_dest}")

    # Create plugins directory if it doesn't exist
    try:
        plugins_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        print(f"❌ Permission denied creating directory: {plugins_dir}")
        print("   Try running with administrator/sudo privileges")
        return False

    # Remove existing installation
    if plugin_dest.exists():
        print(f"   Removing existing installation...")
        try:
            shutil.rmtree(plugin_dest)
        except PermissionError:
            print(f"❌ Permission denied removing: {plugin_dest}")
            return False

    # Copy entire plugin directory
    try:
        shutil.copytree(
            source_dir,
            plugin_dest,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.pyo",
                ".git",
                ".gitignore",
                ".DS_Store",
            ),
        )
        print(f"   ✓ Copied plugin files")
    except Exception as e:
        print(f"   ✗ Failed to copy plugin: {e}")
        return False

    # Count copied files
    copied = sum(1 for _ in plugin_dest.rglob("*") if _.is_file())
    print(f"\n✅ Installed {copied} files successfully")
    return True


def uninstall_plugin(plugins_dir: Path) -> bool:
    """
    Uninstall the plugin from the QGIS plugins directory.

    Args:
        plugins_dir: QGIS plugins directory.

    Returns:
        True if successful, False otherwise.
    """
    plugin_dest = plugins_dir / PLUGIN_NAME

    if not plugin_dest.exists():
        print(f"⚠️  Plugin not found at: {plugin_dest}")
        return True

    print(f"\n🗑️  Uninstalling plugin from: {plugin_dest}")

    try:
        shutil.rmtree(plugin_dest)
        print("✅ Plugin uninstalled successfully")
        return True
    except PermissionError:
        print(f"❌ Permission denied removing: {plugin_dest}")
        print("   Try running with administrator/sudo privileges")
        return False
    except Exception as e:
        print(f"❌ Failed to uninstall: {e}")
        return False


def print_post_install_instructions():
    """Print instructions for after installation."""
    print("\n" + "=" * 60)
    print("🎉 Installation Complete!")
    print("=" * 60)
    print("""
Next steps:

1. Restart QGIS if it's currently running

2. Enable the plugin:
   - Go to: Plugins → Manage and Install Plugins
   - Click on 'Installed' tab
   - Find 'Timelapse' and check the box to enable it

3. Authenticate with Google Earth Engine (first time only):
   - Run in terminal: earthengine authenticate
   - Or the plugin will prompt you when first used

4. Access the plugin:
   - Click the Timelapse icon in the toolbar, OR
   - Go to: Timelapse menu → Create Timelapse

For help and documentation, see:
https://github.com/opengeos/qgis-timelapse-plugin
""")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Install QGIS Timelapse Plugin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python install.py                    # Install with default settings
  python install.py --profile myprof   # Install to specific QGIS profile
  python install.py --uninstall        # Uninstall the plugin
  python install.py --qgis-path /path  # Install to custom path
        """,
    )

    parser.add_argument(
        "--profile", default="default", help="QGIS profile name (default: 'default')"
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall the plugin instead of installing",
    )
    parser.add_argument("--qgis-path", help="Custom QGIS plugins directory path")

    args = parser.parse_args()

    # Print header
    print("=" * 60)
    print("  QGIS Timelapse Plugin Installer")
    print("=" * 60)
    print(f"\n🖥️  Platform: {platform.system()} {platform.release()}")
    print(f"🐍 Python: {sys.version.split()[0]}")

    # Get paths
    source_dir = get_plugin_source_directory()
    print(f"📁 Source: {source_dir}")

    try:
        plugins_dir = get_qgis_plugins_path(args.profile, args.qgis_path)
        print(f"📁 Target: {plugins_dir}")
    except OSError as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

    # Uninstall mode
    if args.uninstall:
        success = uninstall_plugin(plugins_dir)
        sys.exit(0 if success else 1)

    # Install plugin
    success = install_plugin(plugins_dir, source_dir)

    if success:
        print_post_install_instructions()
        sys.exit(0)
    else:
        print("\n❌ Installation failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
