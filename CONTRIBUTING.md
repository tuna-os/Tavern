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

For a sandboxed Flatpak build:

```bash
just dev                  # build + install + run as Flatpak
```

## Tests

```bash
pytest tests/                                       # full suite
pytest tests/test_backend.py -v                     # one file
pytest tests/test_benchmarks.py --benchmark-enable  # benchmarks
```

Tests run headlessly — the autouse fixtures in `tests/conftest.py` mock `Gio.Settings` and dialog `.present()` calls so nothing pops on screen. If you add new dialog types, extend that fixture.

## Working on the UI

Blueprint files (`.blp`) compile to `.ui` XML at build time via `blueprint-compiler`. Always rebuild after editing a `.blp`:

```bash
./run.sh                  # re-runs blueprint-compiler
```

When adding a new page, follow the eight-step checklist in [CLAUDE.md](CLAUDE.md#adding-a-new-page) — it covers Blueprint, Python, window wiring, gresource registration, and meson sources.

## Pull requests

- Keep PRs focused — one change, one PR.
- Include a screenshot or short clip for any user-visible UI change.
- Run `pytest tests/` locally before opening.
- Reference the issue you're closing (`Closes #123`).

## Code style

- Match the surrounding style — Tavern is a small codebase, consistency matters more than any specific rule.
- Logging is off by default. New code should use `_log = get_logger('module_name')` from `logging_util`, not bare `print`.
- Backend I/O goes on a thread and reports back via `GLib.idle_add` — don't block the UI thread.

## Project docs

- [README.md](README.md) — user-facing docs.
- [CLAUDE.md](CLAUDE.md) — full developer + architecture guide.
- [ROADMAP.md](ROADMAP.md) — what's planned.
