#!/bin/bash
#
# Script to package the Timelapse plugin for distribution
# 
# This script is deprecated. Please use package_plugin.py instead:
#   python package_plugin.py
#
# Usage: ./package.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "Note: This script is deprecated. Consider using package_plugin.py instead."
echo ""

PLUGIN_NAME="timelapse"
PLUGIN_DIR="${SCRIPT_DIR}/../${PLUGIN_NAME}"

# Get version from metadata
VERSION=$(grep "version=" "${PLUGIN_DIR}/metadata.txt" | cut -d'=' -f2)

if [[ -z "$VERSION" ]]; then
    echo "❌ Could not determine version from metadata.txt"
    exit 1
fi

echo "Packaging ${PLUGIN_NAME} version ${VERSION}..."

# Create output directory
mkdir -p dist

# Create temp directory
TEMP_DIR=$(mktemp -d)
DEST_DIR="$TEMP_DIR/$PLUGIN_NAME"

# Copy plugin files
cp -r "$PLUGIN_DIR" "$DEST_DIR"

# Remove unwanted files
find "$DEST_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$DEST_DIR" -name "*.pyo" -delete 2>/dev/null || true
find "$DEST_DIR" -name ".DS_Store" -delete 2>/dev/null || true
find "$DEST_DIR" -name ".git*" -delete 2>/dev/null || true

# Create zip file
cd "$TEMP_DIR"
zip -r "${PLUGIN_NAME}-${VERSION}.zip" "$PLUGIN_NAME"

# Move to output directory
mv "${PLUGIN_NAME}-${VERSION}.zip" "${SCRIPT_DIR}/../dist/"

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "✅ Plugin packaged: dist/${PLUGIN_NAME}-${VERSION}.zip"
echo ""
