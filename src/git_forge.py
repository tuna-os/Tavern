# git_forge.py - Abstract interface and implementations for different git forges
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Support for fetching release/version information from different git forges.
Currently supports: GitHub, GitLab, Codeberg (Gitea), Gitea (generic).
"""

import re
import json
from abc import ABC, abstractmethod
from urllib.request import urlopen, Request
from urllib.error import URLError

from .logging_util import get_logger

_log = get_logger('git_forge')


class GitForge(ABC):
    """Abstract base class for different git forges."""
    
    @abstractmethod
    def detect_from_url(self, url: str) -> bool:
        """Check if this forge matches the given repository URL."""
        pass
    
    @abstractmethod
    def get_releases(self, owner: str, repo: str) -> list:
        """Fetch releases/tags from the repository.
        
        Returns list of dicts: [{version, date, changelog}, ...]
        """
        pass


class GitHubForge(GitForge):
    """GitHub releases fetcher."""
    
    DOMAIN_PATTERN = re.compile(r'(?:https?://)?(?:www\.)?github\.com')
    REPO_PATTERN = re.compile(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)')
    API_BASE = 'https://api.github.com/repos'
    
    def detect_from_url(self, url: str) -> bool:
        """Check if URL is a GitHub project."""
        return bool(self.DOMAIN_PATTERN.search(url))
    
    def get_releases(self, owner: str, repo: str) -> list:
        """Fetch releases from GitHub API."""
        try:
            api_url = f'{self.API_BASE}/{owner}/{repo}/releases'
            _log.debug('Fetching GitHub releases: %s', api_url)
            
            req = Request(api_url, headers={'User-Agent': 'Tavern/0.1'})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            releases = []
            for release in data:
                version = release.get('tag_name', '').lstrip('v')
                date = release.get('published_at', '')[:10]  # YYYY-MM-DD
                changelog = release.get('body', '') or release.get('name', 'No description')
                
                if version:
                    releases.append({
                        'version': version,
                        'date': date,
                        'changelog': changelog,
                    })
            
            _log.info('Fetched %d releases from GitHub', len(releases))
            return releases
        
        except URLError as e:
            _log.warning('Failed to fetch GitHub releases: %s', e)
            return []
        except Exception as e:
            _log.error('Error parsing GitHub releases: %s', e)
            return []


class GitLabForge(GitForge):
    """GitLab releases fetcher (also supports self-hosted GitLab)."""
    
    DOMAIN_PATTERN = re.compile(r'(?:https?://)?(?:www\.)?gitlab\.com')
    REPO_PATTERN = re.compile(r'(https?://[^/]+)/(.+?)(?:\.git)?$')
    
    def detect_from_url(self, url: str) -> bool:
        """Check if URL is a GitLab project."""
        return bool(self.DOMAIN_PATTERN.search(url))
    
    def get_releases(self, owner: str, repo: str, base_url: str = 'https://gitlab.com') -> list:
        """Fetch releases from GitLab API.
        
        Args:
            owner: GitLab username/group
            repo: Repository name
            base_url: Base URL for GitLab instance (default: gitlab.com)
        """
        try:
            # GitLab API uses project ID, but we can use path encoding
            project_path = f'{owner}%2F{repo}'.replace('/', '%2F')
            api_url = f'{base_url}/api/v4/projects/{project_path}/releases'
            _log.debug('Fetching GitLab releases: %s', api_url)
            
            req = Request(api_url, headers={'User-Agent': 'Tavern/0.1'})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            releases = []
            for release in data:
                version = release.get('tag_name', '').lstrip('v')
                date = release.get('released_at', '')[:10]  # YYYY-MM-DD
                changelog = release.get('description', '') or release.get('name', 'No description')
                
                if version:
                    releases.append({
                        'version': version,
                        'date': date,
                        'changelog': changelog,
                    })
            
            _log.info('Fetched %d releases from GitLab', len(releases))
            return releases
        
        except URLError as e:
            _log.warning('Failed to fetch GitLab releases: %s', e)
            return []
        except Exception as e:
            _log.error('Error parsing GitLab releases: %s', e)
            return []


class CodebergForge(GitForge):
    """Codeberg (Gitea instance) releases fetcher."""
    
    DOMAIN_PATTERN = re.compile(r'(?:https?://)?(?:www\.)?codeberg\.org')
    REPO_PATTERN = re.compile(r'codeberg\.org/([^/\s"\']+)/([^/\s"\'#?.]+)')
    API_BASE = 'https://codeberg.org/api/v1/repos'
    
    def detect_from_url(self, url: str) -> bool:
        """Check if URL is a Codeberg project."""
        return bool(self.DOMAIN_PATTERN.search(url))
    
    def get_releases(self, owner: str, repo: str) -> list:
        """Fetch releases from Codeberg (Gitea) API."""
        try:
            api_url = f'{self.API_BASE}/{owner}/{repo}/releases'
            _log.debug('Fetching Codeberg releases: %s', api_url)
            
            req = Request(api_url, headers={'User-Agent': 'Tavern/0.1'})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            releases = []
            for release in data:
                version = release.get('tag_name', '').lstrip('v')
                date = release.get('published_at', '')[:10]  # YYYY-MM-DD
                changelog = release.get('body', '') or release.get('name', 'No description')
                
                if version:
                    releases.append({
                        'version': version,
                        'date': date,
                        'changelog': changelog,
                    })
            
            _log.info('Fetched %d releases from Codeberg', len(releases))
            return releases
        
        except URLError as e:
            _log.warning('Failed to fetch Codeberg releases: %s', e)
            return []
        except Exception as e:
            _log.error('Error parsing Codeberg releases: %s', e)
            return []


class GiteaForge(GitForge):
    """Generic Gitea instance releases fetcher (self-hosted)."""
    
    REPO_PATTERN = re.compile(r'(https?://[^/]+)/([^/]+)/([^/]+)')
    
    def __init__(self, base_url: str):
        """Initialize with Gitea instance base URL."""
        self.base_url = base_url
    
    def detect_from_url(self, url: str) -> bool:
        """Check if URL is from this Gitea instance."""
        return url.startswith(self.base_url)
    
    def get_releases(self, owner: str, repo: str) -> list:
        """Fetch releases from Gitea API."""
        try:
            api_url = f'{self.base_url}/api/v1/repos/{owner}/{repo}/releases'
            _log.debug('Fetching Gitea releases: %s', api_url)
            
            req = Request(api_url, headers={'User-Agent': 'Tavern/0.1'})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            releases = []
            for release in data:
                version = release.get('tag_name', '').lstrip('v')
                date = release.get('published_at', '')[:10]  # YYYY-MM-DD
                changelog = release.get('body', '') or release.get('name', 'No description')
                
                if version:
                    releases.append({
                        'version': version,
                        'date': date,
                        'changelog': changelog,
                    })
            
            _log.info('Fetched %d releases from Gitea', len(releases))
            return releases
        
        except URLError as e:
            _log.warning('Failed to fetch Gitea releases: %s', e)
            return []
        except Exception as e:
            _log.error('Error parsing Gitea releases: %s', e)
            return []


def get_forge_for_url(source_url: str) -> tuple:
    """Detect which forge a URL belongs to and extract owner/repo.
    
    Returns: (forge_instance, owner, repo) or (None, None, None) if not recognized.
    """
    if not source_url or not isinstance(source_url, str):
        return None, None, None
    
    source_url = source_url.strip()
    
    # Try GitHub
    forge = GitHubForge()
    if forge.detect_from_url(source_url):
        match = forge.REPO_PATTERN.search(source_url)
        if match:
            return forge, match.group(1), match.group(2)
    
    # Try Codeberg
    forge = CodebergForge()
    if forge.detect_from_url(source_url):
        match = forge.REPO_PATTERN.search(source_url)
        if match:
            return forge, match.group(1), match.group(2)
    
    # Try GitLab
    forge = GitLabForge()
    if forge.detect_from_url(source_url):
        match = forge.REPO_PATTERN.search(source_url)
        if match:
            base_url = match.group(1)
            path = match.group(2).rstrip('.git')
            parts = path.split('/')
            if len(parts) >= 2:
                owner = parts[0]
                repo = parts[-1]
                # Create instance with custom base URL
                forge_instance = GitLabForge()
                return forge_instance, owner, repo
    
    _log.debug('No recognized git forge found in URL: %s', source_url)
    return None, None, None


def extract_owner_repo_from_url(source_url: str) -> tuple:
    """Extract owner and repo from a git URL (supports multiple forges).
    
    Returns: (owner, repo) or (None, None) if not recognized.
    """
    # Remove .git suffix if present
    url = source_url.rstrip('.git') if isinstance(source_url, str) else ''
    
    # Try various patterns
    patterns = [
        r'[:/]([^/:]+)/([^/.]+?)(?:\.git)?$',  # git@github.com:owner/repo or https://...owner/repo
        r'/([^/:]+)/([^/.]+?)(?:\.git)?/?$',   # /owner/repo format
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2)
    
    return None, None
