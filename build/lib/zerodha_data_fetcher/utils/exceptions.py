"""Custom exceptions for Zerodha Data Fetcher."""


class ZerodhaAPIError(Exception):
    """Base exception for Zerodha API related errors."""
    pass


class AuthenticationError(ZerodhaAPIError):
    """Raised when authentication fails."""
    pass


class InvalidTickerError(ZerodhaAPIError):
    """Raised when an invalid ticker token is provided."""
    pass


class RateLimitError(ZerodhaAPIError):
    """Raised when API rate limit is exceeded."""
    pass


class DataFetchError(ZerodhaAPIError):
    """Raised when data fetching fails."""
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when the authentication token has expired."""
    pass
