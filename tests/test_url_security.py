# test_url_security.py - Branch tests for the SSRF validator (src/url_security.py)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# test_media.py drives the validator through MediaMixin. These cover the
# branches that file never reaches: resolver failures, mixed public/private
# answers, IPv6 zone ids, unparsable URLs and ports, the assert_* contract,
# and the best-effort TCP_NODELAY. No GTK and no network.

import socket

import pytest

import tavern.url_security as us


def _answers(*ips):
    """A getaddrinfo stand-in returning one TCP entry per address."""
    def fake(host, port, proto=0, *args, **kwargs):
        family = socket.AF_INET6 if any(':' in ip for ip in ips) else socket.AF_INET
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (ip, 0)) for ip in ips]
    return fake


class TestResolveHost:
    @pytest.mark.parametrize('exc', [
        socket.gaierror('no such host'),
        UnicodeError('label too long'),
        OSError('network is down'),
    ])
    def test_resolver_failure_yields_empty_set(self, monkeypatch, exc):
        def boom(*args, **kwargs):
            raise exc
        monkeypatch.setattr(us.socket, 'getaddrinfo', boom)
        assert us._resolve_host('x.example') == set()

    def test_resolver_failure_makes_url_unsafe(self, monkeypatch):
        def boom(*args, **kwargs):
            raise socket.gaierror('no such host')
        monkeypatch.setattr(us.socket, 'getaddrinfo', boom)
        assert us.validate_media_url_and_ip('https://x.example/a.png') == (False, None)

    def test_ipv6_zone_id_is_stripped_before_parsing(self, monkeypatch):
        monkeypatch.setattr(us.socket, 'getaddrinfo', _answers('fe80::1%eth0'))
        ips = us._resolve_host('zone.example')
        assert [str(ip) for ip in ips] == ['fe80::1']

    def test_zone_id_link_local_is_blocked(self, monkeypatch):
        monkeypatch.setattr(us.socket, 'getaddrinfo', _answers('fe80::1%eth0'))
        assert us.validate_media_url_and_ip('https://zone.example/a.png') == (False, None)

    def test_duplicate_answers_collapse(self, monkeypatch):
        monkeypatch.setattr(us.socket, 'getaddrinfo',
                            _answers('93.184.216.34', '93.184.216.34'))
        assert len(us._resolve_host('dup.example')) == 1


class TestValidateMediaUrlAndIp:
    def test_one_blocked_answer_rejects_a_mixed_record_set(self, monkeypatch):
        # A hostname that also resolves to loopback must not pass on the
        # strength of its public record.
        monkeypatch.setattr(us.socket, 'getaddrinfo',
                            _answers('93.184.216.34', '127.0.0.1'))
        assert us.validate_media_url_and_ip('https://mixed.example/a.png') == (False, None)

    def test_public_host_returns_the_pinned_address(self, monkeypatch):
        monkeypatch.setattr(us.socket, 'getaddrinfo', _answers('93.184.216.34'))
        assert us.validate_media_url_and_ip('https://public.example/a.png') == (
            True, '93.184.216.34')

    def test_public_ipv6_is_pinned_as_text(self, monkeypatch):
        monkeypatch.setattr(us.socket, 'getaddrinfo', _answers('2001:4860:4860::8888'))
        assert us.validate_media_url_and_ip('https://v6.example/a.png') == (
            True, '2001:4860:4860::8888')

    def test_curated_host_has_no_pin_and_skips_dns(self, monkeypatch):
        def no_dns(*args, **kwargs):
            raise AssertionError('curated hosts must not be resolved')
        monkeypatch.setattr(us.socket, 'getaddrinfo', no_dns)
        assert us.validate_media_url_and_ip('https://github.com/o.png') == (True, None)

    def test_scheme_and_host_are_case_insensitive(self, monkeypatch):
        def no_dns(*args, **kwargs):
            raise AssertionError('curated hosts must not be resolved')
        monkeypatch.setattr(us.socket, 'getaddrinfo', no_dns)
        assert us.validate_media_url_and_ip('HTTPS://GitHub.COM/o.png') == (True, None)

    def test_curated_host_still_needs_https_and_default_port(self):
        assert us.validate_media_url_and_ip('http://github.com/o.png') == (False, None)
        assert us.validate_media_url_and_ip('https://github.com:8443/o.png') == (False, None)
        assert us.validate_media_url_and_ip('https://u@github.com/o.png') == (False, None)

    def test_password_only_userinfo_rejected(self):
        assert us.validate_media_url_and_ip('https://:pw@github.com/o.png') == (False, None)

    @pytest.mark.parametrize('url', [
        'https://example.com:notaport/a.png',   # non-numeric port
        'https://example.com:99999/a.png',      # out of range
    ])
    def test_unparsable_port_rejected(self, url):
        assert us.validate_media_url_and_ip(url) == (False, None)

    def test_unparsable_url_rejected(self):
        # An unbalanced IPv6 bracket makes urlparse raise ValueError.
        assert us.validate_media_url_and_ip('https://[::1/a.png') == (False, None)

    @pytest.mark.parametrize('ip', [
        '127.0.0.1', '10.0.0.1', '169.254.169.254', '0.0.0.0', '100.64.0.1',
        '::1', 'fe80::1', 'fc00::1', '::ffff:127.0.0.1',
    ])
    def test_literal_ip_hosts_are_resolved_and_blocked(self, monkeypatch, ip):
        host = f'[{ip}]' if ':' in ip else ip
        monkeypatch.setattr(us.socket, 'getaddrinfo', _answers(ip))
        assert us.validate_media_url_and_ip(f'https://{host}/a.png') == (False, None)


class TestAssertSafeMediaUrl:
    def test_unsafe_url_raises_naming_the_url(self):
        with pytest.raises(ValueError, match='blocked unsafe media URL'):
            us.assert_safe_media_url('http://127.0.0.1/secret')

    def test_curated_url_returns_no_pin(self):
        assert us.assert_safe_media_url('https://flathub.org/x.png') is None

    def test_public_url_returns_the_pin(self, monkeypatch):
        monkeypatch.setattr(us.socket, 'getaddrinfo', _answers('93.184.216.34'))
        assert us.assert_safe_media_url('https://public.example/a.png') == '93.184.216.34'


class TestIpIsBlocked:
    @pytest.mark.parametrize('ip', [
        '255.255.255.255', '240.0.0.1', '192.0.2.1', '198.51.100.1',
        '100.64.0.1', '224.0.0.1', '::', 'ff02::1', '2001:db8::1',
    ])
    def test_non_global_ranges_blocked(self, ip):
        assert us._ip_is_blocked(us.ipaddress.ip_address(ip))

    @pytest.mark.parametrize('ip', ['93.184.216.34', '1.1.1.1', '2001:4860:4860::8888'])
    def test_global_addresses_allowed(self, ip):
        assert not us._ip_is_blocked(us.ipaddress.ip_address(ip))


class TestPinnedConnectionBestEffort:
    def test_tcp_nodelay_failure_does_not_abort_connect(self):
        wrapped = []

        class Sock:
            def setsockopt(self, *args):
                raise OSError('not supported')

        class Context:
            def wrap_socket(self, sock, server_hostname):
                wrapped.append(server_hostname)
                return sock

        conn = us.PinnedHTTPSConnection('host.example', 443, pinned_ip='93.184.216.34')
        conn._create_connection = lambda *a, **k: Sock()
        conn._context = Context()
        conn.connect()
        assert wrapped == ['host.example']


class TestBuildSafeOpener:
    def test_opener_uses_pinned_https_and_ssrf_redirect_handlers(self):
        opener = us.build_safe_opener()
        kinds = {type(h) for h in opener.handlers}
        assert us.PinnedHTTPSHandler in kinds
        assert us._SSRFRedirectHandler in kinds

    def test_stock_redirect_handler_is_replaced(self):
        opener = us.build_safe_opener()
        redirects = [h for h in opener.handlers if hasattr(h, 'redirect_request')]
        assert [type(h) for h in redirects] == [us._SSRFRedirectHandler]

    def test_redirect_to_unsafe_host_raises_before_any_request_is_built(self):
        from urllib.request import Request
        handler = us._SSRFRedirectHandler()
        with pytest.raises(ValueError, match='blocked unsafe redirect'):
            handler.redirect_request(Request('https://github.com/a'), None, 302, '', {},
                                     'https://user@github.com/b')
