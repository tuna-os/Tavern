# task_manager.py - Centralized installation/removal task manager
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import subprocess
import threading
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import GLib, GObject
from .logging_util import get_logger, profile, log_timing

_log = get_logger('task_manager')


# ── Brew output → friendly phase mapping ─────────────────────────
_PHASE_PATTERNS = [
    # (substring in brew output, user-visible label, progress fraction hint)
    # N.B. Order matters — "Uninstalling" contains "Installing" as a substring,
    # so more-specific patterns must come before less-specific ones.
    ('Downloading',           'Downloading…',       0.10),
    ('Already downloaded',    'Downloading…',       0.20),
    ('Fetching',              'Fetching…',          0.15),
    ('Uninstalling',          'Removing…',          0.50),
    ('Installing',            'Installing…',        0.40),
    ('Pouring',               'Installing…',        0.55),
    ('Unlinking',             'Removing links…',    0.60),
    ('Linking',               'Finishing up…',      0.75),
    ('Removing',              'Removing…',          0.55),
    ('Purging',               'Removing…',          0.65),
    ('Moving',                'Finishing up…',      0.70),
    ('Caveats',               'Almost done…',       0.85),
    ('Summary',               'Finishing up…',      0.90),
]


# Matches brew download progress bars: "######  15.3%"
_DOWNLOAD_BAR_RE = re.compile(r'^[#\s]{4,}\s+(\d+\.?\d*)\s*%\s*$')


def _parse_phase(line):
    """Parse a line of brew output and return (label, fraction) or None."""
    # Download progress bar — e.g. "######  15.3%" — map to 0.05–0.35 range
    m = _DOWNLOAD_BAR_RE.match(line.strip())
    if m:
        pct = float(m.group(1))
        return 'Downloading…', 0.05 + (pct / 100.0) * 0.30

    for pattern, label, frac in _PHASE_PATTERNS:
        if pattern.lower() in line.lower():
            return label, frac
    return None


class TaskStatus:
    PENDING   = 'pending'
    RUNNING   = 'running'
    COMPLETED = 'completed'
    FAILED    = 'failed'
    CANCELLED = 'cancelled'


class TaskOperation:
    INSTALL   = 'install'
    REMOVE    = 'uninstall'
    UPGRADE   = 'upgrade'

    @staticmethod
    def label(op):
        return {
            TaskOperation.INSTALL: 'Installing',
            TaskOperation.REMOVE: 'Removing',
            TaskOperation.UPGRADE: 'Upgrading',
        }.get(op, op.title())


# "X was installed from tap A but you are trying to install from tap B"
_MULTI_TAP_RE = re.compile(
    r'(\S+) was installed from the (\S+) tap\s+'
    r'but you are trying to install it from the (\S+) tap',
    re.IGNORECASE,
)

# "X exists in multiple taps: * tap/a/x  * tap/b/x"
_AMBIGUOUS_TAP_RE = re.compile(r'^\s*\*\s+([\w\-./]+)', re.MULTILINE)


class Task(GObject.Object):
    """A single package operation tracked by the TaskManager."""

    __gtype_name__ = 'TavernTask'

    # Properties observable from UI
    status       = GObject.Property(type=str, default=TaskStatus.PENDING)
    progress     = GObject.Property(type=float, default=0.0)   # 0.0 – 1.0
    status_text  = GObject.Property(type=str, default='Waiting…')
    error_detail = GObject.Property(type=str, default='')

    # Set when a multi-tap conflict is detected: {'installed_tap': str, 'target_tap': str}
    conflict_info = None
    # Set when a formula/cask exists in multiple taps: [fully/qualified/name, ...]
    ambiguous_taps = None
    # Fully-qualified install name override (e.g. 'ublue-os/tap/antigravity-cli-linux')
    qualified_install_name = None

    __gsignals__ = {
        'finished': (GObject.SignalFlags.RUN_LAST, None, (bool,)),  # success
    }

    def __init__(self, package, operation, **kwargs):
        super().__init__(**kwargs)
        self.package   = package
        self.operation = operation          # TaskOperation.*
        self._process  = None
        self._output_lines = []            # kept for diagnostics, never shown raw

    # ── Read-only helpers ────────────────────────────────────────
    @property
    def title(self):
        return f'{TaskOperation.label(self.operation)} {self.package.display_name or self.package.name}'

    @property
    def is_active(self):
        return self.status in (TaskStatus.PENDING, TaskStatus.RUNNING)

    # ── Internal API (called from worker thread via GLib.idle_add) ──
    def _set_running(self):
        self.status = TaskStatus.RUNNING
        self.status_text = 'Starting…'
        self.progress = 0.05
        self.package.task_active   = True
        self.package.task_progress = 0.05
        self.package.task_label    = 'Starting…'

    def _update_phase(self, label, fraction):
        self.status_text = label
        if fraction > self.progress:
            self.progress = fraction
        self.package.task_label = label
        if fraction > self.package.task_progress:
            self.package.task_progress = fraction

    def _set_completed(self):
        self.status = TaskStatus.COMPLETED
        self.progress = 1.0
        self.status_text = 'Done'
        self.package.task_active   = False
        self.package.task_progress = 0.0
        self.package.task_label    = ''
        self.emit('finished', True)

    def _set_failed(self, detail=''):
        self.status = TaskStatus.FAILED
        self.error_detail = detail
        self.status_text = 'Failed'
        self.package.task_active   = False
        self.package.task_progress = 0.0
        self.package.task_label    = ''
        self.emit('finished', False)


class TaskManager(GObject.Object):
    """Singleton-ish manager that owns all tasks and runs them sequentially."""

    __gtype_name__ = 'TavernTaskManager'

    active_count = GObject.Property(type=int, default=0)

    __gsignals__ = {
        'task-added':    (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'task-changed':  (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'task-finished': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self, backend, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._tasks = []           # all tasks (recent history + active)
        self._queue = []           # tasks waiting to run
        self._running = False
        self._lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────
    @property
    def tasks(self):
        return list(self._tasks)

    def get_task_for_package(self, package):
        """Return the active task for *package*, or None."""
        for t in reversed(self._tasks):
            if t.package is package and t.is_active:
                return t
        return None

    def submit(self, package, operation):
        """Queue *operation* on *package*. Returns the new Task."""
        _log.info('Submitting task: %s %s (%s)',
                  operation, package.name, package.pkg_type)
        task = Task(package, operation)
        task.connect('notify', lambda *a: GLib.idle_add(self.emit, 'task-changed', task))
        self._tasks.append(task)
        with self._lock:
            self._queue.append(task)
            _log.debug('Queue depth after submit: %d', len(self._queue))
        self._update_active_count()
        self.emit('task-added', task)
        self._maybe_start_next()
        return task

    # ── Convenience wrappers ─────────────────────────────────────
    def install(self, package):
        return self.submit(package, TaskOperation.INSTALL)

    def remove(self, package):
        return self.submit(package, TaskOperation.REMOVE)

    def upgrade(self, package):
        return self.submit(package, TaskOperation.UPGRADE)

    # ── Internal runner ──────────────────────────────────────────
    def _maybe_start_next(self):
        with self._lock:
            if self._running or not self._queue:
                return
            task = self._queue.pop(0)
            self._running = True
        _log.debug('Starting worker thread for: %s', task.title)
        thread = threading.Thread(target=self._run_task, args=(task,), daemon=True)
        thread.start()

    def _run_task(self, task):
        from .backend import _brew_cmd

        GLib.idle_add(task._set_running)

        args = [task.operation]
        if task.qualified_install_name:
            # Fully-qualified name already encodes the tap; no --cask/--formula needed
            args.append(task.qualified_install_name)
        else:
            if task.package.pkg_type == 'cask':
                args.append('--cask')
            args.append(task.package.name)
        cmd = _brew_cmd(args)
        _log.info('Running brew command: %s', ' '.join(cmd))

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            task._process = process
            _log.debug('Subprocess PID: %d', process.pid)

            for line in process.stdout:
                line = line.rstrip('\n')
                task._output_lines.append(line)
                parsed = _parse_phase(line)
                if parsed:
                    label, frac = parsed
                    GLib.idle_add(task._update_phase, label, frac)

            process.wait()
            success = process.returncode == 0
            _log.info('Brew exited: %s  rc=%d  lines=%d',
                      task.title, process.returncode, len(task._output_lines))

            if success:
                GLib.idle_add(self._apply_task_success, task)
            else:
                detail = self._extract_error(task._output_lines)
                conflict = self._detect_multi_tap_conflict(task._output_lines)
                ambiguous = self._detect_ambiguous_taps(task._output_lines)
                _log.warning('Task failed: %s — %s', task.title, detail[:200])
                GLib.idle_add(self._apply_task_failure, task, detail, conflict, ambiguous)

        except Exception as e:
            _log.exception('Exception running task %s', task.title)
            GLib.idle_add(task._set_failed, str(e))

        finally:
            with self._lock:
                self._running = False
            GLib.idle_add(self._finish_task, task)

    MAX_FINISHED_HISTORY = 20

    def _finish_task(self, task):
        self._update_active_count()
        self.emit('task-finished', task)
        # Cap retained history so finished tasks (and the Packages/output
        # they reference) don't accumulate for the app's lifetime.
        finished = [t for t in self._tasks if not t.is_active]
        if len(finished) > self.MAX_FINISHED_HISTORY:
            drop = set(finished[:-self.MAX_FINISHED_HISTORY])
            self._tasks = [t for t in self._tasks if t not in drop]
        # Schedule next queued task
        self._maybe_start_next()

    def clear_finished(self):
        """Drop all finished tasks from history (task panel Clear button)."""
        self._tasks = [t for t in self._tasks if t.is_active]

    def _apply_task_success(self, task):
        self._update_package_state(task)
        task._set_completed()

    def _apply_task_failure(self, task, detail, conflict, ambiguous):
        if conflict:
            installed_tap, target_tap = conflict
            task.conflict_info = {
                'installed_tap': installed_tap,
                'target_tap': target_tap,
            }
            _log.info('Multi-tap conflict for %s: installed from %s, tried %s',
                      task.package.name, installed_tap, target_tap)

        if ambiguous:
            task.ambiguous_taps = ambiguous
            _log.info('Ambiguous taps for %s: %s', task.package.name, ambiguous)
            
        task._set_failed(detail)

    def _update_package_state(self, task):
        """Update the Package object + backend installed sets after a successful op."""
        pkg = task.package
        backend = self._backend
        if task.operation == TaskOperation.INSTALL:
            pkg.installed = True
            if pkg.pkg_type == 'formula':
                backend._installed_formulae.add(pkg.name)
            else:
                backend._installed_casks.add(pkg.name)
        elif task.operation == TaskOperation.REMOVE:
            pkg.installed = False
            if pkg.pkg_type == 'formula':
                backend._installed_formulae.discard(pkg.name)
            else:
                backend._installed_casks.discard(pkg.name)

    def _update_active_count(self):
        count = sum(1 for t in self._tasks if t.is_active)
        if self.active_count != count:
            self.active_count = count

    @staticmethod
    def _extract_error(lines):
        """Pull a short human-readable error from brew output."""
        error_lines = []
        capture = False
        for ln in lines:
            low = ln.lower()
            if 'error' in low or 'fatal' in low or 'failed' in low:
                capture = True
            if capture:
                error_lines.append(ln)
            if len(error_lines) >= 6:
                break
        if error_lines:
            return '\n'.join(error_lines)
        return '\n'.join(lines[-4:]) if lines else 'Unknown error'

    @staticmethod
    def _detect_multi_tap_conflict(lines):
        """Return (installed_tap, target_tap) if a multi-tap conflict is present, else None."""
        text = '\n'.join(lines)
        m = _MULTI_TAP_RE.search(text)
        if m:
            return m.group(2), m.group(3)
        return None

    @staticmethod
    def _detect_ambiguous_taps(lines):
        """Return list of fully-qualified names if an ambiguous-tap error is present, else None."""
        text = '\n'.join(lines)
        if 'exists in multiple taps' not in text.lower():
            return None
        matches = _AMBIGUOUS_TAP_RE.findall(text)
        return matches if len(matches) >= 2 else None

    def install_qualified(self, package, qualified_name):
        """Install a package using a fully-qualified tap/name, e.g. ublue-os/tap/foo."""
        task = self.submit(package, TaskOperation.INSTALL)
        task.qualified_install_name = qualified_name
        return task
