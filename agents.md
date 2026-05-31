# Tavern Developer & AI Agent Guide

## Quick Start

Build and run locally:
```bash
./run.sh                    # Full build + install + run with Homebrew
just dev                    # Full Flatpak build + install + run
just run-direct             # Run without rebuilding
```

## Project Structure

```
tavern/
├── agents.md              # This file
├── skills/                # AI agent skill definitions
├── run.sh                 # Local dev wrapper (Homebrew build)
├── Justfile               # Flatpak build automation
├── src/                   # Python source code
│   ├── main.py           # Entry point with startup profiling
│   ├── application.py    # GTK app singleton
│   ├── window.py         # Main window (heavily instrumented)
│   ├── backend.py        # Homebrew/Flathub/Tap data layer
│   ├── *_page.py         # Browse/Search/Installed/Brewfile pages
│   └── *.blp             # Blueprint UI definitions
├── data/                  # Desktop integration files
├── tests/                 # Pytest test suite
└── README.md              # User documentation
```

## Build System

### Local Development (Homebrew)

**File:** `run.sh`

The development script builds with Homebrew-installed GTK4/Libadwaita and installs to `~/.local/`.

**Key environment setup:**
- Sources Homebrew shell environment
- Sets `XDG_DATA_DIRS` for resource discovery
- Installs to `$HOME/.local` (not system-wide)

**Usage:**
```bash
bash run.sh                 # Build, install, launch
bash run.sh --log=debug    # Launch with full logging
```

### Flatpak (Production)

**File:** `Justfile`

Build and package as a Flatpak for distribution.

**Tasks:**
```bash
just build                  # Compile the Flatpak container
just install                # Build + install to user Flatpak
just dev                    # Build + install + run (one command)
just run                    # Run already-installed Flatpak
just uninstall              # Remove app and local remote
just clean                  # Remove all build artifacts
```

**Build directories:**
- `.flatpak-build/` — compilation workspace
- `.flatpak-repo/` — local package repository
- `.flatpak-state/` — build cache

## Logging & Profiling

### Overview

Tavern has a comprehensive instrumentation system for debugging and performance analysis. All major operations are timed and logged.

**Design:** Logging is **OFF by default**. Enable via environment variables for zero overhead in normal operation.

### Environment Variables

```bash
TAVERN_LOG=1|info           # Enable INFO-level logging
TAVERN_LOG=debug            # Enable DEBUG-level logging (verbose)
TAVERN_PROFILE=1            # Enable @profile decorator timing (requires TAVERN_LOG)
TAVERN_LOG_FILE=/tmp/p.log  # Also write logs to this file
```

**Example:**
```bash
# Full startup profiling to console
TAVERN_LOG=info ./run.sh

# Detailed backend debugging to file
TAVERN_LOG=debug TAVERN_LOG_FILE=/tmp/tavern.log ./run.sh

# Performance profiling only
TAVERN_PROFILE=1 TAVERN_LOG=info ./run.sh
```

### Logging Infrastructure

**File:** `src/logging_util.py`

**Key functions:**
- `init_logging()` — Initialize logging system (called at startup)
- `get_logger(name)` — Get a logger for a module (e.g., `get_logger('backend')` → `Tavern.backend`)
- `log_timing(label, category)` — Context manager for timing blocks
- `@profile` — Decorator for function-level timing

**Log format:**
```
HH:MM:SS.mmm [LEVEL] Tavern.module: message
```

Example output:
```
15:35:49.725 [INFO ] Tavern.window: Kicking off backend.load_all_async()
15:35:49.726 [DEBUG] Tavern.backend: _load_all_thread started
15:35:50.768 [INFO ] Tavern.window: Formulae loaded: 14 packages
```

### Startup Profiling

**File:** `src/main.py`

The application startup is fully instrumented with timing breakpoints:

```
============================================================================
TAVERN DESKTOP STARTUP
============================================================================
Starting Tavern  version=0.1.0  python=3.12.12
Resources loaded: 2.3 ms
Application module imported: 145.2 ms
Application instance created: 4.5 ms
Running application...
```

Then followed by `do_activate()` in `application.py`:

```
do_activate: called
TavernWindow created: 125.3 ms
CSS loaded and applied: 3.2 ms
Window presented: 8.1 ms
```

And window initialization in `window.py`:

```
TavernWindow.__init__: starting
Backend created: 2.1 ms
Task manager created: 1.3 ms
Pages wired: 0.8 ms
Window actions setup: 2.2 ms
Settings restored: 1.5 ms
Backend.load_all_async() started: 0.6 ms
TavernWindow.__init__: completed in 137.8 ms
```

**Available timing points:**
- `main()` — Full startup from process start to window shown
- `__init__()` — Homebrew backend + Flathub integration startup
- `do_activate()` — Window creation and CSS loading
- `load_brewfile()` — Brewfile parsing and package loading (with per-category stats)
- `_load_packages_thread()` — Formulae/cask/flatpak loading with min/max/avg times

### Brewfile Loading Profiling

**File:** `src/brewfile_page.py`

Comprehensive per-package profiling when opening a Brewfile:

```
======================================================================
Loading Brewfile: /usr/share/ublue-os/homebrew/artwork.Brewfile
======================================================================
Tapping: ublue-os/tap
Loading packages: formulae=0, casks=5, flatpaks=0
Loaded cask aurora-wallpapers: 5311.6 ms
Loaded cask bazzite-wallpapers: 2104.3 ms
...
Casks stats: count=5, min=0.1 ms, max=5311.6 ms, avg=1704.2 ms
Tap ublue-os/tap: success (4310.2 ms)
Finished populating 5 packages
======================================================================
TOTAL BREWFILE LOAD TIME: 7234.5 ms
======================================================================
```

### Key Logging Locations

| Module | Key logs |
|--------|----------|
| `main.py` | Startup timeline, resource loading |
| `application.py` | Command-line parsing, activation, window/brewfile events |
| `window.py` | Window init, page loading, package activation |
| `backend.py` | Backend init, tap scanning, package fetch, icon loading |
| `brewfile_page.py` | Brewfile parsing, tapping, per-package timing, statistics |
| `package_tile.py` | Icon loading, tile rendering |

## Command-Line Arguments

Tavern supports opening packages and Brewfiles from the command line:

```bash
# Open a specific package (if available)
tavern --package=<name>
tavern -p <name>

# Open a Brewfile
tavern --brewfile=/path/to/file.Brewfile
tavern -b /path/to/file.Brewfile

# Open with logging enabled
TAVERN_LOG=info tavern --brewfile ~/mybrewfile
```

**Implementation:** `src/application.py` — `do_command_line()` method

Uses direct `sys.argv` parsing (more reliable than GTK's OptionArg system for custom args).

## Key Features & Their Implementation

### Homebrew Integration
- **Backend:** `backend.py` — Homebrew API, local brew CLI, tap scanning
- **Data:** Package class with formula, cask, flatpak types
- **Caching:** `~/.cache/tavern/` for formulae/casks JSON

### Flatpak Support
- **Discovery:** Flathub appstream API (`https://flathub.org/api/v2/appstream/{app_id}`)
- **Metadata:** Icon URL, summary, homepage, releases
- **Launching:** `xdg-open appstream://{app_id}` → Bazaar MIME handler

### Brewfile Management
- **Parsing:** `backend.parse_brewfile()` — Supports tap, brew, cask, flatpak entries
- **Rendering:** `brewfile_page.py` — Tab-based UI, per-type sections
- **Duplicate Prevention:** `window._open_brewfiles` tracks open file paths
- **Performance:** Full profiling chain from parse to render

### UI & Styling
- **Framework:** GTK 4.20.3 + Libadwaita 1.8.4
- **UI Definition:** Blueprint `.blp` files compiled to `.ui` XML
- **Styling:** `src/style.css` with custom theme variables
- **Resources:** Compiled into `tavern.gresource` bundle

## Troubleshooting

### "Unable to load resource for composite template..."
Libadwaita resources not found. Fix missing Homebrew pkg-config symlinks:
```bash
ln -s ../../Cellar/libadwaita/1.8.4/lib/pkgconfig/libadwaita-1.pc \
  /home/linuxbrew/.linuxbrew/lib/pkgconfig/libadwaita-1.pc
ln -s ../../Cellar/libadwaita/1.8.4/lib/girepository-1.0/Adw-1.typelib \
  /home/linuxbrew/.linuxbrew/lib/girepository-1.0/Adw-1.typelib
```

### Text not rendering on labels
Enable logging and check output for GTK assertion failures. Often caused by template widgets not loading properly. See "Logging & Profiling" above.

### Slow Homebrew builds
Homebrew formulae downloads/parsing happens in a background thread. Check logs:
```bash
TAVERN_LOG=debug ./run.sh 2>&1 | grep -E "Installed|Tap scan|Cache"
```

## Testing

**Run tests:**
```bash
pytest tests/
pytest tests/test_backend.py -v                  # Specific test file
pytest tests/test_backend.py::test_parse -v      # Specific test
```

**With logging:**
```bash
TAVERN_LOG=debug pytest tests/ -s                 # Show all output
```

## Environment Notes

**Current setup:**
- **OS:** Fedora Silverblue (DistroBox)
- **GTK:** 4.20.3 (Homebrew)
- **Libadwaita:** 1.8.4 (newer than system 1.7.5)
- **Python:** 3.12.12 (Homebrew)
- **pkg-config symlinks:** Required for Homebrew detection

## Skills Directory

See `skills/` for AI agent skill definitions:
- `skills/build.md` — Build system capabilities
- `skills/profiling.md` — Performance profiling & logging
- `skills/features.md` — Feature implementation guide
