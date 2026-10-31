# Contributing to Tavern

Thanks for your help! Tavern is a GTK 4 / Libadwaita Homebrew client, written in Python with Blueprint UI definitions.

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

**[Donate time with your AI CLI](https://hub.tunaos.org/#contribute).**

Your machine runs one task at a time using your signed-in AI coding CLI.
The relay alternates between eligible **School** (OS) and **Reef** (apps)
hives after each task. If one hive has no work, the other can continue.

The guide covers prerequisites, verified `just` setup, credentials, provider
costs, and how to stop with Ctrl+C. Your subscription quota or API charges apply.
Never post account credentials or API keys in issues or pull requests.

## Dev setup

Install build dependencies (Homebrew on Linux or macOS):

```bash
brew install gtk4 libadwaita meson ninja pygobject3 gettext desktop-file-utils blueprint-compiler
```

Build, install to `~/.local`, and launch:

```bash
./run.sh                  # normal run
TAVERN_LOG=debug ./run.sh # with verbose logging
```

### Development profile (side-by-side installs)

Build with the development profile to run both development and release versions simultaneously:

```bash
meson setup builddir -Dprofile=development
meson compile -C builddir
meson install -C builddir
```

The development profile changes the application ID to `org.tunaos.tavern.Devel`. The app then appears as a separate entry in the launcher and in settings. You can test a release build and develop against `main` at the same time.

For a Flatpak build in a sandbox (needs [`just`](https://github.com/casey/just)):

```bash
just dev                  # build + install + run as Flatpak (development profile)
```

## Tests

Use the system Python with its PyGObject bindings. A separate Python install
such as `actions/setup-python` cannot use the distribution's `python3-gi`.
On Ubuntu, install the same dependencies as CI:

```bash
sudo apt-get update
sudo apt-get install -y python3-gi python3-gi-cairo python3-pip \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 \
  libglib2.0-dev-bin libxml2-utils blueprint-compiler xvfb dbus-x11
/usr/bin/python3 -m pip install --break-system-packages -r requirements-test.txt
```

`requirements-test.txt` pins the same compatible pytest and pytest-benchmark
versions for the host, CI sandbox, and local script for Flatpak tests. Update them
together: pytest-benchmark 5.3.0 supports pytest 9.1.1, but its fixture uses
`Node._nodeid`, which pytest 9.2 removed.

Build the UI resource at the exact path that `tests/conftest.py` loads:

```bash
mkdir -p build-ui .flatpak-build/files/share/tavern
blueprint-compiler batch-compile build-ui src src/*.blp
cp src/style.css build-ui/
glib-compile-resources \
  --target=.flatpak-build/files/share/tavern/tavern.gresource \
  --sourcedir=build-ui --sourcedir=src src/tavern.gresource.xml

xvfb-run -a dbus-run-session -- /usr/bin/python3 -m pytest tests/ -m "not slow"
/usr/bin/python3 -m pytest tools/tests/
```

Use a file path in place of `tests/` to run one file. Add `--benchmark-enable`
to run benchmarks, though the plugin is required even when benchmarks are off.
GTK needs a display and session bus; the fixtures alone do not provide these.
The host job may skip tests that need `Adw.Spinner` (libadwaita 1.6 or later).
Both the host and GNOME 50 Flatpak test jobs must pass before merge.
Use `just dev` for the separate Flatpak development path.

## Working on the UI

Blueprint files (`.blp`) compile to `.ui` XML at build time via `blueprint-compiler`. Always rebuild after you edit a `.blp`:

```bash
./run.sh                  # re-runs blueprint-compiler
```

When adding a page, keep Blueprint, Python, window wiring, gresource registration, and meson sources in sync — README.md and `src/` show where each piece lands.

### Localization

Wrap every user-visible Blueprint value in `_()`, for example
`label: _("Install");`, and add new Blueprint/Python sources to
`po/POTFILES.in`. Python UI strings should use `gettext.gettext` (`_`) or
`ngettext` for plurals. Before you open a PR, run:

```bash
python3 tools/check-translations.py
meson setup build
meson compile -C build tavern-pot
```

Add a locale code to `po/LINGUAS` only when its `.po` catalog is ready to
ship. Translation-only PRs are welcome and do not need changes to Python.

Additional maintainer guides cover the [cache lifecycle](docs/CACHE.md),
[curation feed](docs/CURATION.md), [accessibility release pass](docs/ACCESSIBILITY.md),
[release process](docs/RELEASING.md), and [architecture overview](docs/ARCHITECTURE.md).

The files under [`docs/reports/`](docs/reports/README.md) are dated historical
verification snapshots, not maintained contributor instructions.

## Pull requests

- Keep PRs focused — one change, one PR.
- Include a screenshot or short clip for any user-visible UI change.
- Run the test commands above before you open a PR.
- Reference the issue to close (`Closes #123`).

## Debugging

Use environment variables to turn on debug logging and check performance:

```bash
# Turn on debug logging to see what is happening
TAVERN_LOG=debug ./run.sh

# Check how fast the app runs
TAVERN_PROFILE=1 ./run.sh

# Save logs to a file to read later
TAVERN_LOG_FILE=/tmp/tavern.log TAVERN_LOG=debug ./run.sh

# Use logging and speed checks at the same time
TAVERN_LOG=debug TAVERN_PROFILE=1 ./run.sh
```

Logging is off by default. Use the variables above to turn it on. You can set `TAVERN_LOG` to `info` or `debug`. Use `debug` to see more.

## Code style

- Match the local style — Tavern is a small codebase, consistency matters more than any specific rule.
- Logging is off by default. New code should use `_log = get_logger('module_name')` from `logging_util`, not bare `print`.
- Backend I/O goes on a thread and reports back via `GLib.idle_add` — don't block the UI thread.

## Project docs

- [README.md](README.md) — user-facing docs.
- [ROADMAP.md](ROADMAP.md) — what's planned.
