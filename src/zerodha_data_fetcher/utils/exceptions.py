"""
Custom exceptions for Zerodha Data Fetcher.

Exception hierarchy::

    ZerodhaAPIError (base for all API errors)
    +-- AuthenticationError (login/token failures)
    |   +-- TokenExpiredError (cached token no longer valid)
    +-- InvalidTickerError (symbol/token not found or invalid)
    +-- RateLimitError (API throttling)
    +-- DataFetchError (HTTP/network/parsing failures during data retrieval)

All exceptions in this module inherit from :class:`ZerodhaAPIError`,
so callers can catch the base class to handle any library error or
catch a specific subclass for fine-grained control.
"""


class ZerodhaAPIError(Exception):
    """Base exception for all Zerodha API related errors.

    Catch this to handle any error raised by the library.  Prefer
    catching a more specific subclass when you need to distinguish
    between authentication, ticker, rate-limit, or data-fetch failures.
    """
    pass


class AuthenticationError(ZerodhaAPIError):
    """Raised when authentication with the Zerodha API fails.

    Common causes: invalid credentials, failed TOTP generation, or an
    HTTP error during the login / 2FA handshake.
    """
    pass


class InvalidTickerError(ZerodhaAPIError):
    """Raised when a ticker token or trading symbol cannot be resolved.

    This can happen when an integer token does not map to any instrument
    or a symbol string is not found in the instrument data.
    """
    pass


class RateLimitError(ZerodhaAPIError):
    """Raised when the Zerodha API reports that the rate limit has been exceeded.

    The library already applies client-side rate limiting via
    :class:`~zerodha_data_fetcher.core.rate_limiter.RequestRateLimiter`,
    but the server may still reject requests under heavy load.
    """
    pass


class DataFetchError(ZerodhaAPIError):
    """Raised when fetching historical data fails.

    Wraps HTTP errors, connection timeouts, unexpected response
    structures, and JSON parsing failures encountered while retrieving
    OHLCV candle data from the Kite API.
    """
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when a previously cached authentication token has expired.

    Extends :class:`AuthenticationError` because expiry is a specific
    authentication failure.  The library handles this automatically by
    generating a fresh token, so callers rarely need to catch it
    directly.
    """
    pass
