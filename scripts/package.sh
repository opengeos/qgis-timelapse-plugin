#!/bin/bash
# Script to package the plugin for distribution

PLUGIN_NAME="timelapse"
VERSION=$(grep "version=" ../metadata.txt | cut -d'=' -f2)

# Create output directory
mkdir -p ../dist

# Create temp directory
TEMP_DIR=$(mktemp -d)
PLUGIN_DIR="$TEMP_DIR/$PLUGIN_NAME"

# Copy plugin files
mkdir -p "$PLUGIN_DIR"
mkdir -p "$PLUGIN_DIR/icons"

cp ../__init__.py "$PLUGIN_DIR/"
cp ../metadata.txt "$PLUGIN_DIR/"
cp ../timelapse_plugin.py "$PLUGIN_DIR/"
cp ../timelapse_dialog.py "$PLUGIN_DIR/"
cp ../timelapse_core.py "$PLUGIN_DIR/"
cp ../icons/icon.png "$PLUGIN_DIR/icons/"
cp ../icons/icon.svg "$PLUGIN_DIR/icons/"
cp ../resources.qrc "$PLUGIN_DIR/"
cp ../requirements.txt "$PLUGIN_DIR/"
cp ../install.py "$PLUGIN_DIR/"
cp ../LICENSE "$PLUGIN_DIR/"
cp ../README.md "$PLUGIN_DIR/"

# Create zip file
cd "$TEMP_DIR"
zip -r "${PLUGIN_NAME}-${VERSION}.zip" "$PLUGIN_NAME"

# Move to output directory
mv "${PLUGIN_NAME}-${VERSION}.zip" "$(dirname "$0")/../dist/"

# Cleanup
rm -rf "$TEMP_DIR"

echo "Plugin packaged: dist/${PLUGIN_NAME}-${VERSION}.zip"
