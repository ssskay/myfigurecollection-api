"""HTTP transport for MFC.

MyFigureCollection sits behind Cloudflare, which blocks on TLS fingerprint, not
on user-agent. Plain ``requests``/``httpx``/``aiohttp`` get a 403 challenge page
no matter what headers they send — this is why the old `tenji` scraper stopped
working. ``curl_cffi`` with ``impersonate="chrome"`` reproduces a real Chrome
TLS handshake and gets a 200. That choice is load-bearing; do not swap it for a
normal HTTP client.
"""

from __future__ import annotations

import logging
import threading
import time

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from .cache import DiskCache
from .exceptions import (
    MFCBlockedError,
    MFCNotFoundError,
    MFCRateLimitedError,
    MFCTransportError,
)

log = logging.getLogger(__name__)

DEFAULT_IMPERSONATE = "chrome"
DEFAULT_RATE_LIMIT = 1.0  # seconds between requests
DEFAULT_TIMEOUT = 30.0

# Cloudflare's interstitial, in the languages MFC serves it.
_CHALLENGE_MARKERS = (
    "Just a moment...",
    "cf-browser-verification",
    "Checking your browser before accessing",
    "Enable JavaScript and cookies to continue",
)


class RateLimiter:
    """Blocks so that consecutive calls are at least `interval` seconds apart."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                log.debug("rate limiting: sleeping %.2fs", delay)
                time.sleep(delay)
            self._last = time.monotonic()


class Transport:
    """Fetches MFC pages politely: rate-limited, cached, Cloudflare-aware."""

    def __init__(
        self,
        *,
        impersonate: str = DEFAULT_IMPERSONATE,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        timeout: float = DEFAULT_TIMEOUT,
        cache: DiskCache | None = None,
        cache_ttl: float = 3600.0,
        max_retries: int = 2,
    ) -> None:
        self.impersonate = impersonate
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = RateLimiter(rate_limit)
        self.cache = cache if cache is not None else DiskCache(ttl=cache_ttl)
        self._session = requests.Session(impersonate=impersonate)

    def get(self, url: str, *, use_cache: bool = True) -> str:
        """Return the HTML at `url`, from cache when it is fresh enough."""
        if use_cache:
            cached = self.cache.get(url)
            if cached is not None:
                return cached

        html = self._fetch(url)

        if use_cache:
            self.cache.set(url, html)
        return html

    def post(self, url: str, data: dict[str, str], *, use_cache: bool = True) -> str:
        """POST a form and return the body.

        MFC's in-page windows (the Buy panel, for one) are form POSTs that reply
        with JSON rather than HTML. Same rate limiter and same cache as
        :meth:`get` — the cache key just folds in the form fields.
        """
        key = self._cache_key(url, data)
        if use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        body = self._fetch(url, data=data)

        if use_cache:
            self.cache.set(key, body)
        return body

    @staticmethod
    def _cache_key(url: str, data: dict[str, str] | None) -> str:
        if not data:
            return url
        fields = "&".join(f"{k}={v}" for k, v in sorted(data.items()))
        return f"POST {url} {fields}"

    def get_bytes(self, url: str) -> bytes:
        """Fetch a binary asset (an item picture) from MFC's static host.

        Same session, same process-wide rate limiter and the same Cloudflare /
        429 handling as pages, so a crawl that mixes pages and pictures still
        never exceeds one request per `rate_limit` seconds. Not cached: the
        caller is expected to write the bytes to disk and not ask again.
        """
        return self._fetch(url, binary=True)

    def _fetch(self, url: str, *, data: dict[str, str] | None = None, binary: bool = False):
        last_error: Exception | None = None
        method = "POST" if data is not None else "GET"

        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            log.debug("%s %s (attempt %d)", method, url, attempt + 1)
            try:
                if data is not None:
                    response = self._session.post(url, data=data, timeout=self.timeout)
                else:
                    response = self._session.get(url, timeout=self.timeout)
            except RequestException as exc:
                last_error = MFCTransportError(f"request to {url} failed: {exc}")
                continue

            headers = getattr(response, "headers", None) or {}
            is_html = "html" in (headers.get("content-type") or "").lower()
            body = response.text if (not binary or is_html) else ""

            if response.status_code == 429:
                raw = headers.get("retry-after")
                try:
                    retry_after = float(raw) if raw is not None else None
                except ValueError:
                    retry_after = None
                raise MFCRateLimitedError(
                    f"{url} returned HTTP 429 (Retry-After: {raw})", retry_after=retry_after
                )

            if response.status_code == 404:
                # MFC also serves a styled 404 body; the parser catches that case.
                raise MFCNotFoundError(f"MFC has no such object: {url}")

            if response.status_code in (403, 503) and self._is_challenge(body):
                raise MFCBlockedError(
                    f"Cloudflare challenged the request to {url}. The TLS "
                    f"impersonation profile ({self.impersonate!r}) may be stale, "
                    "or this IP is being rate-limited — slow down and retry later."
                )

            if response.status_code >= 500:
                last_error = MFCTransportError(f"{url} returned HTTP {response.status_code}")
                continue

            if response.status_code != 200:
                raise MFCTransportError(f"{url} returned HTTP {response.status_code}")

            if self._is_challenge(body):
                raise MFCBlockedError(f"Cloudflare challenge page served for {url}")

            if binary:
                if is_html:
                    raise MFCTransportError(f"{url} answered with HTML, not a binary asset")
                return response.content
            return body

        raise last_error or MFCTransportError(f"could not fetch {url}")

    @staticmethod
    def _is_challenge(body: str) -> bool:
        head = body[:4096]
        return any(marker in head for marker in _CHALLENGE_MARKERS)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
