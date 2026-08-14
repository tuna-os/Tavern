#!/usr/bin/env bash
# run-flatpak-widget-tests.sh — run Tavern's pytest suite inside the GNOME 50
# flatpak runtime (libadwaita 1.7+) the app actually ships on.
#
# Why: the host Tests workflow (tests.yml) runs against ubuntu-latest's
# libadwaita 1.5, which skips four Adw.Spinner widget tests. This script
# rebuilds the app with an appended tavern-widget-tests module and runs pytest
# inside the flatpak build sandbox, where org.gnome.Platform 50's libadwaita
# 1.7+ is used, so those skipped tests actually execute (tuna-os/Tavern#88).
#
# The production manifest (org.tunaos.tavern.json) is never modified: the test
# module is appended to a generated org.tunaos.tavern.tests.json, so pytest
# never ships in the published flatpak.
#
# Usage (inside a flatpak-github-actions container, or any host with
# flatpak-builder, the GNOME 50 SDK and xvfb):
#   scripts/run-flatpak-widget-tests.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

STATE_DIR="${1:-.flatpak-builder}"

python3 - <<'EOF'
import json

test_module = {
    "name": "tavern-widget-tests",
    "buildsystem": "simple",
    "build-options": {
        "build-args": ["--share=network"],
        # x11 socket so widget tests can reach the Xvfb display
        "test-args": ["--socket=x11"],
    },
    "build-commands": [
        "python3 -m pip install --prefix=/app pytest pytest-benchmark",
    ],
    "sources": [
        {"type": "dir", "path": "."},
    ],
    "test-commands": [
        # conftest.py registers the compiled gresource from this exact path
        "mkdir -p .flatpak-build/files/share/tavern && cp /app/share/tavern/tavern.gresource .flatpak-build/files/share/tavern/tavern.gresource",
        # pip --prefix=/app installs into /app/lib/python3.x/site-packages;
        # put it on PYTHONPATH explicitly so python3 -m pytest resolves
        "PYTHONPATH=$(python3 -c 'import sysconfig; print(sysconfig.get_path(\"purelib\", vars={\"base\": \"/app\"}))') python3 -m pytest tests -m 'not slow' --junitxml=junit-flatpak.xml -p no:cacheprovider",
    ],
}

with open("org.tunaos.tavern.json") as f:
    manifest = json.load(f)
manifest["modules"].append(test_module)

with open("org.tunaos.tavern.tests.json", "w") as f:
    json.dump(manifest, f, indent=4)
    f.write("\n")
print("Wrote org.tunaos.tavern.tests.json")
EOF

echo "Building with the tavern-widget-tests module and running pytest inside the GNOME 50 runtime..."
xvfb-run -a dbus-run-session -- \
  flatpak-builder \
    --repo=test-repo \
    --disable-rofiles-fuse \
    --install-deps-from=flathub \
    --state-dir="$STATE_DIR" \
    --force-clean \
    build-tests org.tunaos.tavern.tests.json

echo "Widget tests complete."
echo "JUnit report: $(find "$STATE_DIR" -name junit-flatpak.xml | head -1)"
echo "To wire this into Flatpak CI, add the test build to .github/workflows/flatpak.yml"
echo "using flatpak/flatpak-github-actions/flatpak-builder with run-tests: true and"
echo "manifest-path: org.tunaos.tavern.tests.json (build-bundle: false), then upload"
echo "'**/junit-flatpak.xml' as an artifact."
