#!/usr/bin/env bash
# run.sh - Development build & run helper for Pasar
set -e

BUILDDIR="builddir"
PREFIX="$HOME/.local"

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

echo "==> Launching Pasar..."
exec env GSETTINGS_SCHEMA_DIR="$HOME/.local/share/glib-2.0/schemas" \
    XDG_DATA_DIRS="$BREW_PREFIX/share:$HOME/.local/share:/usr/local/share:/usr/share" \
    "$HOME/.local/bin/pasar" "$@"
