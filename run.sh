#!/usr/bin/env bash
# run.sh - Development build & run helper for Pasar
set -e

BUILDDIR="builddir"
PREFIX="$HOME/.local"

IS_CASK=0
if [ "$1" = "--cask" ]; then
    IS_CASK=1
    BUILDDIR="builddir-cask"
    PREFIX="$PWD/$BUILDDIR/cask-prefix"
    shift
fi

# Source Homebrew environment so pkg-config can find brew-installed libs (gtk4, libadwaita, etc.)
if [ -x "/opt/homebrew/bin/brew" ]; then
    BREW_PREFIX="/opt/homebrew"
elif [ -x "/usr/local/bin/brew" ]; then
    BREW_PREFIX="/usr/local"
elif [ -x "/home/linuxbrew/.linuxbrew/bin/brew" ]; then
    BREW_PREFIX="/home/linuxbrew/.linuxbrew"
else
    echo "==> Error: Homebrew not found in standard paths."
    exit 1
fi

eval "$("$BREW_PREFIX/bin/brew" shellenv)"

if [ ! -d "$BUILDDIR" ] || [ ! -f "$BUILDDIR/build.ninja" ]; then
    echo "==> Setting up meson build..."
    rm -rf "$BUILDDIR"
    meson setup "$BUILDDIR" --prefix="$PREFIX"
fi

echo "==> Building..."
ninja -C "$BUILDDIR"

echo "==> Installing to $PREFIX..."
ninja -C "$BUILDDIR" install

if [ "$(uname)" = "Darwin" ]; then
    if [ "$IS_CASK" -eq 1 ]; then
        APP_DIR="$PWD/Pasar.app"
    else
        APP_DIR="$HOME/Applications/Pasar.app"
    fi
    echo "==> Packaging macOS App Bundle..."
    mkdir -p "$APP_DIR/Contents/MacOS"
    mkdir -p "$APP_DIR/Contents/Resources"

    if [ ! -f "$APP_DIR/Contents/Resources/AppIcon.icns" ]; then
        ICON_SRC="data/icons/hicolor/scalable/apps/dev.hanthor.Pasar.svg"
        TMP_ICON="/tmp/pasar_icon_$$.png"
        TMP_ICONSET="/tmp/Pasar_$$.iconset"
        
        sips -s format png "$ICON_SRC" --out "$TMP_ICON" > /dev/null
        mkdir -p "$TMP_ICONSET"
        sips -z 16 16     "$TMP_ICON" --out "$TMP_ICONSET/icon_16x16.png" > /dev/null
        sips -z 32 32     "$TMP_ICON" --out "$TMP_ICONSET/icon_16x16@2x.png" > /dev/null
        sips -z 32 32     "$TMP_ICON" --out "$TMP_ICONSET/icon_32x32.png" > /dev/null
        sips -z 64 64     "$TMP_ICON" --out "$TMP_ICONSET/icon_32x32@2x.png" > /dev/null
        sips -z 128 128   "$TMP_ICON" --out "$TMP_ICONSET/icon_128x128.png" > /dev/null
        sips -z 256 256   "$TMP_ICON" --out "$TMP_ICONSET/icon_128x128@2x.png" > /dev/null
        sips -z 256 256   "$TMP_ICON" --out "$TMP_ICONSET/icon_256x256.png" > /dev/null
        sips -z 512 512   "$TMP_ICON" --out "$TMP_ICONSET/icon_256x256@2x.png" > /dev/null
        sips -z 512 512   "$TMP_ICON" --out "$TMP_ICONSET/icon_512x512.png" > /dev/null
        sips -z 1024 1024 "$TMP_ICON" --out "$TMP_ICONSET/icon_512x512@2x.png" > /dev/null
        
        iconutil -c icns "$TMP_ICONSET" -o "$APP_DIR/Contents/Resources/AppIcon.icns"
        rm -rf "$TMP_ICON" "$TMP_ICONSET"
    fi

    echo '<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>dev.hanthor.Pasar</string>
    <key>CFBundleName</key>
    <string>Pasar</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleExecutable</key>
    <string>Pasar</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>' > "$APP_DIR/Contents/Info.plist"

    if [ "$IS_CASK" -eq 1 ]; then
        echo "==> Bundling Resources for Cask distribution..."
        cp -R "$PREFIX/share" "$APP_DIR/Contents/Resources/"
        cp -R "$PREFIX/bin" "$APP_DIR/Contents/Resources/"
        
        echo '#!/bin/bash
# Break out of Rosetta 2 translation if macOS forced this shell script into x86_64
if [ "$(sysctl -in sysctl.proc_translated 2>/dev/null)" = "1" ]; then
    exec arch -arm64 /bin/bash "$0" "$@"
fi

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RESOURCES="$DIR/../Resources"

if [ -x "/opt/homebrew/bin/brew" ]; then
    BREW_PREFIX="/opt/homebrew"
elif [ -x "/usr/local/bin/brew" ]; then
    BREW_PREFIX="/usr/local"
else
    BREW_PREFIX="/home/linuxbrew/.linuxbrew"
fi

export PASAR_DATADIR="$RESOURCES/share/pasar"
export PASAR_LOCALEDIR="$RESOURCES/share/locale"
export GSETTINGS_SCHEMA_DIR="$RESOURCES/share/glib-2.0/schemas"
export XDG_DATA_DIRS="$RESOURCES/share:$BREW_PREFIX/share:/usr/share"

exec "$RESOURCES/bin/pasar" "$@"
' > "$APP_DIR/Contents/MacOS/Pasar"
        chmod +x "$APP_DIR/Contents/MacOS/Pasar"
        echo "==> Cask bundle successfully built at $APP_DIR"
        exit 0
    fi

    echo '#!/bin/bash
# Break out of Rosetta 2 translation if macOS forced this shell script into x86_64
if [ "$(sysctl -in sysctl.proc_translated 2>/dev/null)" = "1" ]; then
    exec arch -arm64 /bin/bash "$0" "$@"
fi

export GSETTINGS_SCHEMA_DIR="'"$HOME"'/.local/share/glib-2.0/schemas"
export XDG_DATA_DIRS="'"$BREW_PREFIX"'/share:'"$HOME"'/.local/share:/usr/local/share:/usr/share"
exec "'"$HOME"'/.local/bin/pasar" "$@"
' > "$APP_DIR/Contents/MacOS/Pasar"
    chmod +x "$APP_DIR/Contents/MacOS/Pasar"

    echo "==> Launching Pasar..."
    exec "$APP_DIR/Contents/MacOS/Pasar" "$@"
else
    echo "==> Launching Pasar..."
    exec env GSETTINGS_SCHEMA_DIR="$HOME/.local/share/glib-2.0/schemas" \
        XDG_DATA_DIRS="$BREW_PREFIX/share:$HOME/.local/share:/usr/local/share:/usr/share" \
        "$HOME/.local/bin/pasar" "$@"
fi
