# Tavern 🍺

[![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](https://github.com/tuna-os/Tavern/blob/main/LICENSE)

Tavern is a modern, fast, and beautiful Homebrew client for Linux, built with **Python**, **GTK 4**, and **Libadwaita**. It provides a premium "App Store" experience for managing your Homebrew formulae and casks.

### Quick Install

**Flatpak (Linux, recommended, with automatic updates):**
```bash
flatpak remote-add --user --if-not-exists tuna-os https://tunaos.org/flatpak/tuna-os.flatpakrepo
flatpak install --user tuna-os org.tunaos.tavern
```

**Homebrew (macOS + Linux):**
```bash
brew tap tuna-os/homebrew-tap && brew install --cask tuna-os/tap/tavern
```
On macOS this installs `Tavern.app`; on Linux it installs a prebuilt AppImage and symlinks it as `tavern` on your PATH.

> [!NOTE]
> The Homebrew cask lives in the org-owned
> [`tuna-os/homebrew-tap`](https://github.com/tuna-os/homebrew-tap)
> (moved from the maintainer's personal tap, tuna-os/Tavern#79 —
> [tuna-os/homebrew-tap#3](https://github.com/tuna-os/homebrew-tap/pull/3),
> merged 2026-08-14). No personal-tap fallback is needed. The Flatpak
> above remains the org-published, recommended channel either way.

> [!IMPORTANT]
> **⚠️ Attribution & Disclaimer**
> Tavern is a **completely AI-generated** project and limited in it's use to just Homebrew. The UI design is a heavy "tribute" (read: shameless ripoff) of [Bazaar](https://github.com/kolunmi/bazaar), which is the best App Store for Linux. If you like this design, you should definitely check out the original project, made by humans and consider supporting the fine folks that make it.

![Tavern Screenshot](https://raw.githubusercontent.com/tuna-os/Tavern/main/data/screenshots/main-window.png)

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

**[Donate time with your AI CLI](https://hub.tunaos.org/#contribute).**

Your machine runs one task at a time using your signed-in AI coding CLI.
The relay alternates between eligible **School** (OS) and **Reef** (apps)
hives after each task. If one hive has no work, the other can continue.

The guide covers prerequisites, verified `just` setup, credentials, provider
costs, and how to stop with Ctrl+C. Your subscription quota or API charges apply.
Never post account credentials or API keys in issues or pull requests.

## 📸 Screenshot Walkthrough

### Main window
![Main window](data/screenshots/main-window.png)

### Search workflow
![GNOME search](data/screenshots/gnome%20search.png)
![Search results](data/screenshots/search%20results.png)

### Package details
![App view](data/screenshots/App%20View.png)

### Taps browser
![Tap view](data/screenshots/Tap%20View.png)

## ✨ Features

- **🏠 Curated Browse**: Popular formulae and casks ranked by real install analytics, plus a daily Discover rotation.
- **🔍 Fast Search**: Instant, off-main-thread searching across tens of thousands of formulae and casks (Ctrl+F), plus GNOME Shell search integration.
- **📦 Package Details**: Rich information including descriptions, versions, dependencies, READMEs, screenshots, and install statistics.
- **🔤 Font Previews**: Font casks render live pangram previews right on the details page.
- **📌 Version Pinning**: Pin formulae and casks to their installed version; pinned packages stay out of update prompts.
- **📄 Brewfile Support**: View complete Brewfiles and install all Homebrew-supported entry types without loss of options. Remove formulae and casks as a group.
- **⚡ Task Management**: Queued installs, removals, and upgrades with per-package progress and a task panel.
- **🫖 Tap Manager**: Add, remove, update, and trust Homebrew taps; browse tap contents.
- **🩺 Brew Doctor**: Check Homebrew health, inspect warnings, retry, and copy diagnostic output.
- **🛠 Maintenance**: Installed security scans, install previews, user services, cleanup previews, and a tool for historical formulae. See [Homebrew features](docs/HOMEBREW_FEATURES.md).
- **🌗 Native Design**: Libadwaita interface following the GNOME HIG — dark mode, adaptive layouts, keyboard shortcuts, and a preferences dialog.
- **🐧 Linux First**: Smart filtering to hide macOS-only casks on Linux systems.
- **🍺 Missing Homebrew Support**: Detects missing Homebrew and offers a terminal installer, command copy, documentation, and live detection retry.
- **⚡ System-First PATH Policy**: Adopts Bluefin parity so system binaries always take precedence over Homebrew binaries in PATH.
## 🚀 Getting Started

### Quick Installation via Homebrew

The easiest way to install Tavern is via Homebrew using the org tap,
`tuna-os/tap`:

```bash
brew tap tuna-os/homebrew-tap
brew install --cask tuna-os/tap/tavern
```

> [!NOTE]
> This is the org-owned channel (tuna-os/Tavern#79,
> [tuna-os/homebrew-tap#3](https://github.com/tuna-os/homebrew-tap/pull/3),
> merged 2026-08-14). On Linux the [Flatpak](#quick-install) is the
> org-published, recommended install.

The cask handles both platforms: `Tavern.app` on macOS and a prebuilt AppImage on Linux, so you don't need Tavern's build dependencies on your machine. If you'd prefer a sandboxed install on Linux, use the Flatpak instead (see below).

### Command-line and links

Launch Tavern directly into a package, tap, or Brewfile view. Pass the target to
Tavern's executable (for example, `tavern` on Linux) or **after the application
ID** in `flatpak run org.tunaos.tavern`. These launch targets open the GUI; they
are not headless install commands.

| Target | Supported arguments |
| --- | --- |
| Formula or cask by name | `--package NAME`, `-p NAME`, `--package=NAME` |
| Local Brewfile | `--brewfile PATH`, `-b PATH`, `--brewfile=PATH` |
| Formula link | `brew://formula/NAME` (also `brew://formulae/NAME`) |
| Cask link | `brew://cask/NAME` (also `brew://casks/NAME`) |
| Package-name shorthand | `brew://NAME` |
| Tap link | `brew://tap/OWNER/REPO` |
| Homebrew web link | `https://formulae.brew.sh/formula/NAME`, `https://formulae.brew.sh/cask/NAME` |

For example, with the Linux executable on your PATH:

```bash
tavern --package ripgrep
tavern 'brew://cask/firefox'
tavern 'brew://tap/tuna-os/homebrew-tap'
tavern --brewfile "$HOME/Brewfile"
```

With the recommended Flatpak install:

```bash
flatpak run org.tunaos.tavern -p ripgrep
flatpak run org.tunaos.tavern 'https://formulae.brew.sh/formula/ripgrep'
flatpak run org.tunaos.tavern 'brew://tap/tuna-os/homebrew-tap'
flatpak run org.tunaos.tavern --brewfile="$HOME/Brewfile"
```

Quote paths containing spaces and use a Brewfile path accessible to Tavern
(inside the sandbox for Flatpak). On macOS, pass arguments to the installed app
with, for example, `open -a Tavern --args --package ripgrep`. For development,
`./run.sh --package ripgrep` forwards arguments after building and installing.

For desktop shortcuts or scripts, pass the link to Tavern as shown above. An
installed desktop `brew://` handler can also route links to Tavern, depending on
your desktop's default-app settings. Ordinary HTTPS links usually open in a web
browser unless explicitly passed to Tavern. The supported URI schemes here are
`brew://` and the specific `https://formulae.brew.sh/` forms above; do not assume
`homebrew://` links work.

### Prerequisites

- [Homebrew](https://brew.sh) (Tavern will offer to install it interactively if not already present).
- Python 3.10+
- GTK 4 and Libadwaita development headers.

```
brew install gtk4 libadwaita meson ninja pygobject3 gettext desktop-file-utils blueprint-compiler

```

### Installation (Development)

1. Clone the repository:
   ```bash
   git clone https://github.com/tuna-os/Tavern.git
   cd Tavern
   ```

2. Run the build and launch script:
   ```bash
   ./run.sh
   ```

## 🛠️ Development

### Building with Meson

```bash
meson setup builddir --prefix="$HOME/.local"
meson compile -C builddir
```

### Running

```bash
./run.sh
```

`./run.sh` rebuilds the configured build directory, installs Tavern under
`$HOME/.local`, and launches it. If `builddir` was configured with another
prefix, reconfigure it with the prefix above before running the script.

## 📦 Flatpak

### Install from the custom OCI Remote (Recommended)

To get automatic updates directly through your software center (like GNOME Software or KDE Discover) or CLI, add the official `tuna-os` OCI remote:

```bash
flatpak remote-add --user --if-not-exists tuna-os https://tunaos.org/flatpak/tuna-os.flatpakrepo
flatpak install --user tuna-os org.tunaos.tavern
```

### Install a single standalone bundle from CI
If you prefer to install a one-off nightly build from the main branch:

```bash
wget https://nightly.link/tuna-os/Tavern/workflows/flatpak/main/Tavern-Linux-CI.zip
unzip Tavern-Linux-CI.zip
flatpak install --user --reinstall Tavern-Linux-CI.flatpak
```

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, tests, and PR guidelines.

## 📄 License

Tavern is released under the **GPL-3.0-or-later** license. See `LICENSE` for details.

---

Part of the [TunaOS](https://tunaos.org) ecosystem. [Docs](https://tunaos.org) · [Contributing](CONTRIBUTING.md)
