# test_git_forge.py - Unit tests for git forge integrations
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import urllib.error
from urllib.error import URLError
from io import BytesIO
import pytest

from tavern.git_forge import (
    GitHubForge,
    GitLabForge,
    CodebergForge,
    GiteaForge,
    get_forge_for_url,
    extract_owner_repo_from_url,
)


class TestGitHubForge:
    def test_detect_from_url(self):
        forge = GitHubForge()
        assert forge.detect_from_url("https://github.com/hanthor/tavern") is True
        assert forge.detect_from_url("http://www.github.com/hanthor/tavern") is True
        assert forge.detect_from_url("https://gitlab.com/hanthor/tavern") is False

    def test_get_releases_success(self, monkeypatch):
        mock_response_data = [
            {
                "tag_name": "v1.2.3",
                "published_at": "2026-05-31T10:00:00Z",
                "body": "This is a release changelog.",
            },
            {
                "tag_name": "v1.2.2",
                "published_at": "2026-05-20T10:00:00Z",
                "name": "Fallback Release Title",
            }
        ]
        
        class MockResponse:
            def __init__(self, data):
                self.data = json.dumps(data).encode("utf-8")
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        monkeypatch.setattr("tavern.git_forge.urlopen", lambda req, timeout=None: MockResponse(mock_response_data))

        forge = GitHubForge()
        releases = forge.get_releases("hanthor", "tavern")
        assert len(releases) == 2
        assert releases[0]["version"] == "1.2.3"
        assert releases[0]["date"] == "2026-05-31"
        assert releases[0]["changelog"] == "This is a release changelog."
        assert releases[1]["version"] == "1.2.2"
        assert releases[1]["changelog"] == "Fallback Release Title"

    def test_get_releases_url_error(self, monkeypatch):
        def mock_urlopen_error(*args, **kwargs):
            raise URLError("Connection timed out")
        
        monkeypatch.setattr("tavern.git_forge.urlopen", mock_urlopen_error)
        
        forge = GitHubForge()
        releases = forge.get_releases("hanthor", "tavern")
        assert releases == []

    def test_get_releases_generic_error(self, monkeypatch):
        def mock_urlopen_bug(*args, **kwargs):
            raise ValueError("Something unexpected")
        
        monkeypatch.setattr("tavern.git_forge.urlopen", mock_urlopen_bug)
        
        forge = GitHubForge()
        releases = forge.get_releases("hanthor", "tavern")
        assert releases == []


class TestGitLabForge:
    def test_detect_from_url(self):
        forge = GitLabForge()
        assert forge.detect_from_url("https://gitlab.com/hanthor/tavern") is True
        assert forge.detect_from_url("https://github.com/hanthor/tavern") is False

    def test_get_releases_success(self, monkeypatch):
        mock_response_data = [
            {
                "tag_name": "v2.0.0",
                "released_at": "2026-05-31T10:00:00.000Z",
                "description": "GitLab release description.",
            }
        ]

        class MockResponse:
            def __init__(self, data):
                self.data = json.dumps(data).encode("utf-8")
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        monkeypatch.setattr("tavern.git_forge.urlopen", lambda req, timeout=None: MockResponse(mock_response_data))

        forge = GitLabForge()
        releases = forge.get_releases("hanthor", "tavern")
        assert len(releases) == 1
        assert releases[0]["version"] == "2.0.0"
        assert releases[0]["date"] == "2026-05-31"
        assert releases[0]["changelog"] == "GitLab release description."

    def test_get_releases_url_error(self, monkeypatch):
        def mock_urlopen_error(*args, **kwargs):
            raise URLError("Connection timed out")
        
        monkeypatch.setattr("tavern.git_forge.urlopen", mock_urlopen_error)
        
        forge = GitLabForge()
        releases = forge.get_releases("hanthor", "tavern")
        assert releases == []


class TestCodebergForge:
    def test_detect_from_url(self):
        forge = CodebergForge()
        assert forge.detect_from_url("https://codeberg.org/hanthor/tavern") is True
        assert forge.detect_from_url("https://github.com/hanthor/tavern") is False

    def test_get_releases_success(self, monkeypatch):
        mock_response_data = [
            {
                "tag_name": "v3.1.2",
                "published_at": "2026-05-30T10:00:00Z",
                "body": "Codeberg release details.",
            }
        ]

        class MockResponse:
            def __init__(self, data):
                self.data = json.dumps(data).encode("utf-8")
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        monkeypatch.setattr("tavern.git_forge.urlopen", lambda req, timeout=None: MockResponse(mock_response_data))

        forge = CodebergForge()
        releases = forge.get_releases("hanthor", "tavern")
        assert len(releases) == 1
        assert releases[0]["version"] == "3.1.2"
        assert releases[0]["changelog"] == "Codeberg release details."

    def test_get_releases_url_error(self, monkeypatch):
        def mock_urlopen_error(*args, **kwargs):
            raise URLError("Codeberg offline")
        
        monkeypatch.setattr("tavern.git_forge.urlopen", mock_urlopen_error)
        
        forge = CodebergForge()
        releases = forge.get_releases("hanthor", "tavern")
        assert releases == []


class TestGiteaForge:
    def test_detect_from_url(self):
        forge = GiteaForge("https://gitea.example.com")
        assert forge.detect_from_url("https://gitea.example.com/user/repo") is True
        assert forge.detect_from_url("https://gitea.other.com/user/repo") is False

    def test_get_releases_success(self, monkeypatch):
        mock_response_data = [
            {
                "tag_name": "1.0",
                "published_at": "2026-05-29T10:00:00Z",
                "name": "Gitea Release",
            }
        ]

        class MockResponse:
            def __init__(self, data):
                self.data = json.dumps(data).encode("utf-8")
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        monkeypatch.setattr("tavern.git_forge.urlopen", lambda req, timeout=None: MockResponse(mock_response_data))

        forge = GiteaForge("https://gitea.example.com")
        releases = forge.get_releases("user", "repo")
        assert len(releases) == 1
        assert releases[0]["version"] == "1.0"
        assert releases[0]["changelog"] == "Gitea Release"

    def test_get_releases_url_error(self, monkeypatch):
        def mock_urlopen_error(*args, **kwargs):
            raise URLError("Gitea offline")
        
        monkeypatch.setattr("tavern.git_forge.urlopen", mock_urlopen_error)
        
        forge = GiteaForge("https://gitea.example.com")
        releases = forge.get_releases("user", "repo")
        assert releases == []


def test_get_forge_for_url():
    # Valid GitHub
    forge, owner, repo = get_forge_for_url("https://github.com/hanthor/tavern.git")
    assert isinstance(forge, GitHubForge)
    assert owner == "hanthor"
    assert repo == "tavern"

    # Valid GitLab
    forge, owner, repo = get_forge_for_url("https://gitlab.com/hanthor/tavern.git")
    assert isinstance(forge, GitLabForge)
    assert owner == "hanthor"
    assert repo == "tavern"

    # Valid Codeberg
    forge, owner, repo = get_forge_for_url("https://codeberg.org/hanthor/tavern")
    assert isinstance(forge, CodebergForge)
    assert owner == "hanthor"
    assert repo == "tavern"

    # Unknown url type
    forge, owner, repo = get_forge_for_url("https://example.com/user/project")
    assert forge is None
    assert owner is None
    assert repo is None

    # Invalid types
    assert get_forge_for_url(None) == (None, None, None)
    assert get_forge_for_url(123) == (None, None, None)


def test_extract_owner_repo_from_url():
    assert extract_owner_repo_from_url("https://github.com/hanthor/tavern") == ("hanthor", "tavern")
    assert extract_owner_repo_from_url("git@github.com:hanthor/tavern.git") == ("hanthor", "tavern")
    assert extract_owner_repo_from_url("/var/home/james/dev/Tavern") == ("dev", "Tavern")
    assert extract_owner_repo_from_url(None) == (None, None)
