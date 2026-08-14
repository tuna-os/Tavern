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
> The Homebrew cask now lives in the org-owned
> [`tuna-os/homebrew-tap`](https://github.com/tuna-os/homebrew-tap)
> (moved from the maintainer's personal tap, tuna-os/Tavern#79 —
> [tuna-os/homebrew-tap#3](https://github.com/tuna-os/homebrew-tap/pull/3)).
> If `brew install` above 404s, that PR hasn't merged yet; use
> `brew tap hanthor/homebrew-tap && brew install --cask hanthor/tap/tavern`
> in the meantime. The Flatpak above remains the org-published,
> recommended channel either way.

> [!IMPORTANT]
> **⚠️ Attribution & Disclaimer**
> Tavern is a **completely AI-generated** project and limited in it's use to just Homebrew. The UI design is a heavy "tribute" (read: shameless ripoff) of [Bazaar](https://github.com/kolunmi/bazaar), which is the best App Store for Linux. If you like this design, you should definitely check out the original project, made by humans and consider supporting the fine folks that make it.

![Tavern Screenshot](https://raw.githubusercontent.com/tuna-os/Tavern/main/data/screenshots/main-window.png)

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
- **📄 Brewfile Support**: Open and manage `.Brewfile`s to bulk-install or remove entire environments.
- **⚡ Task Management**: Queued installs, removals, and upgrades with per-package progress and a task panel.
- **🫖 Tap Manager**: Add, remove, update, and trust Homebrew taps; browse tap contents.
- **🌗 Native Design**: Libadwaita interface following the GNOME HIG — dark mode, adaptive layouts, keyboard shortcuts, and a preferences dialog.
- **🐧 Linux First**: Smart filtering to hide macOS-only casks on Linux systems.

## 🚀 Getting Started

### Quick Installation via Homebrew

The easiest way to install Tavern is via Homebrew using the org tap,
`tuna-os/tap`:

```bash
brew tap tuna-os/homebrew-tap
brew install --cask tuna-os/tap/tavern
```

> [!NOTE]
> This is now the org-owned channel (tuna-os/Tavern#79,
> [tuna-os/homebrew-tap#3](https://github.com/tuna-os/homebrew-tap/pull/3)).
> If that PR hasn't merged yet and the install 404s, fall back to
> `brew tap hanthor/homebrew-tap && brew install --cask hanthor/tap/tavern`.
> On Linux the [Flatpak](#quick-install) is the org-published, recommended install.

The cask handles both platforms: `Tavern.app` on macOS and a prebuilt AppImage on Linux, so you don't need Tavern's build dependencies on your machine. If you'd prefer a sandboxed install on Linux, use the Flatpak instead (see below).

### Prerequisites

- [Homebrew](https://brew.sh) installed and in your PATH.
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
meson setup builddir
meson compile -C builddir
```

### Running

```bash
meson compile -C builddir run
```

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