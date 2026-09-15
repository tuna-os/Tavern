# Tavern Roadmap

**Last updated**: 2026-09-15

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
- ✅ Read-only Brew Doctor report, retry, raw output, and copy (#170 phase 1)

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

- **Release parity** — finish the artifact and install checks in #104.
- **Brew Doctor** — assess explicit fix actions and report export next (#170).
- **Backend contracts** — add focused state tests (#153), then separate state
  ownership (#172) and Brewfile execution (#113). Tap parsing is now separate.
- **Performance** — measure the proposals in #171 before changing search,
  list widgets, or cache policy. Keep feature and performance work incremental.
- **Dynamic Brewfile taps** — auto-tap repos referenced in Brewfiles
- **Local icon/screenshot cache** — ORAS-based database for faster loads

## Maintenance policy

Tavern stays a standalone Python and GTK application. A Rust rewrite needs a
measured product benefit and a separate migration proposal. Shared release
tools can serve multiple languages without an application rewrite.
Small native components are an option for measured CPU bottlenecks. First
improve the algorithm, then compare a native prototype with the Python path.
Keep a narrow data interface and equivalent behavior tests. Include Linux,
macOS, and Flatpak build costs in the decision. Network waits and excess UI
work need design fixes regardless of language.
Use current stable dependencies and keep development and production manifests
aligned. Validate updates with both test jobs and the Flatpak build.
Keep quality checks tied to real behavior; empty scorecard files are not work.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
