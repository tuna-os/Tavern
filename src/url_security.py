# url_security.py - SSRF-safe URL validation for metadata-derived fetches
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Package metadata (homepage, icon_url, README image URLs, scraped favicon
# URLs) is attacker-controlled. This module is the single validator applied
# before every media/favicon/README request in media.py:
#
#   * require https,
#   * reject embedded userinfo and non-default ports,
#   * resolve the hostname and reject loopback / link-local / private /
#     multicast / unspecified / reserved addresses (IPv4 and IPv6),
#   * re-validate each redirect so a public HTTPS site cannot 3xx-drop to
#     127.0.0.1 or an RFC1918 range.
#
# The curated fixed GitHub/Flathub endpoints are listed in CURATED_NETLOCKS so
# they stay explicit rather than being "trusted" through arbitrary DNS.

import ipaddress
import socket
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler

# Always-safe, fixed hosts the media path fetches from by construction. The
# host is pinned literally in media.py (e.g. ``https://github.com/<owner>.png``),
# so an attacker's metadata can never repoint the app at a different host for
# these — DNS resolution is skipped for them, which also avoids offline/DNS
# failures for the endpoints we always want to reach.
CURATED_NETLOCKS = frozenset({
    'github.com',
    'raw.githubusercontent.com',
    'avatars.githubusercontent.com',
    'www.google.com',
    'icons.duckduckgo.com',
    'flathub.org',
})

# https only -> 443. http is rejected outright by the scheme check, so its
# default port never appears here.
_DEFAULT_PORTS = {'https': 443}


def _ip_is_blocked(ip):
    """True if ip is loopback / link-local / private / multicast /
    unspecified / reserved. Covers IPv4 and IPv6 (broadcast falls under
    is_private / is_reserved)."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _resolve_host(host):
    """Return the set of IP addresses host resolves to, or an empty set if it
    cannot be resolved. Never raises — a DNS failure means the URL is unsafe
    for our purposes (we cannot prove it is public)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return set()
    ips = set()
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        # Strip any IPv6 zone id (e.g. fe80::1%eth0) before parsing.
        ips.add(ipaddress.ip_address(addr.split('%', 1)[0]))
    return ips


def is_safe_media_url(url):
    """Return True if ``url`` may be fetched as media.

    Rejects non-HTTPS, embedded userinfo, non-default ports, empty hosts, and
    any hostname whose resolved addresses are loopback / link-local / private /
    multicast / unspecified / reserved. Returns False and never raises, so
    callers can simply skip unsafe candidates.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    scheme = (parsed.scheme or '').lower()
    if scheme != 'https':
        return False
    # userinfo in a metadata URL is a red flag and unnecessary for these fetches.
    if parsed.username is not None or parsed.password is not None:
        return False

    try:
        port = parsed.port
    except ValueError:
        return False  # malformed port
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        return False

    host = (parsed.hostname or '').lower()
    if not host:
        return False

    if host in CURATED_NETLOCKS:
        return True

    ips = _resolve_host(host)
    if not ips:
        return False  # unresolved -> cannot prove public
    return not any(_ip_is_blocked(ip) for ip in ips)


def assert_safe_media_url(url):
    """Raise ``ValueError`` if ``url`` is unsafe to fetch; no-op if safe."""
    if not is_safe_media_url(url):
        raise ValueError(f'blocked unsafe media URL: {url!r}')


class _SSRFRedirectHandler(HTTPRedirectHandler):
    """Follow a redirect only when its target passes ``is_safe_media_url``.

    urllib's default opener follows 3xx redirects blindly, so a public HTTPS
    site can hand off the client to ``http://127.0.0.1``. Re-validating the
    Location before reconnecting closes that SSRF hop.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_safe_media_url(newurl):
            raise ValueError(f'blocked unsafe redirect to {newurl!r}')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_safe_opener():
    """Build a urllib opener that refuses redirect-based SSRF."""
    return build_opener(_SSRFRedirectHandler())
