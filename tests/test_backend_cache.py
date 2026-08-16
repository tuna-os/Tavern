# test_backend_cache.py - Tests for the CacheMixin extracted from BrewBackend
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The refactor (tuna-os/Tavern#90, issue #81) moved Brewfile parsing and
# cache I/O into src/backend_cache.py with zero tests. These cover the pure
# logic: Brewfile line parsing, JSON cache read/write + staleness, the Linux
# cask filter, and host Homebrew JWS cache reads.

import json
import os
import sys
import time

import pytest

from tavern.backend_cache import CacheMixin


class FakeCache(CacheMixin):
    """Minimal host for the mixin — provides the two attributes it expects."""

    def __init__(self, cache_dir, update_status=None):
        self._cache_dir = str(cache_dir)
        self._update_status = update_status or (lambda msg: None)


def write_brewfile(tmp_path, text):
    path = tmp_path / "Brewfile"
    path.write_text(text, encoding="utf-8")
    return path


# ── parse_brewfile ─────────────────────────────────────────────────────────

class TestParseBrewfile:
    def test_parses_all_four_kinds(self, tmp_path):
        bf = write_brewfile(
            tmp_path,
            'tap "owner/repo"\n'
            'brew "ripgrep"\n'
            "cask 'firefox'\n"
            'flatpak "org.gnome.Boxes"\n',
        )
        result = FakeCache(tmp_path).parse_brewfile(bf)
        assert result == {
            "taps": [{"name": "owner/repo", "trusted": False}],
            "formulae": ["ripgrep"],
            "casks": ["firefox"],
            "flatpaks": ["org.gnome.Boxes"],
        }

    def test_tap_trusted_flag(self, tmp_path):
        bf = write_brewfile(tmp_path, 'tap "owner/repo", trusted: true\n')
        result = FakeCache(tmp_path).parse_brewfile(bf)
        assert result["taps"] == [{"name": "owner/repo", "trusted": True}]

    def test_single_quoted_names(self, tmp_path):
        bf = write_brewfile(tmp_path, "brew 'ripgrep'\ncask 'firefox'\n")
        result = FakeCache(tmp_path).parse_brewfile(bf)
        assert result["formulae"] == ["ripgrep"]
        assert result["casks"] == ["firefox"]

    def test_malformed_and_comment_lines_ignored(self, tmp_path):
        bf = write_brewfile(
            tmp_path,
            "# a comment\n"
            "\n"
            "brew \"unterminated\n"
            "  brew   \"with-leading-space\"\n"
            "unknown \"directive\"\n",
        )
        result = FakeCache(tmp_path).parse_brewfile(bf)
        assert result["formulae"] == ["with-leading-space"]
        assert result["taps"] == []
        assert result["casks"] == []
        assert result["flatpaks"] == []

    def test_brewfile_missing_returns_empty(self, tmp_path):
        result = FakeCache(tmp_path).parse_brewfile(tmp_path / "nope")
        assert result == {"taps": [], "formulae": [], "casks": [], "flatpaks": []}

    def test_output_keys_are_stable(self, tmp_path):
        bf = write_brewfile(tmp_path, "brew \"a\"\n")
        assert list(FakeCache(tmp_path).parse_brewfile(bf).keys()) == [
            "taps", "formulae", "casks", "flatpaks",
        ]


# ── cache path / read / write ──────────────────────────────────────────────

class TestCacheIo:
    def test_cache_path_joins_dir(self, tmp_path):
        assert FakeCache(tmp_path)._cache_path("brewfile") == str(
            tmp_path / "brewfile.json"
        )

    def test_save_then_load_round_trip(self, tmp_path, monkeypatch):
        cache = FakeCache(tmp_path)
        monkeypatch.setattr("tavern.backend_cache.GLib.get_real_time", lambda: 1_000_000_000 * 1e6)
        cache._save_cache("state", {"k": "v", "n": [1, 2, 3]})
        data, stale = cache._load_cached("state")
        assert data == {"k": "v", "n": [1, 2, 3]}
        assert stale is False

    def test_load_missing_is_stale(self, tmp_path):
        data, stale = FakeCache(tmp_path)._load_cached("missing")
        assert data is None
        assert stale is True

    def test_load_stale_when_older_than_max_age(self, tmp_path, monkeypatch):
        cache = FakeCache(tmp_path)
        cache._save_cache("state", {"k": "v"})
        # Age is computed against the file mtime; force a very old mtime.
        old = time.time() - 7200
        os.utime(cache._cache_path("state"), (old, old))
        data, stale = cache._load_cached("state", max_age=3600)
        assert data == {"k": "v"}
        assert stale is True

    def test_load_corrupt_json_is_treated_as_miss(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")
        data, stale = FakeCache(tmp_path)._load_cached("broken")
        assert data is None
        assert stale is True

    def test_save_writes_valid_json_with_newline_preserved(self, tmp_path):
        FakeCache(tmp_path)._save_cache("state", {"a": 1})
        raw = (tmp_path / "state.json").read_text()
        assert json.loads(raw) == {"a": 1}


# ── _filter_linux_casks (pure) ─────────────────────────────────────────────

class TestFilterLinuxCasks:
    @pytest.mark.parametrize("platform", ["linux", "linux2"])
    def test_drops_macos_only_casks_on_linux(self, tmp_path, monkeypatch, platform):
        monkeypatch.setattr(sys, "platform", platform)
        data = [
            {"name": "mac-only", "depends_on": {"macos": ">= 11"}},
            {"name": "linux-ok", "depends_on": {"linux": "x86_64"}},
            {"name": "no-deps", "depends_on": {}},
            {"name": "missing-key"},
        ]
        names = [d["name"] for d in FakeCache(tmp_path)._filter_linux_casks(data)]
        assert names == ["linux-ok", "no-deps", "missing-key"]

    def test_keeps_everything_on_macos(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        data = [{"name": "mac-only", "depends_on": {"macos": ">= 11"}}]
        assert FakeCache(tmp_path)._filter_linux_casks(data) == data


# ── host Homebrew JWS cache reads ──────────────────────────────────────────

class TestHostJws:
    def test_brew_cache_paths_shape(self):
        paths = FakeCache("/tmp")._get_host_brew_cache_paths()
        assert paths["formula"].endswith(".cache/Homebrew/api/formula.jws.json")
        assert "formula.jws.json" in paths["formula"]
        assert "cask.jws.json" in paths["cask"]

    def test_missing_jws_returns_none(self, tmp_path):
        cache = FakeCache(tmp_path)
        assert cache._load_from_host_jws("formula") is None

    def test_parses_string_payload(self, tmp_path, monkeypatch):
        jws = tmp_path / "formula.jws.json"
        jws.write_text(json.dumps({"payload": json.dumps([{"name": "ripgrep"}])}))
        cache = FakeCache(tmp_path)
        monkeypatch.setattr(cache, "_get_host_brew_cache_paths",
                            lambda: {"formula": str(jws), "cask": ""})
        assert cache._load_from_host_jws("formula") == [{"name": "ripgrep"}]

    def test_parses_dict_payload(self, tmp_path, monkeypatch):
        jws = tmp_path / "cask.jws.json"
        jws.write_text(json.dumps({"payload": {"items": 1}}))
        cache = FakeCache(tmp_path)
        monkeypatch.setattr(cache, "_get_host_brew_cache_paths",
                            lambda: {"formula": "", "cask": str(jws)})
        assert cache._load_from_host_jws("cask") == {"items": 1}

    def test_missing_payload_key_returns_none(self, tmp_path, monkeypatch):
        jws = tmp_path / "formula.jws.json"
        jws.write_text(json.dumps({"something": "else"}))
        cache = FakeCache(tmp_path)
        monkeypatch.setattr(cache, "_get_host_brew_cache_paths",
                            lambda: {"formula": str(jws), "cask": ""})
        assert cache._load_from_host_jws("formula") is None

    def test_corrupt_jws_returns_none(self, tmp_path, monkeypatch):
        jws = tmp_path / "formula.jws.json"
        jws.write_text("corrupt{{{")
        cache = FakeCache(tmp_path)
        monkeypatch.setattr(cache, "_get_host_brew_cache_paths",
                            lambda: {"formula": str(jws), "cask": ""})
        assert cache._load_from_host_jws("formula") is None

    def test_reports_status_for_host_catalog(self, tmp_path, monkeypatch):
        jws = tmp_path / "formula.jws.json"
        jws.write_text(json.dumps({"payload": json.dumps([])}))
        messages = []
        cache = FakeCache(tmp_path, update_status=messages.append)
        monkeypatch.setattr(cache, "_get_host_brew_cache_paths",
                            lambda: {"formula": str(jws), "cask": ""})
        cache._load_from_host_jws("formula")
        assert any("formulae" in m for m in messages)
