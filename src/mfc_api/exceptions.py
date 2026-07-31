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


class MFCParseError(MFCError):
    """The page loaded but did not look like the markup we know how to read.

    MFC changes its templates occasionally; when that happens this is the error
    you will see, and the parser needs updating against a fresh fixture.
    """
