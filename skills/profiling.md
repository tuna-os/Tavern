# Profiling & Diagnostics Skills

## Overview
Tavern includes comprehensive logging and profiling infrastructure. All major operations are instrumented with timing information and debug output.

**Design principle:** Logging is **disabled by default** for zero overhead. Enable via environment variables when needed.

## Quick Start

```bash
# Full startup timing
TAVERN_LOG=info ./run.sh

# Detailed debugging
TAVERN_LOG=debug ./run.sh

# Performance profiling only
TAVERN_PROFILE=1 TAVERN_LOG=info ./run.sh

# Log to file
TAVERN_LOG=debug TAVERN_LOG_FILE=/tmp/tavern.log ./run.sh
```

## Environment Variables

### TAVERN_LOG
Controls logging level. Options:
- `1`, `true`, `on` → INFO level
- `info` → INFO level (identical to above)
- `debug` → DEBUG level (very verbose)
- Unset or `0` → No logging (default)

**Effect:** Enables `logging.StreamHandler` and logs to stderr.

### TAVERN_PROFILE
Controls @profile decorator timing. Options:
- `1`, `true`, `on` → Enable timing
- Unset or `0` → Disable (default)

**Requires:** `TAVERN_LOG` must be set to one of the above values.

**Effect:** Every function and context manager logs entry/exit with elapsed milliseconds.

### TAVERN_LOG_FILE
Optional file path for log output. Options:
- Absolute path (e.g., `/tmp/tavern.log`) → Logs to file AND stderr
- Unset → Logs to stderr only (default)

**Effect:** Enables `logging.FileHandler` in addition to streaming.

## Logging System

**File:** `src/logging_util.py`

### Core Functions

#### `init_logging()`
Called at application startup (in `main.py`).

Sets up:
- Logger hierarchy (`Tavern`, `Tavern.module`, etc.)
- Handlers (console, file if enabled)
- Formatters (timestamp, level, module name)
- Handler level filtering

**Called from:** `main.py` before any module imports

#### `get_logger(name: str)`
Factory function for module loggers.

```python
logger = get_logger('backend')  # → Tavern.backend logger
logger.info("Starting backend init")
```

**Usage:** Every module does:
```python
logger = get_logger(__name__)
```

**Result:** Logs appear as `Tavern.module_name: message`

### Log Format

```
HH:MM:SS.mmm [LEVEL] Tavern.module: message
```

Example:
```
15:35:49.725 [INFO ] Tavern.window: Kicking off backend.load_all_async()
15:35:49.726 [DEBUG] Tavern.backend: _load_all_thread started
15:35:50.768 [INFO ] Tavern.window: Formulae loaded: 14 packages
```

**Components:**
- `HH:MM:SS.mmm` — Wall clock time with milliseconds
- `[LEVEL]` — INFO, DEBUG, WARNING, ERROR (7 chars, right-aligned)
- `Tavern.module` — Logger hierarchy (left-aligned)
- `message` — Custom log text

## Profiling Infrastructure

### @profile Decorator

**File:** `src/logging_util.py`

Decorator for function-level timing.

```python
@profile
def parse_brewfile(path):
    ...
```

**Output:**
```
Tavern.backend: >> parse_brewfile() start
Tavern.backend: << parse_brewfile() finished: 234.5 ms
```

**Behavior:**
- Logs entry message before function runs
- Logs exit with elapsed time in milliseconds
- Uses `time.perf_counter()` for precise measurement
- Only works when `TAVERN_PROFILE=1`

**Performance:** No overhead when disabled.

### log_timing Context Manager

**File:** `src/logging_util.py`

Context manager for timing blocks.

```python
with log_timing("Loading packages", "backend"):
    packages = backend.load_all()
```

**Output:**
```
Tavern.backend: ⏱  Loading packages (backend) started
Tavern.backend:    Loading packages (backend) finished: 1234.5 ms
```

**Parameters:**
- `label` — Human-readable operation name
- `category` — Log category (module name)

**Behavior:**
- Logs start and finish on separate lines
- Indents finish message by 2 spaces
- Measures wall time from entry to exit
- Returns elapsed time to caller

**Usage in code:**
```python
with log_timing("Tapping homebrew/cask", category="backend") as elapsed:
    tap_formulae()
    tap_casks()
logger.info(f"Tap completed in {elapsed} ms")
```

## Startup Profiling

### Main Entry Point

**File:** `src/main.py`

Full startup profiling with separator markers:

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

**Timing points:**
1. `startup_start = time.perf_counter()` — Zero point
2. After resource loading: `resource_load_time`
3. After `from tavern import application` import: `import_time`
4. After `application.Tavern()` creation: `app_init_time`
5. After `app.run()` returns: `total_time`

**Format:** Each timing uses `(time_ms:.1f} ms` format. Separators use `===` on both sides.

### Application Activation

**File:** `src/application.py`

Window creation and CSS loading timing:

```
do_activate: called
TavernWindow created: 125.3 ms
CSS loaded and applied: 3.2 ms
Window presented: 8.1 ms
```

**Timing points:**
1. Entry to `do_activate()`
2. After `TavernWindow()` creation: `window_time`
3. After CSS loading: `css_time`
4. After `window.present()`: `present_time`
5. Summary: `total_activate_time`

**Key operation:** CSS loading can be slow on first startup due to Libadwaita theme compilation.

### Window Initialization

**File:** `src/window.py`

The most detailed profiling section:

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

**Timing points (in order):**
1. `init_start` — Entry marker
2. `backend_time` — `BrewBackend()` initialization
3. `task_manager_time` — `TaskManager()` creation
4. `pages_time` — Wiring browse/search/installed/brewfile pages
5. `actions_time` — Setting up window actions and keyboard shortcuts
6. `settings_time` — Restoring window geometry and settings
7. `load_start_time` — Starting `backend.load_all_async()`
8. `total_init_time` — Total wall time in `__init__`

**Note:** Backend population (formulae, casks, flatpaks) happens asynchronously after init completes.

## Brewfile Loading Profiling

### Per-Package Timing

**File:** `src/brewfile_page.py`

When opening a Brewfile, individual package loads are timed:

```
======================================================================
Loading Brewfile: /usr/share/ublue-os/homebrew/artwork.Brewfile
======================================================================
Tapping: ublue-os/tap
Loading packages: formulae=0, casks=5, flatpaks=0
Loaded cask aurora-wallpapers: 5311.6 ms
Loaded cask bazzite-wallpapers: 2104.3 ms
Loaded cask gnome-shell: 312.5 ms
Loaded cask ubuntu-font-family: 89.2 ms
Loaded cask whiskers: 1203.4 ms
Casks stats: count=5, min=89.2 ms, max=5311.6 ms, avg=1704.2 ms
Tap ublue-os/tap: success (4310.2 ms)
Finished populating 5 packages
======================================================================
TOTAL BREWFILE LOAD TIME: 7234.5 ms
======================================================================
```

**Timing breakdown:**
1. **Per-item:** Each formula/cask/flatpak logged individually with time
2. **Category stats:** Min/max/average for each type (formula, cask, flatpak)
3. **Per-tap:** Total time for tap operation (including all packages)
4. **Total:** Wall time from open to finish

**Performance insights:**
- **First time slow:** Icons need to be fetched from Flathub or web
- **Subsequent:**~ faster due to HTTP caching
- **Flatpaks:** Tend to be slower due to Flathub API latency

### Tap Operations

**File:** `src/brewfile_page.py` — `_tap_async()` method

Individual tap timing:

```
Tap ublue-os/tap: started
Tap ublue-os/tap: success (4310.2 ms)
```

or on error:

```
Tap ublue-os/tap: failed - Error message here
```

## Log Locations

### By Operation

| Operation | Module | Log pattern |
|-----------|--------|------------|
| Application entry | `main` | `TAVERN DESKTOP STARTUP` |
| Window creation | `application` | `do_activate:` |
| Backend init | `window` | `Backend created:` |
| Homebrew scan | `backend` | `Scanning taps:`, `Found X formulae` |
| Brewfile open | `brewfile_page` | `Loading Brewfile:` |
| Icon fetch | `package_tile` | `Loading icon for` |
| Search | `search_page` | `Search query:` |

### Filtering Logs

Example: Show only window timing
```bash
TAVERN_LOG=info ./run.sh 2>&1 | grep -E "Window|TavernWindow"
```

Example: Show only Brewfile performance
```bash
TAVERN_LOG=info ./run.sh 2>&1 | grep -E "Brewfile|Casks stats"
```

Example: Show only @profile decorators
```bash
TAVERN_PROFILE=1 TAVERN_LOG=info ./run.sh 2>&1 | grep -E ">>|<<"
```

## Performance Optimization Process

1. **Enable profiling:**
   ```bash
   TAVERN_LOG=info TAVERN_PROFILE=1 ./run.sh 2>&1 | tee /tmp/profile.log
   ```

2. **Identify slow operations:**
   - Search for largest `ms` values
   - Check for any `failed` entries
   - Look for long gaps between timestamps

3. **Add timing to new code:**
   ```python
   with log_timing("Operation name", "module_name"):
       slow_function()
   ```

4. **Re-profile and compare:**
   - Rebuild: `meson install -C builddir`
   - Re-run profile command
   - diff old and new logs

5. **Commit improvement:**
   - Include before/after timing in commit message
   - Note which operations were improved

## Known Slow Paths

### First Homebrew tab load (~2-4s)
- Scanning all installed taps
- Fetching formulae metadata
- Indexing for search

**Optimization:** Background task, doesn't block UI

### Icon downloads (~1-5s per Brewfile)
- Flathub API roundtrip for each package
- Icon image download
- Image caching

**Optimization:** Downloaded to cache, reused on subsequent opens

### CSS theme compilation (first run)
- Libadwaita compiling GTK CSS from source
- Affects initial window presentation

**Optimization:** Happens once, then cached by GTK
