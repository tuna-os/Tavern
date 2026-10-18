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
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler
import http.client

# Always-safe, fixed hosts the media path fetches from by construction. The
# host is pinned literally in media.py (e.g. ``https://github.com/<owner>.png``),
# so an attacker's metadata can never repoint the app at a different host for
# these — live DNS pinning is skipped for them, which also avoids offline/DNS
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


def validate_media_url_and_ip(url):
    """Validate that ``url`` is safe to fetch and return (is_safe, pinned_ip).

    For curated hosts, returns (True, None).
    For non-curated hosts, resolves the hostname once:
    - If all resolved IP addresses are safe (public), returns (True, str(first_ip)).
    - If any resolved IP is blocked or unresolvable, returns (False, None).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, None

    scheme = (parsed.scheme or '').lower()
    if scheme != 'https':
        return False, None
    if parsed.username is not None or parsed.password is not None:
        return False, None

    try:
        port = parsed.port
    except ValueError:
        return False, None
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        return False, None

    host = (parsed.hostname or '').lower()
    if not host:
        return False, None

    if host in CURATED_NETLOCKS:
        return True, None

    ips = _resolve_host(host)
    if not ips:
        return False, None
    if any(_ip_is_blocked(ip) for ip in ips):
        return False, None

    # Return string representation of the first verified public IP
    first_ip = next(iter(ips))
    return True, str(first_ip)


def is_safe_media_url(url):
    """Return True if ``url`` may be fetched as media.

    Rejects non-HTTPS, embedded userinfo, non-default ports, empty hosts, and
    any hostname whose resolved addresses are loopback / link-local / private /
    multicast / unspecified / reserved. Returns False and never raises, so
    callers can simply skip unsafe candidates.
    """
    safe, _ = validate_media_url_and_ip(url)
    return safe


def assert_safe_media_url(url):
    """Raise ``ValueError`` if ``url`` is unsafe to fetch; return pinned IP if safe."""
    safe, pinned_ip = validate_media_url_and_ip(url)
    if not safe:
        raise ValueError(f'blocked unsafe media URL: {url!r}')
    return pinned_ip


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that connects directly to a pre-validated IP address
    while retaining the original hostname for SNI and HTTP Host header.
    """

    def __init__(self, host, port=None, **kwargs):
        self._pinned_ip = kwargs.pop('pinned_ip', None)
        super().__init__(host, port, **kwargs)

    def connect(self):
        dest_host = self._pinned_ip if self._pinned_ip else self.host
        self.sock = self._create_connection(
            (dest_host, self.port), self.timeout, self.source_address
        )
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

        if self._tunnel_host:
            self._tunnel()

        server_hostname = self._tunnel_host if self._tunnel_host else self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class PinnedHTTPSHandler(HTTPSHandler):
    """HTTPSHandler that passes the request's approved pinned IP to PinnedHTTPSConnection."""

    def https_open(self, req):
        pinned_ip = getattr(req, '_pinned_ip', None)
        return self.do_open(
            lambda host, **kwargs: PinnedHTTPSConnection(host, pinned_ip=pinned_ip, **kwargs),
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


class _SSRFRedirectHandler(HTTPRedirectHandler):
    """Follow a redirect only when its target passes ``validate_media_url_and_ip``.

    urllib's default opener follows 3xx redirects blindly, so a public HTTPS
    site can hand off the client to ``http://127.0.0.1``. Re-validating the
    Location before reconnecting closes that SSRF hop.
    Binds the validated IP address to the redirect request to prevent DNS rebinding.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe, pinned_ip = validate_media_url_and_ip(newurl)
        if not safe:
            raise ValueError(f'blocked unsafe redirect to {newurl!r}')
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            new_req._pinned_ip = pinned_ip
        return new_req


def build_safe_opener():
    """Build a urllib opener that refuses redirect-based SSRF and binds validated DNS."""
    return build_opener(PinnedHTTPSHandler(), _SSRFRedirectHandler())
