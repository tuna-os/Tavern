# backend_transport.py - Shared backend command and HTTP transport boundary
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transport seams shared by backend mixins, independent of the facade.

Patch this module in tests. Media uses a separate, guarded opener so its
untrusted URLs retain SSRF and redirect validation.
"""

from urllib.request import urlopen  # noqa: F401 (shared API transport seam)

from . import brew_env
from .url_security import assert_safe_media_url, build_safe_opener


def _brew_cmd(args):
    """Build argv using the current Homebrew environment and quoting policy."""
    return brew_env.build_command(args)


# Media fetches go through this redirect-aware opener (see
# url_security.build_safe_opener): it re-validates every 3xx target, so a
# public HTTPS site cannot hand the client off to http://127.0.0.1 or an
# RFC1918 range. Built once at import — urllib openers are thread-safe.
_MEDIA_OPENER = build_safe_opener()


def media_urlopen(req, timeout=None):
    """Validate the request URL against the SSRF policy, then fetch it.

    The URL is rejected before any connection when it is not https, carries
    userinfo, uses a non-default port, or resolves to a loopback / private /
    link-local / multicast / reserved address. Redirects are re-validated by
    _MEDIA_OPENER, so a public HTTPS site cannot 3xx-drop to a local address.
    Fetch callers wrap this in try/except and skip the failed source, so an
    unsafe metadata URL is simply never fetched.
    """
    url = req.full_url if hasattr(req, 'full_url') else str(req)
    assert_safe_media_url(url)
    return _MEDIA_OPENER.open(req, timeout=timeout)

