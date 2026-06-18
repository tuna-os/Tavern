# Tavern — Developer Guide

Tavern is a GTK 4 / Libadwaita Homebrew client for Linux, written in Python with Blueprint UI definitions.

## Quick Start

```bash
./run.sh                  # build + install to ~/.local + launch
TAVERN_LOG=debug ./run.sh  # same with verbose logging
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

**Always rebuild after changing `.blp` files:** `./run.sh` runs meson compile which re-runs blueprint-compiler.

## Logging & Debugging

```bash
TAVERN_LOG=info ./run.sh          # info-level output to console
TAVERN_LOG=debug ./run.sh         # verbose: every fetch, cache hit, signal
TAVERN_PROFILE=1 TAVERN_LOG=info ./run.sh  # function-level timing
TAVERN_LOG_FILE=/tmp/p.log ./run.sh       # also write to file
```

All logging is **off by default** — zero overhead in production.

## C vs Python — Why We Stay in Python

Bazaar (our UI reference) is written in C. We stay in Python because:

- **The UI quality is determined by Blueprint + Libadwaita** — the `.blp` files are identical across C and Python
- Switching would be a complete rewrite with no user-visible benefit
- PyGObject gives full access to every GTK/Libadwaita API
- Python is significantly faster to iterate on (no compile step, readable tracebacks)
- Memory safety is not a concern for a single-user desktop app that doesn't handle untrusted data

When performance matters (Homebrew API fetches, tap scanning), we use background threads and GLib.idle_add for UI callbacks — exactly the same pattern C would use.

## Don'ts

- **Don't rewrite in C.** There is no user-visible benefit. This decision is final.
- **Don't hold window references in pages.** Pages should emit signals carrying the message string; window.py connects them and calls `toast_overlay.add_toast()`.
- **Don't emit toasts directly from pages.** Use the signal-to-window pattern above.
- **Don't use sudo for build/test.** Tavern runs rootless.
- **Don't skip rebuilding after `.blp` changes.** Blueprint → .ui compilation is not automatic.

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

## Agent skills

### Issue tracker

GitHub Issues on `hanthor/Tavern`. See `docs/agents/issue-tracker.md`.

### Triage labels

Defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`CONTEXT.md` + `docs/adr/` at repo root). See `docs/agents/domain.md`.
