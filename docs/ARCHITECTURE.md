# Architecture overview

Tavern is a Homebrew client for Linux and macOS. It is a GTK 4 and
Libadwaita desktop app in Python. We ship it as the `org.tunaos.tavern`
Flatpak and as a Homebrew cask. This document shows the layers of the code,
the threads that do the work, and the flow of data from Homebrew to the
screen.

Other documents give more data:

- [`CACHE.md`](CACHE.md): the cache lifecycle
- [`CURATION.md`](CURATION.md): the curation feed
- [`ACCESSIBILITY.md`](ACCESSIBILITY.md): the accessibility release pass
- [`RELEASING.md`](RELEASING.md): the release process
- [`adr/`](adr/): the design decisions

## System overview

```
                         GTK 4 / Libadwaita UI (main thread)
   window.py  browse/search/installed/tap/doctor/brewfile pages
   page_factory.py  package_details.py  task_panel.py  …
        │  GObject signals: formulae-loaded, casks-loaded, installed-loaded,
        │  taps-loaded, outdated-changed, pinned-changed
        │  property bindings: loading_status, loading_progress
        ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  BrewBackend (GObject): the shared facade                      │
   │  mixins: Taps · Media · Cache · Remote · State · Ui            │
   │  CatalogStore: catalog and package state                       │
   └───┬───────────────┬───────────────┬───────────────┬───────────┘
       │               │               │               │
   subprocess        network        filesystem      GObject
   (brew CLI)        (urllib)       (JSON cache)    properties
       │               │               │               │
       ▼               ▼               ▼               ▼
   local `brew`    formulae.brew.sh  $XDG_CACHE_HOME/  signals and
                   Flathub, GitHub   tavern/*.json     GLib.idle_add
                   curation feed
```

The backend is the only layer that runs `brew`, uses the network, or writes
the cache. The UI calls a backend method. Then it uses the signal or the
callback that gives the result.

## Layers

**UI.** The pages, `window.py`, and `package_details.py` show data, get user
input, and control navigation. They do not block the main thread. Each long
operation is an asynchronous backend method. The pages bind widgets to
backend properties (`loading_status`, `loading_progress`) and to the task
properties of each `Package`. Pages send signals such as `package-activated`
and `install-requested`. The window connects these signals to the backend and
to other pages.

**Page construction.** `PageFactory` (`page_factory.py`) makes each page and
dialog and gives it the shared `backend` and `task_manager`. The window does
not call page constructors. Refer to
[ADR-0002](adr/0002-page-factory.md).

**Backend lifecycle.** `BackendLifecycle` (`backend_lifecycle.py`) controls
the initial and manual catalog loads, the periodic outdated check, and the
refresh of installed state after the task queue drains. It takes the shared
backend, task manager, and settings, and it does not use widgets. The window
connects its view callbacks before it starts the lifecycle. On close, the window
stops the lifecycle to release the timer and the task subscription; package
operations in progress continue. Navigation and task feedback stay in the window.

**Deep links.** `DeepLinkRouter` (`deeplink_router.py`) resolves package and tap
targets against the current catalog. It retries unresolved targets as data arrives
and opens a queued Brewfile after the catalog loads. It has no widget imports.
View callbacks show packages, select taps, report misses, and show choices of
qualified taps. `tap_choice_dialog.py` renders those choices and returns a selected
qualified name to the router, which queues the install through an injected action.

**Backend.** `BrewBackend` does all I/O. It is the source of truth for the
catalog, the installed packages, the taps, and the outdated packages. It is a
GObject, thus pages can bind to its properties and connect to its signals. It
has synchronous methods for tests and the Brewfile loader, and `*_async`
methods for the UI.

**Policy modules.** `catalog_policy.py`, `cache_policy.py`, and
`brew_commands.py` hold rules without UI state: catalog validation, search
rank, cache TTLs, and `brew` subcommands. `brew_env.py` makes each `brew`
command line. In the Flatpak, it runs `brew` on the host through
`flatpak-spawn --host` and quotes each argument.

## Main parts

### Mixins

`BrewBackend` gets its methods from mixins
([`src/backend.py`](../src/backend.py)):

```python
class BrewBackend(TapsMixin, MediaMixin, CacheMixin,
                  RemoteMixin, StateMixin, UiMixin, GObject.Object):
```

Each mixin is a plain class for one concern. The mixins do not import
`backend.py`. A test (`tests/test_dependency_boundaries.py`) makes sure of
this. `backend_icons.py` is a pure ICO to PNG decoder without backend state.

### CatalogStore

`CatalogStore` (`catalog_store.py`) owns the catalog, the installed, pinned,
and outdated sets, and the tap data. A re-entrant lock in the store protects
this data.
`BrewBackend` has properties that send each read and write to the store, so
the mixins keep their attribute names.

### GObject contract

`BrewBackend` is a `GObject.Object`. The UI binds widgets to its properties
(`loading`, `loading_status`, `loading_progress`). Its signals
(`formulae-loaded`, `casks-loaded`, `installed-loaded`, `taps-loaded`,
`outdated-changed`, `pinned-changed`) send the data to the pages.

### Package model

`Package` (`package.py`) is a `GObject.Object` that each page uses as a row.
It holds one formula or cask record from the API. It also holds the task
state (`task_active`, `task_progress`, `task_label`) that `TaskManager`
sets. Pages show `Package` objects. They do not read raw API data.

### Operations

`TaskManager` ([`src/task_manager.py`](../src/task_manager.py)) controls
install, remove, and upgrade. The window and all pages use one
`TaskManager`. It runs `brew` on a worker thread. It changes the `brew` output
into phases that the user can read, and it sets the progress bar of each
`Package`.

On successful install, upgrade, or removal, `TaskManager` records
the package through `BrewBackend.set_package_installed()`. The backend owns
that state through its `CatalogStore`, so `TaskManager` does not mutate the
backend's private catalog sets. When the task queue drains, `BackendLifecycle`
calls `backend.refresh_installed_async()` after view callbacks have had a
chance to queue follow-up work.

### Media URLs

Package metadata gives the URLs for icons, screenshots, and READMEs.
`url_security.py` examines each URL before `media.py` gets it. It accepts
only HTTPS on port 443 to public addresses. It also examines each redirect.

## Threads

The main thread of GTK draws the UI. Operations that block run on other
threads.
Each result goes back to the main thread through `GLib.idle_add`.

- **Catalog load.** `load_all_async()` starts a thread. This thread reads the
  installed packages and loads the cache. Then it gets new catalog data from
  the API, reads the taps, and makes the search index. It shows progress
  through `loading_progress` and `loading_status`.
- **Search.** `search_async()` sends each query to a single-thread executor
  with a generation number. If a newer query comes first, Tavern discards the
  old result (#49).
- **Icons.** `fetch_icon_async()` uses a pool of 6 workers. If two requests
  are for the same package, Tavern downloads the icon one time.
- **Cache refresh.** `TavernApplication` starts a refresh thread 10 seconds
  after start, and then each 2 hours.
- **Tasks.** Each `*_async` task method (install, tap, pin, and others)
  starts a thread. It sends the result to a callback on the main loop.

Locks protect the data that threads share. `_refresh_lock` lets only one catalog refresh
run at a time. The `CatalogStore` lock protects the catalog and package
state. `_icon_lock` protects the map of icon downloads in progress.

## Modules

| File | Layer | Contents |
| --- | --- | --- |
| `main.py` | entry point | Loads the gresource bundle, then starts `TavernApplication`. |
| `application.py` | application | The `Adw.Application`, command-line and `brew://` links, the GNOME search action, and the cache refresh thread. |
| `window.py` | UI | `TavernWindow`. It owns `BrewBackend` and `TaskManager`, connects page signals, and shows toasts and badges. |
| `backend_lifecycle.py` | coordination | Catalog loading, periodic outdated checks, and refresh after tasks finish. |
| `deeplink_router.py` | coordination | Widget-free package/tap lookup, pending deep links, and qualified tap selection. |
| `tap_choice_dialog.py` | UI | Renders qualified tap choices and returns the selection to the router. |
| `page_factory.py` | UI | `PageFactory`. It makes pages and dialogs with their dependencies. |
| `package_details.py` | UI | Package presentation and user actions; delegates asset requests, README transforms, and task signal lifecycle. |
| `asset_loader.py` | UI/backend boundary | Coordinates icon and screenshot requests and drops stale page callbacks. |
| `readme_renderer.py` | presentation | Pure README preview, HTML, base-URI, and install-count transformations. |
| `task_binding.py` | operations/UI boundary | Owns task signal connection lifecycle for package details. |
| `backend.py` | backend | The `BrewBackend` facade. |
| `catalog_store.py` | backend | `CatalogStore`. It owns catalog and package state. |
| `backend_ui.py` | backend | `UiMixin`: catalog load, search, and progress properties. |
| `backend_remote.py` | backend | `RemoteMixin`: catalog, detail, and analytics data from the API, curation, and version history. |
| `backend_cache.py` | backend | `CacheMixin`: the local cache, the Homebrew JWS cache, Brewfile parse, and the Linux cask filter. |
| `backend_state.py` | backend | `StateMixin`: installed, outdated, and pinned state from the `brew` CLI. |
| `backend_icons.py` | backend | ICO to PNG decoder. |
| `media.py` | backend | `MediaMixin`: icons, screenshots, and READMEs, with download size limits. |
| `url_security.py` | backend | The URL check for media downloads. |
| `taps.py` | backend | `TapsMixin`: tap scan, trust, and operations, and the popular taps. |
| `package.py` | model | `Package`: the shared formula or cask row. |
| `task_manager.py` | operations | `TaskManager`: install, remove, and upgrade. |
| `catalog_policy.py` | policy | Catalog validation and search rank. |
| `cache_policy.py` | policy | Atomic JSON cache files, TTLs, and eviction. |
| `brew_commands.py` | policy | Read-only `brew` subcommands. |
| `brew_env.py` | platform | Flatpak and `brew` detection, PATH ordering policy (Bluefin parity), missing-Homebrew install commands, and `brew` subprocess construction. |
| `search_provider.py` | integration | GNOME Shell search through D-Bus, from the cached `linux_packages.json`. |
| `git_forge.py` | backend | Finds GitHub, GitLab, or Codeberg from a source URL for the version history. |

## Data flow: open a package

1. The UI calls `backend.search_async()` or a browse page method. The rows
   come in `formulae-loaded` and `casks-loaded`.
2. When the user opens a row, `PageFactory` makes the package details page.
   The window pushes it onto the `navigation_view`.
3. A worker thread gets the details from the formula or cask API
   (`get_package_info_async`). The icon, screenshot, and README come through
   `MediaMixin` callbacks. The analytics and related packages come from
   `RemoteMixin`.
4. An install goes through `TaskManager`. It sends the `brew` output to the
   progress bar. When the queue drains, `BackendLifecycle` refreshes installed state;
   the pages and window update the installed packages and outdated badge.
