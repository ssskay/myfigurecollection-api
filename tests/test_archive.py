"""The Wayback snapshot hook — guards, cadence, and failure behaviour.

Nothing here touches the network: the archiver takes an injected session, and
every SPN2 response is a saved fixture. The live canary lives in `test_live.py`.

The three properties worth defending, in order of how much damage their absence
would do:

1. **Nothing about a person is ever archived.** MFC is mostly people —
   profiles, collections, lists, club rosters. The guard is a whitelist of
   `/item/<id>`, so a new personal URL shape cannot leak through the way it
   could past a blacklist.
2. A Wayback failure never breaks a read. Archiving is a byproduct; an item
   lookup must survive the Internet Archive being down.
3. The weekly ledger actually skips. Without it a nightly job would hammer both
   the Archive and MFC for no extra resolution.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mfc_api import archive as arch
from mfc_api.archive import Archiver, ArchiveLedger, classify, is_public_item_url
from mfc_api.models import ArchiveResult

ITEM_URL = "https://myfigurecollection.net/item/287"
CREDS = ("test-access", "test-secret")


class FakeResponse:
    def __init__(self, body: str = "{}", status_code: int = 200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return json.loads(self._body)


class FakeSession:
    """Replays a scripted sequence of SPN2 responses and records the calls."""

    def __init__(self, posts=(), gets=()):
        self.posts = list(posts)
        self.gets = list(gets)
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        return self.posts.pop(0) if self.posts else FakeResponse()

    def get(self, url, params=None, headers=None, timeout=None):
        self.get_calls.append({"url": url, "params": params, "headers": headers})
        return self.gets.pop(0) if self.gets else FakeResponse()

    def close(self):
        pass


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Strip the courtesy delays so the suite runs at test speed.

    The delays are real and load-bearing in production; sleeping through them
    here would only test `time.sleep`.
    """
    monkeypatch.setattr(arch, "_POLL_INTERVAL", 0)


@pytest.fixture
def ledger(tmp_path) -> ArchiveLedger:
    return ArchiveLedger(tmp_path / "archive-ledger.json")


def build(session, ledger, **kw) -> Archiver:
    return Archiver(session=session, ledger=ledger, credentials=CREDS,
                    rate_limit=0, **kw)


# -- the allow-list guard -------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://myfigurecollection.net/item/287",
    "https://myfigurecollection.net/item/287/",
    "https://www.myfigurecollection.net/item/2748700",
])
def test_public_item_pages_pass_the_guard(url):
    assert is_public_item_url(url)


@pytest.mark.parametrize("url, why", [
    # Every one of these names a person. This is the list that matters.
    ("https://myfigurecollection.net/profile/Climbatize", "a user profile"),
    ("https://myfigurecollection.net/users.v4.php?mode=view&username=Climbatize&tab=collection",
     "somebody's collection"),
    ("https://myfigurecollection.net/users.v4.php?mode=view&username=Tsunami3k&tab=lists",
     "somebody's lists"),
    ("https://myfigurecollection.net/list/2509/", "a user-built list"),
    ("https://myfigurecollection.net/club/349/members/", "a club member roster"),
    # And the ordinary refusals.
    ("http://myfigurecollection.net/item/287", "plain http"),
    ("https://myfigurecollection.net/item/287?tab=pictures", "a query string on an item"),
    ("https://myfigurecollection.net/item/", "no id"),
    ("https://myfigurecollection.net/item/287/extra", "something appended"),
    ("https://user:pw@myfigurecollection.net/item/287", "embedded credentials"),
    ("https://myfigurecollection.net.evil.example/item/287", "a lookalike host"),
    ("https://www.amiami.com/eng/detail/?gcode=FIGURE-205113", "a different site's item"),
    ("https://order.mandarake.co.jp/order/detailPage/item?itemCode=1", "Mandarake, which is held"),
    ("not a url at all", "not a URL"),
])
def test_everything_else_is_refused(url, why):
    assert not is_public_item_url(url), why


def test_a_personal_page_never_reaches_spn2(ledger):
    """The one failure mode with a victim: do not archive a named person."""
    session = FakeSession()
    result = build(session, ledger).snapshot(
        "https://myfigurecollection.net/profile/Climbatize"
    )
    assert result.status == "skipped"
    assert "allow-listed" in result.reason
    assert session.post_calls == [], "a user profile was sent to the Internet Archive"


# -- the site block -------------------------------------------------------
#
# MFC does not block Save Page Now (verified live 2026-09-03). The switch exists
# for symmetry with amiami-api, whose sibling constant is True because AmiAmi's
# storefront WAF does block the Archive's crawler.


def test_mfc_is_not_marked_as_blocking():
    """If this flips, MFC started refusing the Archive and the weekly pass has
    lost its only source of captures."""
    assert arch.SPN2_BLOCKED_BY_SITE is False
    assert Archiver(site_blocks_spn2=None).site_blocks_spn2 is False


def test_marking_a_site_blocked_stops_the_request(ledger):
    session = FakeSession()
    archiver = Archiver(session=session, ledger=ledger, credentials=CREDS,
                        rate_limit=0, site_blocks_spn2=True)
    result = archiver.snapshot(ITEM_URL)

    assert result.status == "skipped"
    assert result.error_kind == "blocked"
    assert session.post_calls == [], "spent a request on a known-blocked site"


def test_force_still_submits_to_a_blocked_site(ledger, spn2_submit_job_json,
                                               spn2_status_success_json):
    """How a canary re-tests a block, and how we would learn it lifted."""
    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_success_json)])
    archiver = Archiver(session=session, ledger=ledger, credentials=CREDS,
                        rate_limit=0, site_blocks_spn2=True)
    assert archiver.snapshot(ITEM_URL, force=True).status == "success"


# -- the kill switch ------------------------------------------------------


def test_merch_archive_off_stops_everything(ledger, monkeypatch):
    session = FakeSession()
    for value in ("0", "false", "no", "off"):
        monkeypatch.setenv("MERCH_ARCHIVE", value)
        result = build(session, ledger).snapshot(ITEM_URL)
        assert result.status == "skipped", value
        assert "MERCH_ARCHIVE" in result.reason
    assert session.post_calls == []


def test_the_kill_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv("MERCH_ARCHIVE", raising=False)
    assert arch.archiving_enabled()
    monkeypatch.setenv("MERCH_ARCHIVE", "1")
    assert arch.archiving_enabled()


# -- the weekly ledger ----------------------------------------------------


def test_a_fresh_capture_is_skipped_without_a_request(ledger):
    ledger.record(ITEM_URL, ArchiveResult(
        status="success", source_url=ITEM_URL,
        wayback_url="https://web.archive.org/web/20260901120301/" + ITEM_URL,
        timestamp="20260901120301",
        archived_at=datetime.now(timezone.utc).isoformat(),
    ))
    session = FakeSession()
    result = build(session, ledger).snapshot(ITEM_URL)

    assert result.status == "skipped"
    assert "7 days" in result.reason
    # The point of the skip: still citable, at no cost to anyone.
    assert result.wayback_url and result.ok
    assert session.post_calls == []


def test_a_capture_older_than_a_week_is_retried(ledger, spn2_submit_job_json,
                                                spn2_status_success_json):
    stale = datetime.now(timezone.utc) - timedelta(days=8)
    ledger.record(ITEM_URL, ArchiveResult(status="success", source_url=ITEM_URL,
                                          archived_at=stale.isoformat()))
    assert not ledger.is_fresh(ITEM_URL)

    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_success_json)])
    result = build(session, ledger).snapshot(ITEM_URL)
    assert result.status == "success"
    assert len(session.post_calls) == 1


def test_the_ledger_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "archive-ledger.json"
    path.write_text("{ this is not json", encoding="utf-8")
    corrupt = ArchiveLedger(path)
    # Empty, not an exception: losing the ledger costs one redundant capture,
    # refusing to run would cost the whole pass.
    assert corrupt.get(ITEM_URL) is None
    assert not corrupt.is_fresh(ITEM_URL)


def test_the_ledger_round_trips_to_disk(ledger, tmp_path):
    ledger.record(ITEM_URL, ArchiveResult(
        status="success", source_url=ITEM_URL, wayback_url="https://web.archive.org/web/1/x",
        timestamp="20260903081500", archived_at="2026-09-03T08:15:00+00:00",
    ))
    on_disk = json.loads((tmp_path / "archive-ledger.json").read_text())
    assert on_disk[ITEM_URL]["timestamp"] == "20260903081500"
    assert ArchiveLedger(tmp_path / "archive-ledger.json").is_fresh(
        ITEM_URL, now=datetime(2026, 9, 5, tzinfo=timezone.utc)
    )


def test_a_naive_timestamp_is_read_as_utc(ledger, tmp_path):
    (tmp_path / "archive-ledger.json").write_text(
        json.dumps({ITEM_URL: {"archived_at": "2026-09-03T08:15:00"}}), encoding="utf-8"
    )
    fresh = ArchiveLedger(tmp_path / "archive-ledger.json")
    assert fresh.is_fresh(ITEM_URL, now=datetime(2026, 9, 4, tzinfo=timezone.utc))


# -- the happy path -------------------------------------------------------


def test_a_successful_capture_returns_a_citable_url(ledger, spn2_submit_job_json,
                                                    spn2_status_success_json):
    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_success_json)])
    result = build(session, ledger).snapshot(ITEM_URL)

    assert result.status == "success"
    assert result.wayback_url == (
        "https://web.archive.org/web/20260903081500/" + ITEM_URL
    )
    assert result.timestamp == "20260903081500"
    assert result.ok
    # And it is now on the ledger, so the next pass this week skips it.
    assert ledger.is_fresh(ITEM_URL)


def test_the_submit_carries_auth_and_the_cadence_window(ledger, spn2_submit_job_json,
                                                        spn2_status_success_json):
    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_success_json)])
    build(session, ledger).snapshot(ITEM_URL)

    call = session.post_calls[0]
    assert call["url"] == "https://web.archive.org/save/"
    assert call["data"]["url"] == ITEM_URL
    # Server-side dedup agreeing with the local ledger, so a lost ledger still
    # cannot produce a burst of redundant captures.
    assert call["data"]["if_not_archived_within"] == "7d"
    assert call["headers"]["Authorization"] == "LOW test-access:test-secret"


def test_polling_waits_through_pending(ledger, spn2_submit_job_json,
                                       spn2_status_pending_json, spn2_status_success_json):
    session = FakeSession(
        posts=[FakeResponse(spn2_submit_job_json)],
        gets=[FakeResponse(spn2_status_pending_json),
              FakeResponse(spn2_status_pending_json),
              FakeResponse(spn2_status_success_json)],
    )
    result = build(session, ledger).snapshot(ITEM_URL)
    assert result.status == "success"
    assert len(session.get_calls) == 3


# -- dedup ----------------------------------------------------------------


def test_server_side_dedup_is_a_success_not_a_failure(ledger, spn2_submit_dedup_json,
                                                      wayback_available_json):
    session = FakeSession(posts=[FakeResponse(spn2_submit_dedup_json)],
                          gets=[FakeResponse(wayback_available_json)])
    result = build(session, ledger).snapshot(ITEM_URL)

    assert result.status == "already"
    assert result.wayback_url.endswith("20260901120301/" + ITEM_URL)
    assert result.ok
    assert ledger.is_fresh(ITEM_URL), "a dedup answer should still satisfy the cadence"


def test_dedup_without_a_findable_snapshot_still_records(ledger, spn2_submit_dedup_json):
    session = FakeSession(posts=[FakeResponse(spn2_submit_dedup_json)],
                          gets=[FakeResponse('{"archived_snapshots": {}}')])
    result = build(session, ledger).snapshot(ITEM_URL)
    assert result.status == "already"
    assert result.wayback_url is None
    assert not result.ok, "no URL to cite means not ok, even on a dedup"


# -- failure is a row, never an exception ---------------------------------


def test_a_capture_error_returns_failed(ledger, spn2_submit_job_json,
                                        spn2_status_error_json):
    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_error_json)])
    result = build(session, ledger).snapshot(ITEM_URL)

    assert result.status == "failed"
    # Code and sentence both, so the row is still readable six months later.
    assert result.reason == "error:proxy-error: Cannot fetch the page, the proxy failed."
    assert result.error_kind == "transient", "the Archive being busy is not the page's fault"
    assert not ledger.is_fresh(ITEM_URL), "a failure must not satisfy the cadence"


def test_an_immediate_refusal_returns_failed(ledger, spn2_submit_error_json):
    session = FakeSession(posts=[FakeResponse(spn2_submit_error_json)])
    result = build(session, ledger).snapshot(ITEM_URL)
    assert result.status == "failed"
    assert result.error_kind == "dead"


def test_a_thrown_exception_never_escapes(ledger):
    class ExplodingSession(FakeSession):
        def post(self, *a, **kw):
            raise RuntimeError("the Internet Archive fell over")

    result = build(ExplodingSession(), ledger).snapshot(ITEM_URL)
    assert result.status == "failed"
    assert "fell over" in result.reason


def test_non_json_from_the_archive_is_a_failure_not_a_crash(ledger):
    session = FakeSession(posts=[FakeResponse("<html>502 Bad Gateway</html>")])
    result = build(session, ledger).snapshot(ITEM_URL)
    assert result.status == "failed"


def test_missing_credentials_say_how_to_fix_it(ledger, monkeypatch):
    monkeypatch.delenv("IA_ACCESS_KEY", raising=False)
    monkeypatch.delenv("IA_SECRET_KEY", raising=False)
    session = FakeSession()
    archiver = Archiver(session=session, ledger=ledger, credentials=(None, None), rate_limit=0)
    result = archiver.snapshot(ITEM_URL)
    assert result.status == "failed"
    assert "archive.org/account/s3.php" in result.reason
    assert session.post_calls == []


def test_a_429_is_backed_off_once_then_reported(ledger, monkeypatch):
    monkeypatch.setattr(arch.time, "sleep", lambda _s: None)
    session = FakeSession(posts=[
        FakeResponse("{}", status_code=429, headers={"Retry-After": "1"}),
        FakeResponse("{}", status_code=429, headers={"Retry-After": "1"}),
    ])
    result = build(session, ledger).snapshot(ITEM_URL)
    assert result.status == "failed"
    assert len(session.post_calls) == 2, "one retry, then give up rather than hammer"


# -- caps and pending -----------------------------------------------------


def test_the_per_run_cap_holds(ledger, spn2_submit_job_json, spn2_status_success_json):
    session = FakeSession(
        posts=[FakeResponse(spn2_submit_job_json)],
        gets=[FakeResponse(spn2_status_success_json)],
    )
    archiver = build(session, ledger, max_per_run=1)
    first = archiver.snapshot(ITEM_URL)
    second = archiver.snapshot("https://myfigurecollection.net/item/2748700")

    assert first.status == "success"
    assert second.status == "skipped"
    assert "per-run cap" in second.reason
    assert len(session.post_calls) == 1


def test_a_slow_capture_is_pending_not_failed(ledger, spn2_submit_job_json,
                                              spn2_status_pending_json):
    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_pending_json)] * 20)
    result = build(session, ledger, timeout=0.01).snapshot(ITEM_URL)

    assert result.status == "pending"
    assert result.job_id
    assert not ledger.is_fresh(ITEM_URL), "an unfinished capture is not a capture"


# -- error taxonomy -------------------------------------------------------


@pytest.mark.parametrize("text, kind", [
    ("error:user-session-limit", "transient"),
    ("error:too-many-daily-captures", "transient"),
    ("error:not-found", "dead"),
    ("error:blocked-url", "dead"),
    # The one measured live on 2026-09-03: AmiAmi's WAF refusing SPN2. Neither
    # busy nor gone, and calling it either produces a wrong decision — retry
    # forever, or mark a live page dead.
    ("error:no-request: The target server blocks access to https://www.amiami.com/"
     "eng/detail/?gcode=FIGURE-205113. (HTTP status=403)", "blocked"),
    ("something nobody has seen before", "unknown"),
    (None, "unknown"),
])
def test_classify_separates_busy_from_blocked_from_gone(text, kind):
    assert classify(text) == kind


# -- ledger location ------------------------------------------------------


def test_the_shared_env_var_wins_over_the_package_one(monkeypatch, tmp_path):
    """So one bulk pass across sibling clients keeps one honest cadence."""
    monkeypatch.setenv("MERCH_ARCHIVE_LEDGER", str(tmp_path / "shared.json"))
    monkeypatch.setenv("MFC_ARCHIVE_LEDGER", str(tmp_path / "mfc.json"))
    assert arch.default_ledger_path() == tmp_path / "shared.json"
    monkeypatch.delenv("MERCH_ARCHIVE_LEDGER")
    assert arch.default_ledger_path() == tmp_path / "mfc.json"


# -- client wiring --------------------------------------------------------
#
# The read path must be indifferent to whether archiving worked. These drive
# the whole client with a scripted transport, so they cover the one thing the
# unit tests above cannot: that `get_item()` still returns an item.


class ScriptedTransport:
    """The minimum Transport surface `get_item()` uses — HTML in, HTML out."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.gets: list[str] = []

    def get(self, url: str, **kw) -> str:
        self.gets.append(url)
        return self.html

    def close(self):
        pass


def test_get_item_does_not_archive_unless_asked(item_html, ledger):
    from mfc_api.client import MFCClient

    session = FakeSession()
    client = MFCClient(transport=ScriptedTransport(item_html),
                       archiver=build(session, ledger))
    item = client.get_item(287)

    assert item.archive is None
    assert session.post_calls == [], "a plain read must never call the Archive"


def test_get_item_with_archive_attaches_the_capture(item_html, ledger,
                                                    spn2_submit_job_json,
                                                    spn2_status_success_json):
    from mfc_api.client import MFCClient

    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_success_json)])
    client = MFCClient(transport=ScriptedTransport(item_html),
                       archiver=build(session, ledger))
    item = client.get_item(287, archive=True)

    assert item.name, "the item itself is unchanged"
    assert item.archive.status == "success"
    assert item.archive.wayback_url.startswith("https://web.archive.org/web/")
    assert session.post_calls[0]["data"]["url"] == item.url


def test_a_dead_archive_does_not_break_the_read(item_html, ledger):
    """The property the whole design hangs on."""
    from mfc_api.client import MFCClient

    class ExplodingSession(FakeSession):
        def post(self, *a, **kw):
            raise RuntimeError("Internet Archive unreachable")

    client = MFCClient(transport=ScriptedTransport(item_html),
                       archiver=build(ExplodingSession(), ledger))
    item = client.get_item(287, archive=True)

    assert item.id == 287
    assert item.releases, "the item's release/price data survived the Archive being down"
    assert item.archive.status == "failed"


def test_snapshot_item_builds_a_canonical_url(ledger, spn2_submit_job_json,
                                              spn2_status_success_json):
    """An item found by barcode carries the *search* URL it was found at, which
    the guard refuses (rightly — it is a query URL). Going via the id avoids
    handing callers a footgun."""
    from mfc_api.client import MFCClient

    session = FakeSession(posts=[FakeResponse(spn2_submit_job_json)],
                          gets=[FakeResponse(spn2_status_success_json)])
    client = MFCClient(transport=ScriptedTransport(""), archiver=build(session, ledger))
    result = client.snapshot_item(287)

    assert result.status == "success"
    assert session.post_calls[0]["data"]["url"] == "https://myfigurecollection.net/item/287"


def test_the_search_url_an_item_carries_would_have_been_refused(ledger):
    """The reason snapshot_item exists, stated as a test."""
    search_url = ("https://myfigurecollection.net/?_tb=item&mode=browse&tab=search"
                  "&barcode=4513750110050&output=0&page=1")
    assert not is_public_item_url(search_url)
    session = FakeSession()
    assert build(session, ledger).snapshot(search_url).status == "skipped"
    assert session.post_calls == []
