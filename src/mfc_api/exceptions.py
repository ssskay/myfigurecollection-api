"""Exceptions raised by the MFC client."""


class MFCError(Exception):
    """Base class for every error this package raises."""


class MFCNotFoundError(MFCError):
    """The requested object does not exist (MFC served its 404 page)."""


class MFCBlockedError(MFCError):
    """Cloudflare served a challenge instead of the page.

    Almost always means the TLS impersonation is no longer convincing, or this
    IP has been rate-limited. Slow down, or try a different ``impersonate``
    profile.
    """


class MFCTransportError(MFCError):
    """The request failed at the network level, or returned an unexpected status."""


class MFCRateLimitedError(MFCTransportError):
    """HTTP 429. `retry_after` is the server's Retry-After in seconds, if it sent one.

    Never retried inside the transport: the caller decides whether to wait that
    long or end the run.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MFCParseError(MFCError):
    """The page loaded but did not look like the markup we know how to read.

    MFC changes its templates occasionally; when that happens this is the error
    you will see, and the parser needs updating against a fresh fixture.
    """
