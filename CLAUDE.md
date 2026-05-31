# Tavern — Developer Guide

Tavern is a GTK 4 / Libadwaita Homebrew client for Linux, written in Python with Blueprint UI definitions.

## Quick Start

```bash
./run.sh                  # build + install to ~/.local + launch
TAVERN_LOG=debug ./run.sh  # same with verbose logging
```

## Project Layout

```
src/
  main.py                 # entry point + startup timing
  application.py          # GtkApplication singleton, CLI arg parsing
  window.py               # main window — wires all pages together
  window.blp              # main window Blueprint (header, ViewStack, breakpoints)
  backend.py              # ALL homebrew I/O: formulae API, tap scanning, install/remove/upgrade
  tap_page.py / .blp      # Taps browser + add/remove tap management
  browse_page.py / .blp   # Browse curated packages
  search_page.py / .blp   # Search across formulae + casks
  installed_page.py / .blp# Installed packages + updates card
  brewfile_page.py / .blp # Brewfile viewer (dynamically added as tabs)
  package_tile.py / .blp  # Reusable package tile widget
  package_details.py / .blp # Detail page pushed onto NavigationView
  task_manager.py         # Coordinates parallel install/remove/upgrade operations
  task_panel.py / .blp    # Task progress sheet
  logging_util.py         # Zero-overhead logging (off by default)
  style.css               # Custom Libadwaita overrides
  tavern.gresource.xml     # Resource bundle manifest (add .ui files here)
  meson.build             # Build: blueprint → .ui, compile resources, install .py
```

## Architecture

### UI Layer → Backend

All pages receive `BrewBackend` via `set_backend()`. They connect to GObject signals:

| Signal | Emitted by | Consumed by |
|--------|-----------|-------------|
| `formulae-loaded` | backend | browse, search, installed, window |
| `casks-loaded` | backend | browse, search, installed, window |
| `taps-loaded` | backend | tap_page |
| `installed-loaded` | backend | window |
| `outdated-changed` | backend | installed_page |
| `operation-complete` | backend | task_manager |
| `operation-output` | backend | task_panel |

### Navigation Model

```
Adw.ApplicationWindow
└── Adw.ToastOverlay
    └── Adw.NavigationView          ← root nav stack
        └── Adw.NavigationPage "main"
            └── Adw.ToolbarView
                ├── [top] Adw.HeaderBar (ViewSwitcher wide mode)
                ├── [bottom] Adw.ViewSwitcherBar (revealed on narrow screens)
                └── Adw.ViewStack main_stack
                    ├── Browse
                    ├── Taps
                    ├── Search
                    └── Installed
```

Package details are pushed as `Adw.NavigationPage` onto the root `Adw.NavigationView`.

Brewfile tabs are added dynamically to `main_stack` via `window.open_brewfile()`.

### Tap Data Flow

1. `backend.load_all_async()` starts two threads: API fetch + tap scan
2. `_load_tap_packages()` walks `$HOMEBREW_PREFIX/Library/Taps/` (no CLI calls — fast)
3. Emits `taps-loaded` with `{tap_name: [Package, ...]}` for non-core taps
4. `TavernTapPage` renders a sidebar list and a package grid for the selected tap
5. Add Tap → `Adw.AlertDialog` → `backend.tap_async()` → `brew tap user/repo`
6. Remove Tap → confirmation dialog → `backend.untap_async()` → `brew untap`

## Adding a New Page

1. Create `src/my-page.blp` (template `$TavernMyPage: Adw.Bin`)
2. Create `src/my_page.py` (class `TavernMyPage`, import + register GType)
3. Add import to `window.py` (before template is parsed)
4. Add `Adw.ViewStackPage` to `window.blp`
5. Add `my_page = Gtk.Template.Child()` to `TavernWindow`
6. Register `.blp` in `src/meson.build` (blueprints list)
7. Register `.ui` in `src/tavern.gresource.xml`
8. Add `my_page.py` to `tavern_sources` in `src/meson.build`

## Blueprint → .ui → GResource

Blueprint files (`.blp`) compile to `.ui` XML at build time via `blueprint-compiler batch-compile`. The `.ui` files are bundled into `tavern.gresource` and loaded at runtime via resource paths like `/dev/hanthor/Tavern/my-page.ui`.

**Always rebuild after changing `.blp` files:**
```bash
./run.sh     # runs meson compile which re-runs blueprint-compiler
```

## Logging & Debugging

```bash
TAVERN_LOG=info ./run.sh          # info-level output to console
TAVERN_LOG=debug ./run.sh         # verbose: every fetch, cache hit, signal
TAVERN_PROFILE=1 TAVERN_LOG=info ./run.sh  # function-level timing
TAVERN_LOG_FILE=/tmp/p.log ./run.sh       # also write to file
```

All logging is **off by default** — zero overhead in production.

## Testing

```bash
pytest tests/                              # full suite
pytest tests/test_backend.py -v           # specific file
TAVERN_LOG=debug pytest tests/ -s          # with logging
```

## C vs Python — Why We Stay in Python

Bazaar (our UI reference) is written in C. We stay in Python because:

- **The UI quality is determined by Blueprint + Libadwaita** — the `.blp` files are identical across C and Python
- Switching would be a complete rewrite with no user-visible benefit
- PyGObject gives full access to every GTK/Libadwaita API
- Python is significantly faster to iterate on (no compile step, readable tracebacks)
- Memory safety is not a concern for a single-user desktop app that doesn't handle untrusted data

When performance matters (Homebrew API fetches, tap scanning), we use background threads and GLib.idle_add for UI callbacks — exactly the same pattern C would use.

## Key Patterns

### Adding a backend operation

```python
# In backend.py
def my_op_async(self, arg, callback=None):
    thread = threading.Thread(target=self._my_op_thread, args=(arg, callback), daemon=True)
    thread.start()

def _my_op_thread(self, arg, callback):
    # … do work …
    GLib.idle_add(callback, result)
```

### Connecting a new signal to a page

```python
# In window.py __init__, after set_backend()
self.my_page.connect('some-signal', self._on_some_signal)

def _on_some_signal(self, page, data):
    self.toast_overlay.add_toast(Adw.Toast.new('Done!'))
```

### Emitting a toast from a page

Pages should emit a signal (e.g. `tap-operation`) carrying the message string. `window.py` connects it and calls `toast_overlay.add_toast()`. Pages must not hold a reference to the window.

## Bazaar UI Alignment

Reference: `/var/home/james/dev/bazaar/src/`

Key elements we mirror from Bazaar:
- `Adw.ViewSwitcher` in header (wide) + `Adw.ViewSwitcherBar` at bottom (narrow)
- `Adw.Breakpoint` on `Adw.ApplicationWindow` to switch between them at 550sp
- `card` + `flat` CSS classes on package tiles
- `icon-dropshadow` CSS class on package icons
- `Adw.StatusPage` for empty states
- `Adw.NavigationView` for detail push/pop

Things Bazaar has that Tavern intentionally omits:
- Flatpak / polkit / auth (Homebrew runs as user, no sandboxing needed)
- Curated JSON config (we use hardcoded popular lists for now)
- D-Bus backend isolation (not needed at Tavern's scale)
