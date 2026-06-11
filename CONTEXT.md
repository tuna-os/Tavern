# Tavern

Tavern is a GTK 4 / Libadwaita graphical client for Homebrew on Linux.

## Language

**Tap**:
A Git repository of Homebrew formula and cask definitions (e.g. `homebrew/core`, `user/homebrew-foo`). Managed via `brew tap` / `brew untap`.
_Avoid_: Repository, source, remote

**Tap trust**:
A Homebrew ≥ 6.0.0 security mechanism requiring explicit user approval before a tap's Ruby code is evaluated or run.
_Avoid_: Tap verification, tap authorization

**Formula**:
A package definition for a command-line tool or library. Managed via `brew install` (no `--cask` flag).
_Avoid_: Package (ambiguous — could be formula or cask)

**Cask**:
A package definition for a GUI application, font, or driver. Managed via `brew install --cask`.
_Avoid_: App, application

**Brewfile**:
A declarative manifest listing taps, formulae, casks, and other dependencies for batch management via `brew bundle`.
_Avoid_: Lockfile, manifest

**Pin**:
A mechanism to exclude a package from `brew upgrade`. Homebrew ≥ 6.0.0 supports pinning both formulae and casks.
_Avoid_: Hold, freeze

**Ask mode**:
Homebrew 6.0.0's default confirmation prompt before `install`, `upgrade`, and `remove` operations. Suppressed in Tavern via `HOMEBREW_NO_INSTALL_ASK=1`.
_Avoid_: Confirmation prompt, dry-run prompt
