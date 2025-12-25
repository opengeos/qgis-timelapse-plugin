#!/bin/bash
#
# Installation script for QGIS Timelapse Plugin (Linux/macOS)
#
# Usage:
#   ./install.sh [--profile PROFILE] [--uninstall] [--deps]
#
# Options:
#   --profile PROFILE    QGIS profile name (default: 'default')
#   --uninstall          Remove the plugin instead of installing
#   --deps               Also install Python dependencies
#

set -e

PLUGIN_NAME="timelapse"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SOURCE="${SCRIPT_DIR}/${PLUGIN_NAME}"

# Default values
PROFILE="default"
UNINSTALL=false
INSTALL_DEPS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        --deps)
            INSTALL_DEPS=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--profile PROFILE] [--uninstall] [--deps]"
            echo ""
            echo "Options:"
            echo "  --profile PROFILE    QGIS profile name (default: 'default')"
            echo "  --uninstall          Remove the plugin instead of installing"
            echo "  --deps               Also install Python dependencies"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Determine QGIS plugins directory based on OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux - check standard, flatpak, and snap locations
    if [[ -d "$HOME/.local/share/QGIS/QGIS3" ]]; then
        QGIS_PLUGINS="$HOME/.local/share/QGIS/QGIS3/profiles/${PROFILE}/python/plugins"
    elif [[ -d "$HOME/.var/app/org.qgis.qgis/data/QGIS/QGIS3" ]]; then
        QGIS_PLUGINS="$HOME/.var/app/org.qgis.qgis/data/QGIS/QGIS3/profiles/${PROFILE}/python/plugins"
    elif [[ -d "$HOME/snap/qgis" ]]; then
        QGIS_PLUGINS="$HOME/snap/qgis/current/.local/share/QGIS/QGIS3/profiles/${PROFILE}/python/plugins"
    else
        QGIS_PLUGINS="$HOME/.local/share/QGIS/QGIS3/profiles/${PROFILE}/python/plugins"
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    QGIS_PLUGINS="$HOME/Library/Application Support/QGIS/QGIS3/profiles/${PROFILE}/python/plugins"
else
    echo "❌ Unsupported operating system: $OSTYPE"
    echo "   Please use install.py for Windows or other platforms."
    exit 1
fi

PLUGIN_DEST="${QGIS_PLUGINS}/${PLUGIN_NAME}"

echo "============================================================"
echo "  QGIS Timelapse Plugin Installer"
echo "============================================================"
echo ""
echo "🖥️  Platform: $(uname -s) $(uname -r)"
echo "📁 Source: ${PLUGIN_SOURCE}"
echo "📁 Target: ${PLUGIN_DEST}"
echo ""

# Check if source exists
if [[ ! -d "$PLUGIN_SOURCE" ]]; then
    echo "❌ Plugin source directory not found: ${PLUGIN_SOURCE}"
    exit 1
fi

# Uninstall mode
if [[ "$UNINSTALL" == true ]]; then
    if [[ -d "$PLUGIN_DEST" ]]; then
        echo "🗑️  Removing plugin from: ${PLUGIN_DEST}"
        rm -rf "$PLUGIN_DEST"
        echo "✅ Plugin uninstalled successfully"
    else
        echo "⚠️  Plugin not found at: ${PLUGIN_DEST}"
    fi
    exit 0
fi

# Install dependencies if requested
if [[ "$INSTALL_DEPS" == true ]]; then
    echo "📦 Installing Python dependencies..."
    if [[ -f "${SCRIPT_DIR}/requirements.txt" ]]; then
        pip install -r "${SCRIPT_DIR}/requirements.txt" && echo "✅ Dependencies installed" || echo "⚠️  Some dependencies failed to install"
    else
        echo "⚠️  requirements.txt not found"
    fi
    echo ""
fi

# Create plugins directory if it doesn't exist
mkdir -p "$(dirname "$PLUGIN_DEST")"

# Remove existing installation
if [[ -d "$PLUGIN_DEST" ]]; then
    echo "   Removing existing installation..."
    rm -rf "$PLUGIN_DEST"
fi

# Copy plugin files
echo "📂 Installing plugin..."
cp -r "$PLUGIN_SOURCE" "$PLUGIN_DEST"

# Remove compiled files and cache directories
find "$PLUGIN_DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$PLUGIN_DEST" -name "*.pyc" -delete 2>/dev/null || true
find "$PLUGIN_DEST" -name "*.pyo" -delete 2>/dev/null || true
find "$PLUGIN_DEST" -name ".DS_Store" -delete 2>/dev/null || true

# Count installed files
FILE_COUNT=$(find "$PLUGIN_DEST" -type f | wc -l | tr -d ' ')
echo "✅ Installed ${FILE_COUNT} files successfully"

echo ""
echo "============================================================"
echo "🎉 Installation Complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Restart QGIS if it's currently running"
echo ""
echo "2. Enable the plugin:"
echo "   - Go to: Plugins → Manage and Install Plugins"
echo "   - Click on 'Installed' tab"
echo "   - Find 'Timelapse' and check the box to enable it"
echo ""
echo "3. Authenticate with Google Earth Engine (first time only):"
echo "   - Run in terminal: earthengine authenticate"
echo "   - Or the plugin will prompt you when first used"
echo ""
echo "4. Access the plugin:"
echo "   - Click the Timelapse icon in the toolbar, OR"
echo "   - Go to: Timelapse menu → Create Timelapse"
echo ""
echo "For help and documentation, see:"
echo "https://github.com/giswqs/qgis-timelapse-plugin"
echo ""

