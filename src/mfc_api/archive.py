"""Wayback (Save Page Now) snapshots for MyFigureCollection item pages.

Why this lives in the client and not in a downstream app: every :class:`Item`
already carries the public page URL, so the archiver has everything it needs
right here. A consumer only *reads* the resulting ``web.archive.org`` URL and
stores it beside its own price row.

Three things this buys, from one hook:

1. A price-history time series, as a byproduct of ordinary reads — the snapshot
   cadence *is* the temporal resolution.
2. Provenance. A price row that cites an immutable, third-party-timestamped
   capture is auditable by someone who does not trust you.
3. Insurance. Sources vanish: Mandarake went dark mid-2026-09 and `tenji` died
   before it.

**Archiving is best-effort and never raises into a read.** Every failure comes
back as an :class:`~mfc_api.models.ArchiveResult` with ``status="failed"``
and a reason. A read must still succeed when the Internet Archive is down.

Politeness, which is the part that gets an IP banned if it is wrong
-------------------------------------------------------------------

* **Weekly cadence per URL.** A JSON ledger records when each URL was last
  captured; anything snapshotted inside :data:`DEFAULT_MIN_INTERVAL_DAYS` days
  is skipped without a request. Enough resolution for a price curve, gentle on
  both the Archive and MFC.
* **Serialized and rate-limited.** SPN2 calls go through the same
  :class:`~mfc_api.transport.RateLimiter` the site transport uses — the same
  class, a separate instance, so archiving never slows an MFC read down or
  speeds a capture up.
* **Per-run cap.** :data:`DEFAULT_MAX_PER_RUN` snapshots per :class:`Archiver`,
  so a bulk job cannot turn into a flood.
* **429/``Retry-After`` is honoured** rather than retried through.

Scope guard
-----------

:func:`is_public_item_url` is a whitelist, not a blacklist: only ``/item/<id>``
passes. That matters more on MFC than on a shop, because most of MFC is *people*
— ``/profile/<username>``, ``/users.v4.php?username=…``, a collection page, a
club member roster. Those are a named individual's data, and a permanent public
archive is the last place they belong. They are refused before a request is
made, and no flag opts one past the guard. A URL carrying any query string at
all is refused too: an item page never needs one, and MFC's query-driven pages
are exactly the personal ones.

Kill switch
-----------

``MERCH_ARCHIVE=0`` (also ``false``/``no``/``off``) disables every snapshot in
the process. Shared with the sibling merch clients on purpose: one variable
turns archiving off across a whole bulk run.

Credentials
-----------

SPN2 needs Internet Archive S3 keys (free, from
https://archive.org/account/s3.php). They are read from ``IA_ACCESS_KEY`` /
``IA_SECRET_KEY``, else the macOS Keychain services ``ia-s3-access`` /
``ia-s3-secret`` — the same places the ``internet-historian`` tool keeps them,
so a machine set up for one is set up for both. Missing keys are a
``status="failed"`` result naming the fix, never an exception.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import RequestException

from .cache import default_cache_dir
from .models import ArchiveResult
from .transport import RateLimiter

log = logging.getLogger(__name__)

SPN2_BASE = "https://web.archive.org"
WAYBACK_AVAILABILITY = "https://archive.org/wayback/available"

#: Seconds between SPN2 calls. Ten a minute is well inside the Archive's
#: tolerance and far below the authenticated concurrency cap of 12.
DEFAULT_RATE_LIMIT = 6.0

#: Snapshots per :class:`Archiver`. A cap, not a target.
DEFAULT_MAX_PER_RUN = 50

#: Weekly cadence, as the spec requires.
DEFAULT_MIN_INTERVAL_DAYS = 7

#: How long to wait for a submitted capture to finish before returning
#: ``status="pending"``. The capture keeps running on the Archive's side.
DEFAULT_TIMEOUT = 30.0

_POLL_INTERVAL = 3.0

#: Whether MFC's own edge refuses Save Page Now. It does not — verified live
#: 2026-09-03, `web.archive.org/web/20260902233622/…/item/287`. The knob exists
#: for symmetry with amiami-api, where the sibling constant is True because
#: AmiAmi's storefront WAF does block the Archive's crawler. Flip this only if
#: the live canary starts reporting a block, so a weekly pass stops spending
#: requests on a refusal.
SPN2_BLOCKED_BY_SITE = False

_BLOCKED_NOTE = (
    "MFC is marked as blocking Save Page Now, so this was not submitted. "
    "Pass force=True to re-test."
)

#: Only these hosts, and only their public item pages.
DEFAULT_ALLOWED_HOSTS = frozenset(
    {"myfigurecollection.net", "www.myfigurecollection.net"}
)

#: ``/item/287`` and nothing else. Deliberately anchored and numeric: MFC's
#: personal pages (``/profile/…``, ``/users.v4.php``, ``/list/…``, ``/club/…``)
#: must never reach a permanent public archive, and a pattern that merely
#: *excluded* those would be one new URL shape away from leaking.
_ITEM_PATH = re.compile(r"^/item/\d+/?$")

# The Archive's own failure taxonomy. Transient means "come back later" and
# says nothing about the target; candidate-dead means the target answered and
# the answer was bad. Kept distinct so a caller can tell "busy" from "gone".
TRANSIENT_ERRORS = frozenset({
    "error:user-session-limit",
    "error:too-many-daily-captures",
    "error:proxy-error",
    "error:soft-time-limit-exceeded",
    "error:capture-location-error",
    "error:browsing-timeout",
})
DEAD_ERRORS = frozenset({
    "error:invalid-url",
    "error:not-found",
    "error:invalid-host-resolution",
    "error:blocked-url",
    "error:forbidden",
})
#: The target's WAF refused the Archive's crawler. Its own category because it
#: is neither: the page is fine and the Archive is fine, but the site will not
#: serve that particular client. Retrying does not help, and it says nothing
#: about whether the page still exists — so treating it as `transient` would
#: retry forever and treating it as `dead` would libel a live page.
#:
#: Measured 2026-09-03: every AmiAmi storefront URL lands here
#: ("The target server blocks access to ... HTTP status=403"), while
#: myfigurecollection.net captures normally.
BLOCKED_ERRORS = frozenset({"error:no-request"})


# -- kill switch ---------------------------------------------------------


def archiving_enabled() -> bool:
    """False when ``MERCH_ARCHIVE`` is set to an off value."""
    raw = os.environ.get("MERCH_ARCHIVE")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


# -- scope guard ---------------------------------------------------------


def is_public_item_url(url: str, *, allowed_hosts: Iterable[str] | None = None) -> bool:
    """True only for a public MFC item page.

    Whitelist semantics. HTTPS, an allow-listed host, a ``/item/<id>`` path, and
    no query string. A profile, a collection page, a user list, a club member
    roster — anything naming a person — returns False, as does an item URL with
    anything appended to it.
    """
    hosts = frozenset(allowed_hosts) if allowed_hosts is not None else DEFAULT_ALLOWED_HOSTS
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or parts.hostname is None:
        return False
    if parts.hostname.lower() not in hosts:
        return False
    if parts.username or parts.password:
        return False
    if parts.query:
        # An item page never needs one, and MFC's query-driven pages
        # (users.v4.php, the search browser) are the personal ones.
        return False
    return bool(_ITEM_PATH.match(parts.path))


# -- ledger --------------------------------------------------------------


def default_ledger_path() -> Path:
    """``$MERCH_ARCHIVE_LEDGER``, else ``$MFC_ARCHIVE_LEDGER``, else the cache dir.

    The shared variable comes first so a cross-client bulk pass can point every
    sibling package at one file and get one honest weekly cadence per URL.
    """
    for var in ("MERCH_ARCHIVE_LEDGER", "MFC_ARCHIVE_LEDGER"):
        override = os.environ.get(var)
        if override:
            return Path(override).expanduser()
    return default_cache_dir() / "archive-ledger.json"


class ArchiveLedger:
    """When each URL was last captured, as JSON on disk.

    Small by construction — one entry per decision-grade item — so it is read
    and rewritten whole. A corrupt or unreadable file is treated as empty:
    losing the ledger costs at most one redundant capture, while refusing to
    run because of it would cost the whole pass.
    """

    def __init__(self, path: Path | str | None = None,
                 min_interval_days: int = DEFAULT_MIN_INTERVAL_DAYS) -> None:
        self.path = Path(path) if path else default_ledger_path()
        self.min_interval = timedelta(days=min_interval_days)
        self._entries: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._entries is None:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._entries = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._entries = {}
        return self._entries

    def get(self, url: str) -> dict | None:
        entry = self._load().get(url)
        return entry if isinstance(entry, dict) else None

    def last_archived_at(self, url: str) -> datetime | None:
        entry = self.get(url)
        if not entry:
            return None
        try:
            stamp = datetime.fromisoformat(str(entry.get("archived_at")))
        except (TypeError, ValueError):
            return None
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)

    def is_fresh(self, url: str, *, now: datetime | None = None) -> bool:
        """True when this URL was captured inside the cadence window."""
        last = self.last_archived_at(url)
        if last is None:
            return False
        return (now or datetime.now(timezone.utc)) - last < self.min_interval

    def record(self, url: str, result: ArchiveResult) -> None:
        entries = self._load()
        entries[url] = {
            "archived_at": (result.archived_at or datetime.now(timezone.utc).isoformat()),
            "wayback_url": result.wayback_url,
            "timestamp": result.timestamp,
            "status": result.status,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
            temp.replace(self.path)
        except OSError as exc:
            # A ledger we cannot persist degrades cadence, not correctness.
            log.warning("could not write archive ledger %s: %s", self.path, exc)


# -- credentials ---------------------------------------------------------


def _keychain(service: str) -> str | None:
    account = os.environ.get("IA_KEYCHAIN_ACCOUNT") or os.environ.get("USER") or ""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        # Not in the Keychain, or not macOS. Either way: fall through to env.
        return None
    return result.stdout.strip() or None


def read_credentials() -> tuple[str | None, str | None]:
    """``(access_key, secret_key)``, from the environment or the Keychain.

    Never raises, never logs the values.
    """
    access = os.environ.get("IA_ACCESS_KEY") or _keychain("ia-s3-access")
    secret = os.environ.get("IA_SECRET_KEY") or _keychain("ia-s3-secret")
    return (access or None), (secret or None)


_NO_CREDS = (
    "no Internet Archive S3 keys. Get free keys at "
    "https://archive.org/account/s3.php, then set IA_ACCESS_KEY / IA_SECRET_KEY, "
    "or store them in the macOS Keychain as ia-s3-access / ia-s3-secret."
)


# -- the archiver --------------------------------------------------------


def _wayback_url(timestamp: str | None, original: str) -> str | None:
    if not timestamp:
        return None
    return f"{SPN2_BASE}/web/{timestamp}/{original}"


class Archiver:
    """Captures MFC item pages into the Wayback Machine, politely.

    One instance per pass. The per-run cap and the rate limiter are instance
    state, so a long-lived shared archiver would leak both.
    """

    def __init__(
        self,
        *,
        ledger: ArchiveLedger | None = None,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        max_per_run: int = DEFAULT_MAX_PER_RUN,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval_days: int = DEFAULT_MIN_INTERVAL_DAYS,
        allowed_hosts: Iterable[str] | None = None,
        session=None,
        credentials: tuple[str | None, str | None] | None = None,
        site_blocks_spn2: bool | None = None,
    ) -> None:
        self.ledger = ledger if ledger is not None else ArchiveLedger(
            min_interval_days=min_interval_days
        )
        # The same RateLimiter class the site transport uses, on its own
        # instance: archiving must not borrow or block MFC's budget.
        self.limiter = RateLimiter(rate_limit)
        self.max_per_run = max_per_run
        self.timeout = timeout
        self.min_interval_days = min_interval_days
        self.allowed_hosts = (
            frozenset(allowed_hosts) if allowed_hosts is not None else DEFAULT_ALLOWED_HOSTS
        )
        # Injectable so the SPN2 mechanics stay under test whatever the site's
        # current stance is — the module constant is the production default,
        # not a fact the unit tests should have to work around.
        self.site_blocks_spn2 = (
            SPN2_BLOCKED_BY_SITE if site_blocks_spn2 is None else site_blocks_spn2
        )
        self._credentials = credentials
        self._session = session
        self._owns_session = session is None
        self.submitted = 0

    # -- internals ------------------------------------------------------

    @property
    def session(self):
        if self._session is None:
            self._session = curl_requests.Session()
        return self._session

    def _headers(self) -> dict[str, str] | None:
        access, secret = (
            self._credentials if self._credentials is not None else read_credentials()
        )
        if not access or not secret:
            return None
        return {"Accept": "application/json", "Authorization": f"LOW {access}:{secret}"}

    @staticmethod
    def _json(response) -> dict:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - any decode failure is the same to us
            return {}
        return body if isinstance(body, dict) else {}

    def _sleep_for_retry_after(self, response) -> None:
        """Honour ``Retry-After`` rather than hammering through a 429."""
        raw = (response.headers or {}).get("Retry-After")
        try:
            delay = float(raw)
        except (TypeError, ValueError):
            delay = self.limiter.interval
        time.sleep(min(max(delay, 0.0), 60.0))

    # -- public API -----------------------------------------------------

    def snapshot(self, url: str, *, timeout: float | None = None,
                 force: bool = False) -> ArchiveResult:
        """Capture `url`, or explain why it was not captured. Never raises."""
        timeout = self.timeout if timeout is None else timeout
        try:
            return self._snapshot(url, timeout=timeout, force=force)
        except Exception as exc:  # noqa: BLE001 - the whole point is not to escape
            log.warning("archiving %s failed: %s", url, exc)
            return ArchiveResult(
                status="failed", source_url=url,
                reason=f"{type(exc).__name__}: {exc}",
            )

    def _snapshot(self, url: str, *, timeout: float, force: bool) -> ArchiveResult:
        if not archiving_enabled():
            return ArchiveResult(status="skipped", source_url=url,
                                 reason="disabled by MERCH_ARCHIVE")

        if not is_public_item_url(url, allowed_hosts=self.allowed_hosts):
            log.debug("refusing to archive non-public URL %s", url)
            return ArchiveResult(
                status="skipped", source_url=url,
                reason="not an allow-listed public MFC item page",
            )

        if self.site_blocks_spn2 and not force:
            # Checked before the ledger: cheaper, and more definitive than a
            # cadence question we do not need to ask.
            return ArchiveResult(status="skipped", source_url=url,
                                 reason=_BLOCKED_NOTE, error_kind="blocked")

        if not force and self.ledger.is_fresh(url):
            known = self.ledger.get(url) or {}
            return ArchiveResult(
                status="skipped", source_url=url,
                wayback_url=known.get("wayback_url"),
                timestamp=known.get("timestamp"),
                archived_at=known.get("archived_at"),
                reason=f"captured within the last {self.min_interval_days} days",
            )

        if self.submitted >= self.max_per_run:
            return ArchiveResult(
                status="skipped", source_url=url,
                reason=f"per-run cap of {self.max_per_run} snapshots reached",
            )

        headers = self._headers()
        if headers is None:
            return ArchiveResult(status="failed", source_url=url, reason=_NO_CREDS)

        deadline = time.monotonic() + timeout
        self.submitted += 1
        outcome, payload = self._submit(url, headers)

        if outcome == "already":
            # Server-side dedup: a recent capture already exists. That is a
            # preservation success, not a failure — go and fetch its URL.
            result = self._existing(url, headers) or ArchiveResult(
                status="already", source_url=url, reason=payload,
                archived_at=datetime.now(timezone.utc).isoformat(),
            )
            self.ledger.record(url, result)
            return result

        if outcome == "error":
            return ArchiveResult(status="failed", source_url=url, reason=payload,
                                 error_kind=classify(payload))

        return self._await_job(url, payload, headers, deadline=deadline)

    def _submit(self, url: str, headers: dict[str, str]) -> tuple[str, str]:
        """``("submitted", job_id)`` | ``("already", msg)`` | ``("error", msg)``."""
        form = {
            "url": url,
            # Belt and braces with the local ledger: if the Archive already has
            # a capture inside our cadence window it declines to make another.
            "if_not_archived_within": f"{self.min_interval_days}d",
            "skip_first_archive": "1",
            "js_behavior_timeout": "0",
        }
        for attempt in (0, 1):
            self.limiter.wait()
            try:
                response = self.session.post(
                    f"{SPN2_BASE}/save/", data=form, headers=headers, timeout=self.timeout
                )
            except RequestException as exc:
                return "error", f"POST /save/ failed: {exc}"
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    self._sleep_for_retry_after(response)
                    continue
                return "error", f"error:proxy-error POST /save/ HTTP {response.status_code}"
            break

        body = self._json(response)
        job_id = body.get("job_id")
        if job_id:
            return "submitted", str(job_id)

        message = str(body.get("message") or "")
        lowered = message.lower()
        if "you can make new capture" in lowered or "same snapshot had been made" in lowered:
            return "already", message
        return "error", str(body.get("status_ext") or message or f"HTTP {response.status_code}")

    def _await_job(self, url: str, job_id: str, headers: dict[str, str],
                   *, deadline: float) -> ArchiveResult:
        last: dict = {}
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(_POLL_INTERVAL, remaining))
            try:
                response = self.session.get(
                    f"{SPN2_BASE}/save/status/{job_id}", headers=headers, timeout=self.timeout
                )
            except RequestException as exc:
                log.debug("polling %s failed: %s", job_id, exc)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                self._sleep_for_retry_after(response)
                continue
            last = self._json(response)
            status = last.get("status")
            if status == "success":
                timestamp = last.get("timestamp")
                result = ArchiveResult(
                    status="success",
                    source_url=url,
                    wayback_url=_wayback_url(timestamp, last.get("original_url") or url),
                    timestamp=timestamp,
                    archived_at=datetime.now(timezone.utc).isoformat(),
                    job_id=job_id,
                )
                self.ledger.record(url, result)
                return result
            if status == "error":
                # Both halves: status_ext is the machine code, message is the
                # sentence that names who refused and why. A row that only
                # carries "error:no-request" is unreadable six months later.
                code = str(last.get("status_ext") or "error")
                detail = str(last.get("message") or "").strip()
                reason = f"{code}: {detail}" if detail else code
                return ArchiveResult(status="failed", source_url=url, reason=reason,
                                     job_id=job_id, error_kind=classify(reason))

        # Out of time, not out of luck: the capture is still running on the
        # Archive's side. Reported as pending so a caller can look it up later
        # rather than treating a slow capture as a lost one.
        return ArchiveResult(
            status="pending", source_url=url, job_id=job_id,
            reason=f"still capturing after {self.timeout:.0f}s (status: "
                   f"{last.get('status', 'pending')})",
        )

    def _existing(self, url: str, headers: dict[str, str]) -> ArchiveResult | None:
        """The closest existing snapshot, via the availability API."""
        self.limiter.wait()
        try:
            response = self.session.get(
                WAYBACK_AVAILABILITY, params={"url": url},
                headers=headers, timeout=self.timeout,
            )
        except RequestException as exc:
            log.debug("availability lookup for %s failed: %s", url, exc)
            return None
        snap = ((self._json(response).get("archived_snapshots") or {}).get("closest") or {})
        if not snap.get("available") or not snap.get("url"):
            return None
        return ArchiveResult(
            status="already",
            source_url=url,
            wayback_url=snap["url"],
            timestamp=snap.get("timestamp"),
            archived_at=datetime.now(timezone.utc).isoformat(),
            reason="a capture inside the cadence window already exists",
        )

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "Archiver":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def classify(error_text: str | None) -> str:
    """``"transient"`` | ``"blocked"`` | ``"dead"`` | ``"unknown"``.

    Three different facts, and conflating any two of them produces a wrong
    decision downstream:

    ``transient``
        The Archive is busy. Says nothing about the page. Retry later.
    ``blocked``
        The site's WAF refused the Archive's crawler. The page is fine, the
        Archive is fine, and retrying will not help.
    ``dead``
        The page itself answered badly — gone, moved, or never there.
    """
    text = (error_text or "").lower()
    if any(code in text for code in TRANSIENT_ERRORS):
        return "transient"
    if any(code in text for code in BLOCKED_ERRORS):
        return "blocked"
    if any(code in text for code in DEAD_ERRORS):
        return "dead"
    return "unknown"


def snapshot(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> ArchiveResult:
    """Capture one URL with a throwaway :class:`Archiver`. Never raises.

    Convenience for a one-off. A pass over many items should build one
    :class:`Archiver` and reuse it, so the rate limiter and the per-run cap
    actually apply across the batch.
    """
    with Archiver(timeout=timeout) as archiver:
        return archiver.snapshot(url)
