# Tavern 🍺

Tavern is a modern, fast, and beautiful Homebrew client for Linux, built with **Python**, **GTK 4**, and **Libadwaita**. It provides a premium "App Store" experience for managing your Homebrew formulae and casks.

```bash
flatpak install --user https://nightly.link/hanthor/Tavern/workflows/flatpak/main/tavern-x86_64.flatpak.zip
```

> [!IMPORTANT]
> **⚠️ Attribution & Disclaimer**
> Tavern is a **completely AI-generated** project and limited in it's use to just Homebrew. The UI design is a heavy "tribute" (read: shameless ripoff) of [Bazaar](https://github.com/kolunmi/bazaar), which is the best App Store for Linux. If you like this design, you should definitely check out the original project, made by humans and consider supporting the fine folks that make it.

![Tavern Screenshot](https://raw.githubusercontent.com/hanthor/tavern/main/data/screenshots/main-window.png)

## ✨ Features

- **🏠 Curated Browse**: Discover popular and featured applications.
- **🔍 Fast Search**: Instant searching across thousands of formulae and casks.
- **📦 Package Details**: Rich information including descriptions, versions, dependencies, and screenshots.
- **📄 Brewfile Support**: Open and manage `.Brewfile`s to bulk-install or remove entire environments.
- **⚡ Task Management**: Parallel installations and removals with a global progress indicator.
- **🌗 Native Design**: Beautiful Libadwaita interface with full Dark Mode support and responsive layouts.
- **🐧 Linux First**: Smart filtering to hide macOS-only casks on Linux systems.

## 🚀 Getting Started

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
   git clone https://github.com/hanthor/tavern.git
   cd tavern
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
wget https://nightly.link/hanthor/Tavern/workflows/flatpak/main/tavern-x86_64.flatpak.zip
unzip tavern-x86_64.flatpak.zip
flatpak install --user tavern.flatpak
```

Or just grab the zip directly: [tavern.flatpak.zip](https://nightly.link/hanthor/Tavern/workflows/flatpak/main/tavern-x86_64.flatpak.zip)

### Build from source

```bash
flatpak-builder --force-clean --user --install flatpak-build dev.hanthor.Tavern.json
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

Tavern is released under the **GPL-3.0-or-later** license. See `LICENSE` for details.
