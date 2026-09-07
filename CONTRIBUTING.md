# Contributing to Tavern

Thanks for wanting to help! Tavern is a GTK 4 / Libadwaita Homebrew client written in Python with Blueprint UI definitions.

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

For a sandboxed Flatpak build (requires [`just`](https://github.com/casey/just)):

```bash
just dev                  # build + install + run as Flatpak
```

## Tests

The host test suite uses the system Python because the distro's PyGObject
bindings are not visible to a separate Python installation. On Ubuntu, install
the test and UI compilation prerequisites first:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  python3-gi python3-gi-cairo \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 \
  libglib2.0-dev-bin libxml2-utils blueprint-compiler xvfb dbus-x11
python3 -m pip install --break-system-packages pytest pytest-benchmark
```

Compile the Blueprint UI and resource bundle to the path loaded by
`tests/conftest.py`, then run the tests with a display and session bus:

```bash
mkdir -p build-ui .flatpak-build/files/share/tavern
blueprint-compiler batch-compile build-ui src src/*.blp
cp src/style.css build-ui/
glib-compile-resources \
  --target=.flatpak-build/files/share/tavern/tavern.gresource \
  --sourcedir=build-ui --sourcedir=src src/tavern.gresource.xml

xvfb-run -a dbus-run-session -- \
  python3 -m pytest tests/ -m "not slow"                    # host suite
xvfb-run -a dbus-run-session -- \
  python3 -m pytest tests/test_backend.py -v                 # one file
xvfb-run -a dbus-run-session -- \
  python3 -m pytest tests/test_benchmarks.py --benchmark-enable
```

Tests run headlessly — the autouse fixtures in `tests/conftest.py` mock `Gio.Settings` and dialog `.present()` calls so nothing pops on screen. If you add new dialog types, extend that fixture.

The `pytest-flatpak` CI job also runs the suite inside the GNOME 50 SDK. Use
`just dev` for interactive Flatpak development; the complete sandboxed test
sequence is maintained in `.github/workflows/tests.yml`.

## Working on the UI

Blueprint files (`.blp`) compile to `.ui` XML at build time via `blueprint-compiler`. Always rebuild after editing a `.blp`:

```bash
./run.sh                  # re-runs blueprint-compiler
```

When adding a new page, keep Blueprint, Python, window wiring, gresource registration, and meson sources in sync — the repo layout in [README.md](README.md) and `src/` shows where each piece lands.

### Localization

Wrap every user-visible Blueprint value in `_()`, for example
`label: _("Install");`, and add new Blueprint/Python sources to
`po/POTFILES.in`. Python UI strings should use `gettext.gettext` (`_`) or
`ngettext` for plurals. Before opening a PR, run:

```bash
python3 tools/check-translations.py
meson setup build
meson compile -C build tavern-pot
```

Add a locale code to `po/LINGUAS` only when its `.po` catalog is ready to
ship. Translation-only PRs are welcome and do not require changes to Python.

Additional maintainer guides cover the [cache lifecycle](docs/CACHE.md),
[curation feed](docs/CURATION.md), [accessibility release pass](docs/ACCESSIBILITY.md),
and [release process](docs/RELEASING.md).

The files under [`docs/reports/`](docs/reports/README.md) are dated historical
verification snapshots, not maintained contributor instructions.

## Pull requests

- Keep PRs focused — one change, one PR.
- Include a screenshot or short clip for any user-visible UI change.
- Run `python3 -m pytest tests/` locally before opening.
- Reference the issue you're closing (`Closes #123`).

## Code style

- Match the surrounding style — Tavern is a small codebase, consistency matters more than any specific rule.
- Logging is off by default. New code should use `_log = get_logger('module_name')` from `logging_util`, not bare `print`.
- Backend I/O goes on a thread and reports back via `GLib.idle_add` — don't block the UI thread.

## Project docs

- [README.md](README.md) — user-facing docs.
- [ROADMAP.md](ROADMAP.md) — what's planned.
