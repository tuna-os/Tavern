# Tavern 🍺

Tavern is a modern, fast, and beautiful Homebrew client for Linux, built with **Python**, **GTK 4**, and **Libadwaita**. It provides a premium "App Store" experience for managing your Homebrew formulae and casks.

### Quick Install

**Flatpak (Linux, recommended):**
```bash
curl -L https://nightly.link/hanthor/Tavern/workflows/flatpak/main/Tavern-Linux-CI.zip -o Tavern-Linux-CI.zip && unzip -o Tavern-Linux-CI.zip && flatpak install --user --reinstall Tavern-Linux-CI.flatpak
```

**Homebrew (macOS + Linux):**
```bash
brew tap hanthor/homebrew-tap && brew install --cask hanthor/tap/tavern
```
On macOS this installs `Tavern.app`; on Linux it installs a prebuilt AppImage and symlinks it as `tavern` on your PATH.

> [!IMPORTANT]
> **⚠️ Attribution & Disclaimer**
> Tavern is a **completely AI-generated** project and limited in it's use to just Homebrew. The UI design is a heavy "tribute" (read: shameless ripoff) of [Bazaar](https://github.com/kolunmi/bazaar), which is the best App Store for Linux. If you like this design, you should definitely check out the original project, made by humans and consider supporting the fine folks that make it.

![Tavern Screenshot](https://raw.githubusercontent.com/hanthor/Tavern/main/data/screenshots/main-window.png)

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

- **🏠 Curated Browse**: Discover popular and featured applications.
- **🔍 Fast Search**: Instant searching across thousands of formulae and casks.
- **📦 Package Details**: Rich information including descriptions, versions, dependencies, and screenshots.
- **📄 Brewfile Support**: Open and manage `.Brewfile`s to bulk-install or remove entire environments.
- **⚡ Task Management**: Parallel installations and removals with a global progress indicator.
- **🌗 Native Design**: Beautiful Libadwaita interface with full Dark Mode support and responsive layouts.
- **🐧 Linux First**: Smart filtering to hide macOS-only casks on Linux systems.

## 🚀 Getting Started

### Quick Installation via Homebrew

The easiest way to install Tavern is via Homebrew using the `hanthor/tap`:

```bash
brew tap hanthor/homebrew-tap
brew install --cask hanthor/tap/tavern
```

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
   git clone https://github.com/hanthor/Tavern.git
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

### Install latest build from CI

Download and install the latest Flatpak bundle built from the `main` branch:

```bash
# Download the latest CI build
wget https://nightly.link/hanthor/Tavern/workflows/flatpak/main/Tavern-Linux-CI.zip
unzip Tavern-Linux-CI.zip
flatpak install --user --reinstall Tavern-Linux-CI.flatpak
```

Or just grab the zip directly: [Tavern-Linux-CI.zip](https://nightly.link/hanthor/Tavern/workflows/flatpak/main/Tavern-Linux-CI.zip)

### Build from source

```bash
flatpak-builder --force-clean --user --install flatpak-build dev.hanthor.Tavern.json
```

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, tests, and PR guidelines.

## 📄 License

Tavern is released under the **GPL-3.0-or-later** license. See `LICENSE` for details.
