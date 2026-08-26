# cache_policy.py - bounded, versioned cache lifecycle
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import tempfile
from pathlib import Path


class CacheManager:
    """Own Tavern cache writes, accounting, eviction, and safe clearing."""

    SCHEMA_VERSION = 1

    def __init__(self, root, max_bytes=256 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.max_bytes = int(max_bytes)
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_version_marker()

    def _write_version_marker(self):
        marker = self.root / 'CACHE_VERSION'
        if marker.exists() and marker.read_text(encoding='utf-8').strip() == str(self.SCHEMA_VERSION):
            return
        self.clear()
        marker.write_text(f'{self.SCHEMA_VERSION}\n', encoding='utf-8')

    def _safe_path(self, path):
        candidate = Path(path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError('cache path escapes Tavern cache directory')
        return candidate

    def atomic_write_json(self, path, data):
        target = self._safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=target.parent, delete=False
        ) as handle:
            json.dump(data, handle, separators=(',', ':'))
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
        self.enforce_quota(protected={target, self.root / 'CACHE_VERSION'})

    def atomic_write_bytes(self, path, data):
        target = self._safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, delete=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
        self.enforce_quota(protected={target, self.root / 'CACHE_VERSION'})

    def files(self):
        return [path for path in self.root.rglob('*') if path.is_file()]

    def size_bytes(self):
        total = 0
        for path in self.files():
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def enforce_quota(self, protected=None):
        protected = {self._safe_path(path) for path in (protected or set())}
        files = []
        total = 0
        for path in self.files():
            try:
                stat = path.stat()
            except OSError:
                continue
            total += stat.st_size
            if path.resolve() not in protected:
                files.append((stat.st_atime, stat.st_mtime, stat.st_size, path))
        for _atime, _mtime, size, path in sorted(files):
            if total <= self.max_bytes:
                break
            try:
                path.unlink()
                total -= size
            except OSError:
                continue
        return total

    def clear(self):
        if not self.root.exists():
            return
        for path in sorted(self.root.rglob('*'), reverse=True):
            safe = self._safe_path(path)
            try:
                if safe.is_file() or safe.is_symlink():
                    safe.unlink()
                elif safe.is_dir():
                    safe.rmdir()
            except OSError:
                continue

