APP_ID := "dev.hanthor.Tavern.Devel"
MANIFEST := APP_ID + ".json"
BUILD_DIR := ".flatpak-build"
REPO_DIR := ".flatpak-repo"
STATE_DIR := ".flatpak-state"

# Build the Devel Flatpak and install it (default for local dev)
default: dev

# Build the Devel Flatpak
build:
    flatpak run org.flatpak.Builder \
        --force-clean \
        --state-dir={{STATE_DIR}} \
        --repo={{REPO_DIR}} \
        {{BUILD_DIR}} \
        {{MANIFEST}}

# Install the just-built Devel Flatpak
install: build
    flatpak --user remote-add --no-gpg-verify --if-not-exists tavern-local {{REPO_DIR}}
    flatpak --user install --or-update --noninteractive tavern-local {{APP_ID}}

# Run the installed Devel Flatpak
run:
    flatpak run {{APP_ID}}

run-direct:
    ./run.sh

# Build, install, and immediately run (devel)
dev: install run

# Build & install the production release Flatpak
release:
    flatpak run org.flatpak.Builder \
        --force-clean \
        --state-dir={{STATE_DIR}} \
        --repo={{REPO_DIR}} \
        {{BUILD_DIR}} \
        dev.hanthor.Tavern.json
    flatpak --user remote-add --no-gpg-verify --if-not-exists tavern-local {{REPO_DIR}}
    flatpak --user install --or-update --noninteractive tavern-local dev.hanthor.Tavern

# Uninstall the Devel app and remove the local remote
uninstall:
    flatpak --user uninstall --noninteractive {{APP_ID}} || true
    flatpak --user remote-delete tavern-local || true

# Clean all build artefacts
clean:
    rm -rf {{BUILD_DIR}} {{REPO_DIR}} {{STATE_DIR}}

# Validate desktop and AppStream metadata if tools are available
validate:
    -desktop-file-validate data/dev.hanthor.Tavern.desktop.in
    -appstreamcli validate data/dev.hanthor.Tavern.metainfo.xml.in

