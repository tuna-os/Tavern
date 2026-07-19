# brew_env.py - Homebrew environment discovery and command construction
# SPDX-License-Identifier: GPL-3.0-or-later

import os
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
            _log.info('Found brew via PATH at %s', path)
            return path
    except Exception:
        pass
    _log.warning('brew executable not found; falling back to bare "brew"')
    return 'brew'


IN_FLATPAK = _is_flatpak()
BREW_BIN = _find_brew()
