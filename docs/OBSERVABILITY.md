# Tavern Observability & Telemetry Assessment

This document describes the observability architecture, logging subsystem, performance profiling capabilities, and future telemetry recommendations for **Tavern**.

---

## Current Architecture

Tavern is a Linux desktop application built with Python, GTK 4, and Libadwaita. It operates locally against the user's `brew` installation and Homebrew API endpoints.

### 1. Logging Subsystem (`src/logging_util.py`)

Logging is centralized in `src/logging_util.py`. Logging levels are disabled (set to `WARNING`) by default to maintain quiet standard output during normal desktop operation.

#### Environment Variables

- `TAVERN_LOG`:
  - `1`, `true`, `info`: Enables `INFO` level logging across the `Tavern.*` namespace.
  - `debug`: Enables `DEBUG` level logging for verbose operation details.
- `TAVERN_PROFILE`:
  - `1`, `true`, `yes`: Enables performance profiling output for decorated functions and timing blocks.
- `TAVERN_LOG_FILE`:
  - `<path>`: Directs logs to a specified file in addition to standard error (`sys.stderr`).

#### Code Usage Pattern

```python
from logging_util import get_logger

logger = get_logger("backend")
logger.info("Refreshing Homebrew formula catalog")
```

---

## 2. Performance Profiling

Tavern includes built-in timing instrumentation to measure latency on critical user-facing paths (e.g. search indexing, catalog parsing, and subprocess invocation).

### Decorator Usage (`@profile`)

```python
from logging_util import profile

@profile(threshold_ms=50)
def load_catalog():
    ...
```

### Context Manager Usage (`log_timing`)

```python
from logging_util import log_timing

with log_timing("Fetch remote cask metadata"):
    ...
```

---

## 3. Data Flow & Exporter Policy

- **No Remote Telemetry Exporter**: Tavern does not ship metrics, traces, or diagnostic data to external telemetry endpoints or third-party analytical services.
- **Local Diagnostics**: All diagnostic logs are written exclusively to standard error or a local file specified by `TAVERN_LOG_FILE`.

---

## 4. Telemetry Enhancement Roadmap

When an observability backend is configured and authorized, the following extensions are recommended:

1. **Structured Log Formatter**:
   Add an optional JSON formatting handler (`TAVERN_LOG_FORMAT=json`) to simplify integration with `systemd-journald`, Vector, or desktop log parsers.
2. **OpenTelemetry Span Tracing**:
   Instrument request-path operations (e.g. Homebrew API queries, bottle downloads, formula installations) with OpenTelemetry spans when an OpenTelemetry Collector is detected locally.
3. **Subprocess Metrics**:
   Track duration, status codes, and failure rates for `brew` binary invocations.
