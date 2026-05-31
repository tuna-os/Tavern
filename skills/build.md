# Build & Deployment Skills

## Overview
Tavern is built with Meson for local development and Flatpak for distribution. Both paths are fully automated.

## Local Development (Homebrew)

**Script:** `run.sh`

The local development build targets Homebrew-installed GTK4 and Libadwaita. This is the fastest iteration path.

### Build Steps
1. Source Homebrew environment
2. Run `meson install -C builddir 2>&1`
3. Set `XDG_DATA_DIRS` to include Homebrew and system data paths
4. Launch `/home/linuxbrew/.linuxbrew/bin/tavern`

### Key Environment Variables
- `GSETTINGS_SCHEMA_DIR=~/.local/share/glib-2.0/schemas` — GSettings schema location
- `XDG_DATA_DIRS=~/.local/share:/usr/share:...` — UI resource paths
- `HOMEBREW_PREFIX=/home/linuxbrew/.linuxbrew` — Homebrew installation root

### Build Artifacts
- `builddir/` — Meson build directory (auto-created)
- `~/.local/bin/tavern` — Installed executable script
- `~/.local/share/tavern/` — UI resources (`.ui`, `.gresource`)
- `~/.local/share/applications/dev.hanthor.Tavern.desktop` — Desktop entry

### Troubleshooting Local Builds

**"symbol not found in flat namespace"**
→ pkg-config symlinks missing for Homebrew. Run:
```bash
ln -s ../../Cellar/libadwaita/1.8.4/lib/pkgconfig/libadwaita-1.pc \
  /home/linuxbrew/.linuxbrew/lib/pkgconfig/libadwaita-1.pc
ln -s ../../Cellar/libadwaita/1.8.4/lib/pkgconfig/gio-2.0.pc \
  /home/linuxbrew/.linuxbrew/lib/pkgconfig/gio-2.0.pc
ln -s ../../Cellar/libadwaita/1.8.4/lib/girepository-1.0/Adw-1.typelib \
  /home/linuxbrew/.linuxbrew/lib/girepository-1.0/Adw-1.typelib
```

**"Unable to load resource for composite template..."**
→ Resource loading failed. Check that:
1. `tavern.gresource` exists in `~/.local/share/tavern/`
2. `XDG_DATA_DIRS` includes `~/.local/share`
3. GSETTINGs schema is in place: `glib-compile-schemas ~/.local/share/glib-2.0/schemas`

## Flatpak Development

**Configuration:** `Justfile`, `dev.hanthor.Tavern.json`

Flatpak provides isolated, reproducible builds suitable for distribution.

### Build Targets
```bash
just build              # Build Flatpak container only
just install            # Build + install to user Flatpak environment
just dev                # Build + install + run (complete cycle)
just run                # Run already-installed Flatpak
just uninstall          # Remove installed Flatpak
just clean              # Remove all artifacts
```

### Build Pipeline
1. **Build:** `flatpak-builder` compiles sources and dependencies
2. **Create runtime:** Combines shared libraries and tools
3. **Bundle:** Creates `.flatpak` installation bundle
4. **Install:** Registers in user's Flatpak environment
5. **Launch:** Via `flatpak run dev.hanthor.Tavern`

### Build Directories & Artifacts
- `.flatpak-build/` — Compilation workspace (can reach 5GB+)
- `.flatpak-repo/` — Local package repository
- `.flatpak-state/` — Build incremental cache
- Installed: `~/.local/share/flatpak/app/dev.hanthor.Tavern/`

### Manifest
**File:** `dev.hanthor.Tavern.json`

Contains:
- Runtime dependencies (GTK4, Libadwaita, Python)
- Build command options
- Module definitions
- Property permissions (D-Bus, file access, network)

### Env in Flatpak
Flatpak automatically:
- Sandboxes the application
- Provides only declared permissions
- Manages system library versions
- Sets up D-Bus communication

## Testing

### Unit Tests
```bash
pytest tests/                           # Run all tests
pytest tests/test_backend.py -v         # Specific test file
pytest tests/test_backend.py::test_parse_brewfile  # Specific test
TAVERN_LOG=debug pytest tests/ -s        # With full verbose output
```

### Test Files
- `tests/test_backend.py` — Package parsing, Homebrew API
- `tests/test_search_provider.py` — Search plugin (D-Bus)
- `tests/test_task_manager.py` — Async task execution
- `tests/test_logging_util.py` — Logging infrastructure
- `tests/conftest.py` — Shared fixtures

### Test Framework
**Tool:** `pytest` (see `pyproject.toml`)

**Key fixtures:**
- `mock_backend` — Pre-populated backend for testing
- `tmp_path` — Temporary directory for file tests
- `monkeypatch` — Environment variable mocking

## Meson Build System

**File:** `meson.build` (root), `src/meson.build`, `data/meson.build`

### Key Targets
```bash
meson setup builddir                # Initialize build directory
meson compile -C builddir           # Compile only
meson install -C builddir           # Compile and install
ninja -C builddir                   # Direct Ninja invocation
```

### Build Options
Available via `meson configure builddir -D<option>=<value>`:
- `prefix=/home/linuxbrew/.linuxbrew` — Installation root
- `libdir=lib` — Library directory
- `datadir=share` — Data directory

### Targets
- `tavern` — Main executable (Python script)
- `tavern.gresource` — Resource bundle (UI + assets)
- `tavern.desktop`, `*.ui`, `*.metainfo.xml` — Data files

## CI/CD Integration

Currently local development only. For future CI:

1. **Docker/Podman:** Use UBlue base image
2. **Matrix:** Test on multiple GNOME versions
3. **Artifacts:** Publish `.flatpak` to Flathub
4. **Gating:** Require tests + linting to pass

## Performance Considerations

### Cold Start (~7-8 seconds total)
- **1.5s:** GTK/Libadwaita module import
- **1.2s:** Backend initialization
- **2-4s:** Taps scan and Homebrew catalog load
- **1-2s:** UI rendering

Use `TAVERN_LOG=info TAVERN_PROFILE=1 ./run.sh` to profile.

### Hot Reload (development iteration)
Changes to:
- **.blp files:** Rebuild only UI file, `meson install`
- **.py files:** Often run without rebuild (some runtimes support this)
- **meson.build:** Full rebuild required

For rapid iteration: `just run-direct` skips rebuild if already installed.
