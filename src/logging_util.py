# logging_util.py - Centralized logging and profiling for Tavern
# SPDX-License-Identifier: GPL-3.0-or-later
#
# OFF by default.  Enable via environment variables:
#
#   TAVERN_LOG=1          – turn on informational logging  (INFO level)
#   TAVERN_LOG=debug      – turn on verbose logging        (DEBUG level)
#   TAVERN_PROFILE=1      – turn on performance profiling  (timing of key ops)
#   TAVERN_LOG_FILE=path  – also write logs to a file
#
# When disabled, the helpers are essentially no-ops (the stdlib logger stays
# at WARNING, so all our info/debug calls are silently discarded).

import functools
import logging
import os
import sys
import time
import threading

# ── Module-level state ───────────────────────────────────────────────────────
_initialized = False
_profiling_enabled = False

# ── Public helpers ───────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for *name* (e.g. ``'backend'`` → ``Tavern.backend``)."""
    return logging.getLogger(f'Tavern.{name}')


def init_logging():
    """
    Set up the Tavern logging subsystem.  Safe to call more than once
    (subsequent calls are no-ops).

    Reads the following environment variables:

    * ``TAVERN_LOG``       – ``"1"`` or ``"info"`` for INFO, ``"debug"`` for DEBUG.
    * ``TAVERN_PROFILE``   – ``"1"`` to enable ``@profile`` timing output.
    * ``TAVERN_LOG_FILE``  – optional path; logs are *also* written there.
    """
    global _initialized, _profiling_enabled

    if _initialized:
        return
    _initialized = True

    env_log = os.environ.get('TAVERN_LOG', '').strip().lower()
    env_profile = os.environ.get('TAVERN_PROFILE', '').strip().lower()
    env_log_file = os.environ.get('TAVERN_LOG_FILE', '').strip()

    # Profiling flag (read by the @profile decorator)
    _profiling_enabled = env_profile in ('1', 'true', 'yes')

    # Determine the effective level
    if env_log in ('debug',):
        level = logging.DEBUG
    elif env_log in ('1', 'true', 'yes', 'info'):
        level = logging.INFO
    elif _profiling_enabled:
        # If only profiling is requested, we still need INFO for the timing
        # messages (they use the PERF level alias below).
        level = logging.INFO
    else:
        # Default: only warnings/errors (effectively silent for our messages)
        level = logging.WARNING

    root = logging.getLogger('Tavern')
    root.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    # ── Formatter ────────────────────────────────────────────────────────
    fmt = logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d [%(levelname)-5s] %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )

    # Console handler → stderr
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # Optional file handler
    if env_log_file:
        try:
            fh = logging.FileHandler(env_log_file, mode='a', encoding='utf-8')
            fh.setLevel(logging.DEBUG)  # capture everything when writing to file
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError as exc:
            root.warning('Could not open log file %s: %s', env_log_file, exc)

    # Startup banner (only when logging is actually on)
    if level <= logging.INFO:
        root.info('Logging initialised  level=%s  profile=%s  file=%s',
                  logging.getLevelName(level),
                  _profiling_enabled,
                  env_log_file or '(none)')


def is_profiling() -> bool:
    """Return True when ``TAVERN_PROFILE=1`` is set."""
    return _profiling_enabled


# ── Profiling decorator ─────────────────────────────────────────────────────

def profile(fn=None, *, threshold_ms: float = 0):
    """
    Decorator that logs wall-clock time of a function call.

    Only emits output when profiling is enabled (``TAVERN_PROFILE=1``).

    Parameters
    ----------
    threshold_ms : float
        If > 0, only log calls that exceed this duration (milliseconds).
        Useful for filtering out fast calls in hot loops.

    Usage::

        @profile
        def heavy_work():
            ...

        @profile(threshold_ms=50)
        def sometimes_slow():
            ...
    """
    def decorator(func):
        logger = get_logger(f'perf.{func.__module__}.{func.__qualname__}')

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not _profiling_enabled:
                return func(*args, **kwargs)
            t0 = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            except BaseException:
                raise
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if elapsed_ms >= threshold_ms:
                    logger.info(
                        '%s  took %.1f ms  [thread=%s]',
                        func.__qualname__,
                        elapsed_ms,
                        threading.current_thread().name,
                    )

        return wrapper

    # Allow both @profile and @profile(threshold_ms=…)
    if fn is not None:
        return decorator(fn)
    return decorator


# ── Context-manager for ad-hoc timing blocks ────────────────────────────────

class log_timing:
    """
    Context manager that logs the duration of a block.

    Only emits output when profiling is enabled.

    Usage::

        with log_timing('fetch formulae API'):
            data = urlopen(…).read()
    """

    def __init__(self, label: str, logger_name: str = 'perf'):
        self.label = label
        self._logger = get_logger(logger_name)

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        if _profiling_enabled:
            elapsed_ms = (time.perf_counter() - self._t0) * 1000
            self._logger.info('%s  took %.1f ms', self.label, elapsed_ms)
        return False
