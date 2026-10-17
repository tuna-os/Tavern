# brew_env.py - Homebrew environment discovery and command construction
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shlex
import shutil
import subprocess

from .logging_util import get_logger

_log = get_logger('brew_env')


# Disable Homebrew's automatic update checks when we run brew commands.
# This prevents random hangs and bandwidth waste on slow/capped connections.
os.environ['HOMEBREW_NO_AUTO_UPDATE'] = '1'
os.environ['HOMEBREW_API_AUTO_UPDATE_SECS'] = '604800'
# Homebrew 6.0.0+ defaults to ask mode (confirmation prompt) — suppress it
# so Tavern's subprocess-driven install/remove/upgrade operations don't hang.
os.environ['HOMEBREW_NO_INSTALL_ASK'] = '1'


#: Official Homebrew installer used by the missing-brew offer.
HOMEBREW_INSTALL_URL = (
    'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh'
)
HOMEBREW_DOC_URL = 'https://brew.sh'

#: Terminal emulators probed (in order) to run the installer interactively.
#: The installer needs a TTY for its `sudo` password prompt, so Tavern never
#: runs it as a captured subprocess — it delegates to a host terminal.
TERMINAL_CANDIDATES = (
    'xdg-terminal-exec',
    'ptyxis',
    'gnome-terminal',
    'kgx',
    'konsole',
    'x-terminal-emulator',
    'xterm',
)

#: Default Homebrew prefixes. System bins (/usr/local/bin, /usr/bin, /bin, ...)
#: must always win over these in PATH (Bluefin parity): `brew shellenv`
#: prepends its bin/sbin dirs, which would otherwise shadow system tools.
#: Note: /usr/local is only treated as a brew prefix when Homebrew is actually
#: configured or installed there (e.g. on Intel macOS), never unconditionally.
_DEFAULT_BREW_PREFIXES = (
    '/home/linuxbrew/.linuxbrew',
    os.path.expanduser('~/.linuxbrew'),
    '/opt/homebrew',
)

#: Pure-bash snippet appended after every `eval "$(brew shellenv)"` on the
#: host side. Moves any *linuxbrew*/*homebrew* PATH entries after everything
#: else using shell builtins only (no awk/python dependency on the host).
_FLATPAK_PATH_REORDER_SNIPPET = (
    '__tavern_sys=""; __tavern_brew=""; '
    'IFS=: read -ra __tavern_parts <<<"$PATH"; '
    'for __tavern_p in "${__tavern_parts[@]}"; do '
    'case "$__tavern_p" in *linuxbrew*|*homebrew*) '
    '__tavern_brew="${__tavern_brew:+$__tavern_brew:}$__tavern_p";; '
    '*) __tavern_sys="${__tavern_sys:+$__tavern_sys:}$__tavern_p";; esac; done; '
    'PATH="${__tavern_sys}${__tavern_brew:+:$__tavern_brew}"; '
    'unset __tavern_sys __tavern_brew __tavern_parts __tavern_p; '
    'export PATH'
)


def _is_flatpak():
    """Detect if running inside a Flatpak sandbox."""
    result = os.path.exists('/.flatpak-info')
    _log.debug('Flatpak detection: %s', result)
    return result


def _find_brew():
    """Find the brew executable."""
    candidates = [
        '/home/linuxbrew/.linuxbrew/bin/brew',
        '/opt/homebrew/bin/brew',
        '/usr/local/bin/brew',
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            _log.info('Found brew at %s', c)
            return c
    # fallback: try PATH
    try:
        result = subprocess.run(['which', 'brew'], capture_output=True, text=True)
        if result.returncode == 0:
            path = result.stdout.strip()
            # A `which` that exits 0 but prints nothing (a shell wrapper, or a
            # mocked/broken which) would otherwise make BREW_BIN the empty
            # string, and callers would exec '' instead of falling through to
            # the bare-'brew' contract below.
            if path:
                _log.info('Found brew via PATH at %s', path)
                return path
    except Exception:
        pass
    _log.warning('brew executable not found; falling back to bare "brew"')
    return 'brew'


IN_FLATPAK = _is_flatpak()
BREW_BIN = _find_brew()


def is_brew_available(brew_bin=None):
    """True when Tavern resolved a real brew executable.

    The sentinel `'brew'` means "not found, exec via PATH and hope" — every
    brew invocation will fail with FileNotFoundError on a host without
    Homebrew. The missing-brew banner/dialog gates on this predicate.
    """
    if brew_bin is None:
        brew_bin = BREW_BIN
    return brew_bin != 'brew' and bool(brew_bin)


def refresh_brew_bin():
    """Re-run brew discovery and update the module global.

    Lets the missing-brew dialog's Retry button pick up a fresh install
    without restarting the app. Returns the new value.
    """
    global BREW_BIN
    BREW_BIN = _find_brew()
    return BREW_BIN


def _brew_bin_dirs(brew_bin=None):
    """Absolute brew bin/sbin dirs that must lose to system dirs in PATH."""
    prefixes = set(_DEFAULT_BREW_PREFIXES)
    prefix_env = os.environ.get('HOMEBREW_PREFIX')
    if prefix_env and os.path.normpath(prefix_env) != '/':
        prefixes.add(prefix_env)
    if brew_bin is None:
        brew_bin = BREW_BIN
    if brew_bin and brew_bin != 'brew' and os.path.isabs(brew_bin):
        parent = os.path.dirname(os.path.dirname(brew_bin))
        if parent and os.path.normpath(parent) != '/':
            prefixes.add(parent)
    dirs = set()
    for prefix in prefixes:
        norm = os.path.normpath(prefix)
        if not norm or norm == '/':
            continue
        dirs.add(os.path.join(norm, 'bin'))
        dirs.add(os.path.join(norm, 'sbin'))
    return dirs


def demote_brew_dirs(path_value, brew_dirs=None):
    """Return PATH with Homebrew bin/sbin moved after all other entries.

    Preserves the relative order inside each group, drops duplicates
    (first occurrence wins within its group), and is idempotent. Entries
    that merely mention homebrew but are not brew bin/sbin dirs (e.g. a
    user's `~/homebrew-tools/bin`) are left in place — only exact brew
    bin/sbin dirs move.
    """
    if not path_value:
        return ''
    if brew_dirs is None:
        brew_dirs = _brew_bin_dirs()
    else:
        brew_dirs = {os.path.normpath(d) for d in brew_dirs}
    system_parts = []
    brew_parts = []
    seen = set()
    for part in path_value.split(os.pathsep):
        norm = os.path.normpath(part) if part else ''
        if not part or norm in seen:
            continue
        seen.add(norm)
        if norm in brew_dirs:
            brew_parts.append(part)
        else:
            system_parts.append(part)
    return os.pathsep.join(system_parts + brew_parts)


def command_env(base=None):
    """Environment for brew child processes: inherited env, system-wins PATH.

    `brew shellenv` (and an interactive shell that already evaluated it) puts
    Homebrew bins ahead of system bins; every brew child would then resolve
    shadowed tools (python3, gcc, …) from Homebrew. Demote brew dirs to the
    end so system tools always win, matching Bluefin behavior.
    """
    env = dict(base if base is not None else os.environ)
    env['PATH'] = demote_brew_dirs(env.get('PATH', ''))
    return env


# Reorder Tavern's own process PATH on import so child processes that inherit
# os.environ without overriding it also keep system bins ahead of Homebrew bins.
if 'PATH' in os.environ:
    os.environ['PATH'] = demote_brew_dirs(os.environ['PATH'])


def build_homebrew_install_command(*, in_flatpak=None):
    """Argv that runs the official Homebrew installer (no `shell=True`).

    Callers must run this in an interactive host terminal (see
    `build_terminal_install_argv`) — never as a captured subprocess —
    because the installer prompts for the `sudo` password.
    """
    in_flatpak = IN_FLATPAK if in_flatpak is None else in_flatpak
    inner = (
        f'/bin/bash -c "$({shlex.quote("/usr/bin/curl")} -fsSL '
        f'{shlex.quote(HOMEBREW_INSTALL_URL)} | /bin/bash)"'
    )
    if in_flatpak:
        return ['flatpak-spawn', '--host', 'bash', '-c', inner]
    return ['/bin/bash', '-c',
            f'$({shlex.quote("/usr/bin/curl")} -fsSL '
            f'{shlex.quote(HOMEBREW_INSTALL_URL)} | /bin/bash)']


def build_terminal_install_argv(terminal_bin, install_cmd=None, *,
                                in_flatpak=None):
    """Wrap the installer argv so it runs inside a host terminal emulator.

    Returns None when `terminal_bin` is falsy (caller falls back to the
    copy-command / open-brew.sh options).
    """
    if not terminal_bin:
        return None
    in_flatpak = IN_FLATPAK if in_flatpak is None else in_flatpak
    if install_cmd is None:
        install_cmd = build_homebrew_install_command(in_flatpak=False)
    hold = 'echo; read -n1 -rsp "Press any key to close..."'
    script = f"{shlex.join(install_cmd)}; rc=$?; {hold}; exit $rc"
    if in_flatpak:
        return ['flatpak-spawn', '--host', terminal_bin,
                '--', '/bin/bash', '-c', script]
    return [terminal_bin, '--', '/bin/bash', '-c', script]


def find_terminal_emulator(candidates=None, which=None):
    """First available terminal emulator from `candidates`, or None."""
    if candidates is None:
        candidates = TERMINAL_CANDIDATES
    which = which or shutil.which
    for candidate in candidates:
        if which(candidate):
            return candidate
    return None


def should_offer_homebrew_install(brew_bin=None, installed_count=None):
    """Headless predicate behind the missing-brew banner (pure, testable).

    The banner shows when no usable brew executable was found. An
    `installed_count` of 0 alone is not sufficient — a healthy host can
    simply have nothing installed — but callers may pass it for logging.
    """
    _ = installed_count
    return not is_brew_available(brew_bin)


def build_command(args, *, in_flatpak=None, brew_bin=None):
    """Build a Homebrew command without depending on the backend facade."""
    in_flatpak = IN_FLATPAK if in_flatpak is None else in_flatpak
    brew_bin = BREW_BIN if brew_bin is None else brew_bin
    if in_flatpak:
        quoted = ' '.join(shlex.quote(str(arg)) for arg in args)
        return [
            'flatpak-spawn', '--host', 'bash', '-c',
            'export HOMEBREW_NO_AUTO_UPDATE=1 && '
            'export HOMEBREW_API_AUTO_UPDATE_SECS=604800 && '
            'export HOMEBREW_NO_INSTALL_ASK=1 && '
            'export HOMEBREW_NO_COLOR=1 && export LC_ALL=C && '
            'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" && '
            + _FLATPAK_PATH_REORDER_SNIPPET
            + f' && brew {quoted}',
        ]
    return [brew_bin, *args]
