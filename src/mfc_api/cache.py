"""On-disk response cache with a TTL.

Keeps repeated agent calls off MFC entirely. Entries are plain files keyed by a
hash of the URL, so the cache is trivially inspectable and safe to delete.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)


def default_cache_dir() -> Path:
    """``$MFC_API_CACHE_DIR``, else the XDG cache dir, else ``~/.cache``."""
    override = os.environ.get("MFC_API_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "mfc-api"


class DiskCache:
    def __init__(self, directory: Path | str | None = None, ttl: float = 3600.0) -> None:
        self.directory = Path(directory) if directory else default_cache_dir()
        self.ttl = ttl

    @property
    def enabled(self) -> bool:
        return self.ttl > 0

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        # Shard by first two chars so a big cache stays navigable.
        return self.directory / digest[:2] / f"{digest}.html"

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return None
        if age > self.ttl:
            log.debug("cache expired (%.0fs old): %s", age, key)
            return None
        try:
            log.debug("cache hit: %s", key)
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def set(self, key: str, value: str) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so a crash can't leave a half-written entry.
            temp = path.with_suffix(".tmp")
            temp.write_text(value, encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            log.warning("could not write cache entry for %s: %s", key, exc)

    def clear(self) -> int:
        """Delete every cached page. Returns how many files were removed."""
        removed = 0
        if not self.directory.exists():
            return removed
        for path in self.directory.rglob("*.html"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed
