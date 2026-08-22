# Tavern Roadmap

**Last updated**: 2026-08-22

Part of the [TunaOS](https://tunaos.org) ecosystem.

## Done

- ✅ Brewfile support — open, display, bulk install/remove
- ✅ Filter macOS-only Casks on Linux
- ✅ Icons and screenshots for packages
- ✅ Discover section (replaced reverse-alphabetical "Recently Added")
- ✅ Tap Manager — add, remove, update, list taps; view tap contents; trust status
- ✅ Related Packages — dependencies, same-tap siblings, and versioned variants on the details page
- ✅ Version pinning — pin/unpin formulae and casks; pinned packages excluded from update prompts
- ✅ Preferences and Keyboard Shortcuts dialogs; header-bar search (Ctrl+F)
- ✅ Indexed search off the main thread ([#49](https://github.com/tuna-os/Tavern/issues/49))
- ✅ Font cask previews ([#39](https://github.com/tuna-os/Tavern/issues/39))

## Release health

Tavern's distribution channels are active, but they do not yet share one
release contract. Repository tags reached `v0.1.57` on 2026-08-20 while the
latest GitHub Release remains `v0.1.9` from 2026-06-15. The recommended
Flatpak is promoted separately from the `prod` branch.

Before calling a new version stable, complete the release-parity gate tracked
in [#104](https://github.com/tuna-os/Tavern/issues/104):

- choose one intentional promotion event and source commit as the canonical
  version;
- produce matching GitHub Release, Flatpak OCI, Homebrew cask, AppImage, and
  macOS artifacts from that promotion;
- record artifact/version verification for every supported channel; and
- reconcile or clearly mark tags that do not represent a published release.

Success means a user can identify the current stable version and obtain the
same release through every supported install path. Until this gate passes,
new tags alone are not evidence of a stable release.

## Planned

- **Dynamic Brewfile taps** — auto-tap repos referenced in Brewfiles
- **Local icon/screenshot cache** — ORAS-based database for faster loads

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
