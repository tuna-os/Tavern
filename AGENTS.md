# AGENTS.md — agent guide for tuna-os/Tavern

A **Homebrew client for Linux and macOS** — Python + GTK4 + libadwaita,
shipped as the `org.tunaos.tavern` Flatpak and as a Homebrew cask.

Human docs: [`README.md`](README.md), [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`docs/`](docs/) (`CACHE.md`, `CURATION.md`, `RELEASING.md`,
`ACCESSIBILITY.md`, and `adr/`). [`docs/agents/`](docs/agents/) is about how
hive's skills should *consume* this repo's docs; this file is about the repo
itself.

## Homebrew release ownership

`tuna-os/homebrew-tap/Casks/tavern.rb` owns cask structure. The release workflow
uses `tools/update-homebrew-cask.py` to change only version and two checksums.
Unknown cask shapes and downgrades fail. Never regenerate the whole cask.
The tap owns runtime dependencies, AppRun patches, desktop artifacts, icons,
and cache refresh hooks. Artifact paths must match the released AppImage.

The updater requires `TAP_GITHUB_TOKEN` with write access to the org tap.
Rejected pushes fail the job. Both install verification jobs use the org tap.

## A green host test job is not full coverage

`tests.yml` runs the same suite twice on purpose:

- **`pytest`** on the host, against Ubuntu's libadwaita **1.5**. The
  `requires_adw_spinner` tests (`test_window.py`, `test_task_panel.py`,
  `test_tap_page.py`) **skip** there — `Adw.Spinner` needs ≥ 1.6.
- **`pytest-flatpak`** inside a real flatpak-builder sandbox against
  `org.gnome.Platform//50` — the libadwaita the app actually ships against.
  Those tests run for real only here (#88).

If you are reading a single green tick, check which job it came from.

## Running the tests at all takes two non-obvious steps

1. **Do not use `actions/setup-python`.** `tests/conftest.py` imports `gi` at
   collection time, and PyGObject here is apt's `python3-gi`, built against
   the system interpreter — a setup-python interpreter cannot see it and every
   module fails to collect.
2. **Compile the gresource bundle first**, to exactly
   `.flatpak-build/files/share/tavern/tavern.gresource`. `conftest.py` looks
   for that path, and the `Gtk.Template` classes cannot be imported without
   it — skip it and **14 modules fail at collection** with `g-resource-error`
   / "could not create new GType".

```bash
mkdir -p build-ui .flatpak-build/files/share/tavern
blueprint-compiler batch-compile build-ui src src/*.blp
cp src/style.css build-ui/
glib-compile-resources \
  --target=.flatpak-build/files/share/tavern/tavern.gresource \
  --sourcedir=build-ui --sourcedir=src src/tavern.gresource.xml

xvfb-run -a dbus-run-session -- python3 -m pytest tests/ -m "not slow"
```

Two more traps CI's comments record: `glib-compile-resources` is in
`libglib2.0-dev-**bin**` (not `libglib2.0-bin`), and **`pytest-benchmark` is
required, not optional** — pyproject's `addopts` carries
`--benchmark-disable`, and pytest exits on an unknown argument.

`--build-only` in the Flatpak job is deliberate: the clean/finish/export
phases pull in `appstreamcli compose`, which failed on GitHub-hosted runners
with `file-read-error` / `filters-but-no-output` despite the same manifest
succeeding locally and in `flatpak.yml`. Root cause unpinned; that job was
never producing an artifact, so it sidesteps rather than guesses.

## Gates beyond pytest

`tests.yml` also runs three tools that are easy to overlook:

```bash
python3 tools/check-translations.py
python3 tools/validate-release.py --version "$(sed -n "s/.*version: '\([^']*\)'.*/\1/p" meson.build | head -1)"
python3 tools/check-supply-chain.py
```

The version comes from `meson.build` — that file is the single source of
truth for the release contract, so bumping it has consequences beyond the
build.

## Publishing paths

`publish-flatpak.yml` calls the shared `tuna-os/.github` publisher.
There are no local index writers. Change the shared implementation for index
fixes. `prod` must remain an ancestor of `main` so promotion can fast-forward.
Preserve production-only commits by a merge into `main`; never force-push prod.
