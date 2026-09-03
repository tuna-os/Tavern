# AGENTS.md — agent guide for tuna-os/Tavern

A **Homebrew client for Linux and macOS** — Python + GTK4 + libadwaita,
shipped as the `org.tunaos.tavern` Flatpak and as a Homebrew cask.

Human docs: [`README.md`](README.md), [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`docs/`](docs/) (`CACHE.md`, `CURATION.md`, `RELEASING.md`,
`ACCESSIBILITY.md`, and `adr/`). [`docs/agents/`](docs/agents/) is about how
hive's skills should *consume* this repo's docs; this file is about the repo
itself.

## The release automation writes to the wrong tap

`README.md` says the cask moved to the org-owned
[`tuna-os/homebrew-tap`](https://github.com/tuna-os/homebrew-tap) (#79, merged
2026-08-14) and that "no personal-tap fallback is needed". **Two workflows did
not move with it:**

- `update-homebrew-tap.yml` checks out `hanthor/homebrew-tap` and pushes the
  regenerated cask there.
- `verify-tap-install.yml` runs `brew tap hanthor/homebrew-tap` and installs
  from it.

So on every release the org tap — the one users are told to install from — is
untouched, and the post-release verification installs from a tap nobody is
directed to. **Do not "fix" this by simply repointing the checkout.** The
workflow overwrites `Casks/tavern.rb` wholesale with a generated file, and the
org tap's hand-maintained cask carries things the generated one does not:
`depends_on formula: "pygobject3"`, the `dev.hanthor.Tavern.*` desktop and
icon artifacts the *released* AppImage actually ships, the `AppRun` `$0`
path-resolution patch, the `TAVERN_DATADIR`/`TAVERN_LOCALEDIR` exports, and
the postflight icon-cache refresh. Repointing as-is would clobber all of it.

The two viable shapes are: rewrite the workflow to edit only `version` and the
two `sha256` values in the existing cask, or delete the workflow and keep the
cask hand-maintained. Either is a decision, not a patch.

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

`publish-flatpak.yml` / `promote-to-prod.yml` cover the Flatpak channel, and
this repo carries **two** vendored copies of the flatpak index writer:
`.github/scripts/update-index.py` and `scripts/update-index.py`. They differ
from each other and from every other copy in the org.

`tuna-os/.github` runs `flatpak-tooling-drift-check.yml` weekly against eight
application repos, comparing their `.github/scripts/update-index.py` to
`.github/actions/update-flatpak-index/update-index.py`. **Tavern is not in that
list**, so neither copy here is checked by anything. On default branches today:

| copy | blob |
|---|---|
| `.github/actions/update-flatpak-index/update-index.py` (org canonical) | `6eaa8186` |
| `Tavern/.github/scripts/update-index.py` | `ec916224` |
| `Tavern/scripts/update-index.py` | `127aed10` |

Migrating to the composite action would remove both, which is what that
workflow's comment says it is an interim guard for. Short of that, changing one
copy here means checking the other deliberately.
