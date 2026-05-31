# Feature Implementation & Architecture Skills

## Overview
Tavern is a GTK4 + Libadwaita desktop application for managing Homebrew packages and Brewfiles. The architecture is modular and designed for extension.

**Technology Stack:**
- **UI Framework:** GTK 4.20.3 + Libadwaita 1.8.4
- **UI Definition:** Blueprint language (`.blp` files, compiled to `.ui`)
- **Application Runtime:** Python 3.12
- **Backend:** Homebrew + Flathub + local file system
- **IPC:** D-Bus for search provider integration
- **Build System:** Meson + Flatpak

## High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│  GTK4 Application Window (TavernWindow)              │
│  ┌──────────────────────────────────────────────────┤
│  │ Tab Container                                    │
│  │ ├─ Browse Page (BrowsePage)                      │
│  │ │  └─ Category filters + package tiles           │
│  │ ├─ Search Page (SearchPage)                      │
│  │ │  └─ Live search over Homebrew + Flathub       │
│  │ ├─ Installed Page (InstalledPage)                │
│  │ │  └─ Currently installed packages               │
│  │ └─ Brewfile Page (BrewfilePage)                  │
│  │    └─ Parse & display .Brewfile contents        │
│  └──────────────────────────────────────────────────┤
│  Task Panel (bottom)                                │
│  ├─ Operation queue + progress                      │
│  └─ Async job management via TaskManager            │
└─────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│ Backend Layer (BrewBackend)                         │
│ ├─ Homebrew CLI wrapper                            │
│ │  ├─ brew list, brew search, brew install, etc.   │
│ │  └─ Tap scanning                                 │
│ ├─ Flathub integration                             │
│ │  ├─ Appstream API queries                        │
│ │  └─ Icon downloads                               │
│ ├─ File I/O                                        │
│ │  ├─ Brewfile parsing                             │
│ │  └─ Configuration storage                        │
│ └─ Caching                                         │
│    └─ ~/.cache/tavern/ for metadata                 │
└─────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────┬──────────────┬──────────────┐
│ Homebrew CLI │ Flathub API  │ File System  │
└──────────────┴──────────────┴──────────────┘
```

## Core Modules

### 1. UI Layer

#### window.py & window.blp
**Main application container.**

Responsibilities:
- Tab container with 4 pages
- Task panel at bottom
- Window geometry persistence
- Global hotkeys and actions
- Brewfile open tracking (prevents duplicates)

**Key state:**
- `_page_tabs` — Page name to widget mapping
- `_open_brewfiles` — Dict of page_name → normalized file paths
- `backend` — Reference to BrewBackend
- `task_manager` — Reference to TaskManager

**Timing:** Window.__init__ is fully instrumented (9 timing points)

#### Pages
- **browse_page.py / browse-page.blp** — Browse all packages by tap
- **search_page.py / search-page.blp** — Full-text search
- **installed_page.py / installed-page.blp** — Installed packages
- **brewfile_page.py / brewfile-page.blp** — Brewfile contents (per-tap sections)

**Common pattern:**
```python
class NamePage(Adw.Bin):
    def __init__(self):
        super().__init__()
        self.backend = ...           # Reference to backend
        self.task_manager = ...      # For async operations
        
    def populate(self):
        """Load and render page contents."""
        ...
```

#### Package Tiles
- **package_tile.py / package-tile.blp** — Individual package display
- **package_rich_tile.py / package-rich-tile.blp** — Detailed package view

**Types supported:**
- `formula` — Standard Homebrew package
- `cask` — GUI application
- `flatpak` — Sandbox application (Flathub)

### 2. Backend Layer

#### backend.py
**All data access and external integrations.**

Key classes:
- `Package` — Data class for a single package (name, type, version, homepage, etc.)
- `BrewBackend` — Main backend interface

Key methods:
- `load_all_async()` — Background load of all packages
- `parse_brewfile(path)` — Parse .Brewfile file
- `get_flatpak_info(app_id)` — Query Flathub appstream API
- `run_command(cmd)` — Execute brew CLI commands
- `search(query)` — Full-text package search

**External APIs:**
- `${brew} list` — Get installed packages
- `${brew} search` — Search packages
- `https://flathub.org/api/v2/appstream/{app_id}` — Flathub metadata
- File I/O — Read Brewfiles

**Caching:**
- `~/.cache/tavern/formulae.json` — Cached formulae list
- `~/.cache/tavern/casks.json` — Cached cask list
- `~/.cache/tavern/icons/` — Downloaded package icons

#### Task Management

**task_manager.py / TaskManager**

Async operation queue with progress tracking.

Methods:
- `enqueue(task, callback)` — Add operation to queue
- `Task.cancel()` — Cancel running task

Behavior:
- Runs tasks serially (one at a time)
- Updates progress bar and status text
- Logs to task panel widget
- Persists 5 most recent tasks

#### Logging & Profiling

**logging_util.py**

Core infrastructure:
- `get_logger(name)` — Module logger factory
- `@profile` — Function timing decorator
- `log_timing(label, category)` — Block timing context manager
- `init_logging()` — Initialization

### 3. Desktop Integration

#### Application Entry Point
**application.py / Tavern**

- GTK application singleton
- Command-line argument parsing (sys.argv direct)
- D-Bus search provider registration
- Window lifecycle management

Command-line support:
```bash
tavern --brewfile=/path/to/file.Brewfile
tavern --package=formula_name
```

#### Search Provider
**search_provider.py**

D-Bus integration with GNOME Shell search.

- Implements `org.gnome.Shell.SearchProvider2` interface
- Indexes packages for shell integration
- File: `shell-search-provider-dbus-interfaces.xml`

## Adding Features

### Example: Add new package field
1. Update `Package` class in `backend.py`:
   ```python
   @dataclass
   class Package:
       name: str
       type: str  # formula, cask, flatpak
       version: str
       homepage: str
       NEW_FIELD: str = ""  # Add here
   ```

2. Update parsing in `parse_brewfile()`:
   ```python
   if "new_field" in brew_data:
       pkg.new_field = brew_data["new_field"]
   ```

3. Render in package tile:
   - Update `.blp` file with new widget
   - Update `.py` file to populate it

4. Test in `tests/test_backend.py`

### Example: Add new page
1. Create `src/new_page.py` subclassing `Adw.Bin`
2. Create `src/new-page.blp` with UI definition
3. Add to window in `window.py`:
   ```python
   tab = Gtk.Box()
   tab.append(NewPage())
   self._page_tabs["new"] = tab
   ```
4. Update meson.build if adding new `.blp` file

### Example: Integrate new external service
1. Add query method to `BrewBackend`:
   ```python
   def get_service_data(self, query):
       """Fetch from external service."""
       response = http.get(f"https://api.example.com/{query}")
       return parse_response(response)
   ```

2. Call from UI:
   ```python
   def on_search(self, query):
       self.task_manager.enqueue(
           Task(self.backend.get_service_data, query),
           self.on_results
       )
   ```

3. Add error handling and logging

## Brewery File Format (.Brewfile)

**Supported entries:**

```brewfile
# Homebrew taps (required for most packages)
tap "homebrew/cask"
tap "ublue-os/tap"

# Standard packages (binaries)
brew "git"
brew "python"

# GUI applications (macOS concept, works on Linux with Homebrew)
cask "google-chrome"
cask "spotify"

# Flatpak applications (Linux-specific)
flatpak "org.mozilla.firefox"
flatpak "com.github.flatscan.Flatscan"
```

**Parser location:** `backend.parse_brewfile(path)`

Returns:
```python
{
    "taps": ["homebrew/cask", "ublue-os/tap"],
    "formulae": [Package(...), ...],
    "casks": [Package(...), ...],
    "flatpaks": [Package(...), ...]
}
```

**Flathub integration:** For each flatpak entry, queries appstream API:
```
GET https://flathub.org/api/v2/appstream/{app_id}
```

Retrieves: metadata, icon URL, homepage, description

## UI Patterns

### Page Structure
Every page follows this pattern:
```python
class NamePage(Adw.Bin):
    def __init__(self, backend, task_manager):
        super().__init__()
        self.backend = backend
        self.task_manager = task_manager
        # Load template from .blp file
        
    def populate(self):
        """Called when page becomes visible."""
        # Load data asynchronously
        task = Task(self.backend.method, args)
        self.task_manager.enqueue(task, self._on_loaded)
        
    def _on_loaded(self, task):
        """Callback when data is ready."""
        # Update UI with results
```

### Package Display
Tile widgets render package info:
- **Name and version**
- **Icon** (from Homebrew/Flathub)
- **Description** (from homepage/appstream)
- **Install button** (if not installed)
- **Badge** (type: formula/cask/flatpak)

**Styling:** `src/style.css`

### Async Operations
All I/O uses `TaskManager`:
```python
def load_stuff(self):
    task = Task(
        self.backend.slow_method,
        arg1, arg2
    )
    self.task_manager.enqueue(task, self.on_complete)
    
def on_complete(self, task):
    if task.result:
        self.display_results(task.result)
    else:
        self.show_error(task.error)
```

## Testing

### Unit Tests
Location: `tests/`

**Files:**
- `test_backend.py` — Backend logic
- `test_search_provider.py` — Search indexing
- `test_task_manager.py` — Async queue
- `test_logging_util.py` — Logging
- `conftest.py` — Shared fixtures

**Pattern:**
```python
def test_parse_brewfile(tmp_path):
    """Test parsing a real Brewfile."""
    brewfile = tmp_path / "test.Brewfile"
    brewfile.write_text("""
        tap "homebrew/cask"
        brew "git"
        cask "spotify"
        """)
    
    result = backend.parse_brewfile(str(brewfile))
    assert len(result["formulae"]) == 1
    assert len(result["casks"]) == 1
```

Running:
```bash
pytest tests/
pytest tests/test_*.py -v
TAVERN_LOG=debug pytest tests/ -s
```

## Performance Tips

### Load UI templates early
Blueprint compilation happens at build time. At runtime, `Gtk.Builder` loads `.ui` files.

### Use background tasks for I/O
Never block the UI thread on network, file, or subprocess operations.

```python
# ❌ DO NOT:
packages = subprocess.run(["brew", "list"]).stdout.decode()

# ✅ DO:
def load_packages_thread():
    return subprocess.run(["brew", "list"]).stdout.decode()

task = Task(load_packages_thread)
self.task_manager.enqueue(task, self.on_packages_loaded)
```

### Cache aggressively
- Flathub icons → `~/.cache/tavern/icons/`
- Formulae list → `~/.cache/tavern/formulae.json`
- Search index → In-memory hash with mtime check

### Profile before optimizing
Use environment variables:
```bash
TAVERN_LOG=info TAVERN_PROFILE=1 ./run.sh
```

See [profiling.md](profiling.md) for details.

## Code Style

- **Python 3.12** — Type hints required
- **Formatting:** 4-space indents, black-compatible
- **Modules:** One class per file (mostly)
- **Naming:** snake_case for methods/vars, CapsCase for classes
- **Comments:** Docstrings on classes and complex methods

Example:
```python
class MyPage(Adw.Bin):
    """Display a list of packages."""
    
    def __init__(self, backend: BrewBackend):
        super().__init__()
        self.backend = backend
        
    def populate(self) -> None:
        """Load and render this page's contents."""
        task = Task(self.backend.list_packages)
        self.task_manager.enqueue(task, self._on_packages)
```

## Dependencies (Flatpak)

Managed in `dev.hanthor.Tavern.json`:

- **Runtime:** freedesktop 23.08 (GTK4, Python, etc.)
- **Build tools:** blueprint-compiler, meson, pkg-config
- **Python packages:** via pip (requests, etc.)

To add a new dependency:
1. Update `pyproject.toml` or `dev.hanthor.Tavern.json`
2. Rebuild: `just build`
3. Test: `just run`
