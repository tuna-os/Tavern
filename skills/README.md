# Tavern Skills Reference

This directory contains skill definitions for AI agents working on the Tavern project. Each skill covers a major area of the codebase.

## Quick Navigation

### [build.md](build.md) — Build System & Deployment
- **Local development:** Using `run.sh` with Homebrew
- **Flatpak packaging:** Using Justfile for distribution builds
- **Testing:** Pytest test suite and running tests
- **Build troubleshooting:** Common issues and fixes
- **Performance considerations:** Cold start, hot reload, iteration cycles

**When to use:** Building, testing, deploying, debugging build failures

### [profiling.md](profiling.md) — Logging & Performance Diagnostics
- **Quick start:** Environment variables for instant profiling
- **Logging system:** `get_logger()`, `init_logging()`, log format
- **Profiling decorators:** `@profile` decorator, `log_timing()` context manager
- **Startup profiling:** Full timing breakdown of app initialization
- **Performance optimization:** Process for identifying and fixing slow paths

**When to use:** Investigating slow operations, understanding startup flow, optimizing performance

### [features.md](features.md) — Architecture & Feature Implementation
- **Architecture overview:** UI layer, backend, desktop integration
- **Core modules:** window.py, pages, backend.py, task manager
- **Adding features:** Step-by-step guides for common changes
- **Brewfile format:** Supported syntax and parsing
- **Testing patterns:** How to write and run tests
- **Code style:** Python conventions used in the project

**When to use:** Implementing new features, understanding how parts fit together, writing tests

## Environment Variable Reference

Quick reference for all profiling flags:

```bash
# Logging only
TAVERN_LOG=info ./run.sh

# Full profiling
TAVERN_PROFILE=1 TAVERN_LOG=info ./run.sh

# Debugging with file output
TAVERN_LOG=debug TAVERN_LOG_FILE=/tmp/tavern.log ./run.sh
```

See [profiling.md](profiling.md#environment-variables) for full details.

## Build Command Reference

```bash
# Local development
./run.sh                    # Build, install, run with Homebrew

# Flatpak development
just build                  # Build only
just install                # Build + install
just dev                    # Build + install + run (complete)
just run                    # Run already-installed
just clean                  # Remove artifacts
```

See [build.md](build.md) for full details.

## File Organization

```
tavern/
├── agents.md                    # Main developer guide (start here)
├── skills/                      # AI agent skill definitions
│   ├── README.md               # This file
│   ├── build.md                # Build system and deployment
│   ├── profiling.md            # Logging and performance
│   └── features.md             # Architecture and features
├── src/                        # Application source
│   ├── main.py                 # Entry point
│   ├── application.py          # GTK app singleton
│   ├── window.py               # Main window
│   ├── backend.py              # Backend interface
│   ├── *_page.py               # Page implementations
│   ├── logging_util.py         # Logging/profiling infrastructure
│   └── *.blp                   # Blueprint UI definitions
├── tests/                      # Test suite (pytest)
└── builddir/                   # Meson build artifacts
```

## Key Concepts

### Modules Instrumentation
Every module has timing checkpoints that log startup progress:
- `main.py` — Full startup timeline (8 checkpoints)
- `application.py` — Window creation and CSS (3 checkpoints)
- `window.py` — Backend init and page setup (9 checkpoints)
- `brewfile_page.py` — Per-package timing with statistics

Enable with: `TAVERN_LOG=info`

### Async Operations
All I/O (network, file, subprocess) runs in background threads:
- `TaskManager` — Operation queue with progress tracking
- `Task` — Individual async job wrapper
- Callbacks — UI updates when task completes

### Pages
Four main content areas:
- **Browse** — All packages by tap
- **Search** — Full-text search
- **Installed** — Currently installed packages
- **Brewfile** — Contents of a single Brewfile

### Backend
Single interface to:
- Homebrew CLI (`brew list`, `brew install`, etc.)
- Flathub API (metadata and icons for flatpaks)
- File system (Brewfile parsing, config storage)

## Troubleshooting Guide

| Problem | See | Solution |
|---------|-----|----------|
| Build fails with "symbol not found" | [build.md](build.md#troubleshooting) | Create pkg-config symlinks |
| "Unable to load resource" error | [build.md](build.md#troubleshooting) | Check XDG_DATA_DIRS and gresource |
| Slow startup | [profiling.md](profiling.md#startup-profiling) | Profile with TAVERN_LOG=info |
| Feature not working | [features.md](features.md) | Check module, write test |
| Test failures | [build.md](build.md#testing) | Run with TAVERN_LOG=debug |

## Common Tasks

### Profile Application Startup
```bash
TAVERN_LOG=info ./run.sh 2>&1 | tee startup.log
# Now look at startup.log for timing breakdown
```

### Debug a Specific Operation
```bash
TAVERN_LOG=debug TAVERN_LOG_FILE=/tmp/debug.log ./run.sh
# Open the Brewfile you're testing
# Check /tmp/debug.log for detailed logs
grep "your_operation" /tmp/debug.log
```

### Add Timing to New Code
```python
# In your_module.py
from tavern.logging_util import log_timing

with log_timing("Operation description", "module_name"):
    slow_operation()
```

Then enable profiling:
```bash
TAVERN_LOG=info ./run.sh
```

### Rebuild After Changes
```bash
meson install -C builddir     # Quick rebuild
# or
./run.sh                       # Full rebuild + run
```

### Run Tests
```bash
pytest tests/
pytest tests/test_backend.py::test_parse_brewfile -v
TAVERN_LOG=debug pytest tests/ -s
```

## Architecture Diagrams

See [features.md](features.md#high-level-architecture) for:
- Application structure (UI layer, backend, external services)
- Data flow between components
- How pages interact with the backend

## Performance Targets

| Operation | Target | Current |
|-----------|--------|---------|
| Cold startup (fresh app) | <8s | ~7-8s ✓ |
| Browse page load | <3s | ~2s ✓ |
| Search first result | <500ms | ~300ms ✓ |
| Brewfile open (5 packages) | <5s | ~5-7s |
| Icon download (first time) | varies | 1-5s per package |

See [profiling.md](profiling.md#performance-optimization-process) for how to profile and optimize.

## Additional Resources

- **Main guide:** [agents.md](../agents.md) — Start here for overview
- **README:** [README.md](../README.md) — User documentation
- **Build:** [Justfile](../Justfile) — Flatpak build automation
- **Source:** [src/](../src/) — Python source code

---

**Last updated:** With comprehensive startup profiling (8 main.py, 3 application.py, 9 window.py timing points)

**For questions:** Check the relevant `.md` file or grep the codebase for the operation you're investigating
