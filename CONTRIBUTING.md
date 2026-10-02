# Contributing to Tavern

Thank you for your help. Tavern is a GTK 4 application. It is a Homebrew client for Libadwaita. You write it in Python with Blueprint UI definitions.

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

The development profile changes the application ID to `org.tunaos.tavern.Devel`. It appears separately in your system's application launcher and settings. You can test a release build. You develop against `main` at the same time.

For a sandboxed Flatpak build (needs [`just`](https://github.com/casey/just)):

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
/usr/bin/python3 -m pip install --break-system-packages pytest pytest-benchmark
```

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

Use a file path in place of `tests/` to run one file. Add `--benchmark-enable` to run benchmarks. The benchmark plugin is required even when benchmarks are off. GTK needs a display and session bus. The fixtures alone do not provide these. The host job may skip tests that need `Adw.Spinner` (libadwaita 1.6 or later). Both the host and GNOME 50 Flatpak test jobs must pass before merge.

## Working on the UI

Blueprint files (`.blp`) compile to `.ui` XML at build time via `blueprint-compiler`. Always rebuild after you edit a `.blp`:

```bash
./run.sh                  # re-runs blueprint-compiler
```

When you add a new page, keep Blueprint, Python, window wiring, gresource, and meson sources in sync. The repo layout in [README.md](README.md) and `src/` shows where each piece lands.

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
ship. Translation-only PRs are welcome. They do not need changes to Python.

Maintainer guides:
- [cache lifecycle](docs/CACHE.md)
- [curation feed](docs/CURATION.md)
- [accessibility release pass](docs/ACCESSIBILITY.md)
- [release process](docs/RELEASING.md)

The files in [`docs/reports/`](docs/reports/README.md) are snapshots. They document what was tested. They are not current contributor instructions.

## Pull requests

- Keep PRs focused — one change, one PR.
- Include a screenshot or short clip for any user-visible UI change.
- Run the test commands above before you open a PR.
- Reference the issue you close (`Closes #123`).

## Code style

- Match the code style around you. Tavern is a small codebase. Consistency matters more than any specific rule.
- Logging is off by default. New code should use `_log = get_logger('module_name')` from `logging_util`, not bare `print`.
- Backend I/O goes on a thread and reports back via `GLib.idle_add` — don't block the UI thread.

## Project docs

- [README.md](README.md) — user-facing docs.
- [ROADMAP.md](ROADMAP.md) — what's planned.

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

No time to write code? You can still push this project's backlog forward. TunaOS AI-agent hives work on this repository. Lend a hive your AI subscription or API tokens, and your machine runs contributor tasks from this project's backlog.

- 🪸 [Contribute compute to the reef hive](https://reef.tunaos.org/contribute)
- 🏫 [Contribute compute to the school hive](https://school.tunaos.org/contribute)
