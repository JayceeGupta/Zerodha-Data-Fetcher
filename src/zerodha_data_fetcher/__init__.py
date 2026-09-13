"""
Zerodha Data Fetcher - A Python package for fetching historical data from Zerodha API.

This package provides tools for:
- Fetching historical stock/commodity data from Zerodha
- Managing authentication and rate limiting
- Symbol search and instrument management
- Parallel data fetching with error handling
"""

__version__ = "1.2.0"
__author__ = "Jayam Gupta"
__email__ = "guptajayam47@gmail.com"
__description__ = (
    "A Python package for fetching historical data from Zerodha API for free"
)
__url__ = "https://github.com/JayceeGupta/Zerodha-Data-Fetcher"

# Import main classes and functions for easy access
try:
    # Core functionality
    from .core.data_fetcher import ZerodhaDataFetcher, fetchDataZerodha
    from .core.instrument_manager import ZerodhaInstrumentManager, fetchZerodhaID
    from .core.contract_selector import ResolvedContract
    from .core.auth import AuthenticationManager
    from .core.rate_limiter import RateLimitedThreadPoolExecutor

    # Utilities
    from .utils.config import Config
    from .utils.logging_config import setup_logging
    from .utils.exceptions import (
        ZerodhaAPIError,
        AuthenticationError,
        InvalidTickerError,
        DataFetchError,
        TokenExpiredError,
        StaleInstrumentDataError,
    )

    # Public API - what users can import
    __all__ = [
        # Main classes
        "ZerodhaDataFetcher",
        "ZerodhaInstrumentManager",
        "ResolvedContract",
        "AuthenticationManager",
        "Config",
        # Backward compatibility functions
        "fetchDataZerodha",
        "fetchZerodhaID",
        # Instrument cache helpers
        "refresh_instruments",
        # Utilities
        "setup_logging",
        "RateLimitedThreadPoolExecutor",
        # Exceptions
        "ZerodhaAPIError",
        "AuthenticationError",
        "InvalidTickerError",
        "DataFetchError",
        "TokenExpiredError",
        "StaleInstrumentDataError",
        # Package metadata
        "__version__",
        "__author__",
        "__email__",
        "__description__",
        "__url__",
    ]

    # Package is fully functional
    _IMPORT_ERROR = None

except ImportError as e:
    # Handle import errors gracefully during development or missing dependencies
    import warnings

    warnings.warn(
        f"Some imports failed: {e}. "
        f"Please ensure all dependencies are installed: pip install zerodha-data-fetcher"
    )

    _IMPORT_ERROR = e
    __all__ = [
        "__version__",
        "__author__",
        "__email__",
        "__description__",
        "__url__",
        "check_installation",
    ]


def refresh_instruments() -> bool:
    """
    Force-download the latest Zerodha instrument data, ignoring TTL.

    This is a package-level convenience wrapper around
    :pymeth:`ZerodhaInstrumentManager.refresh_instruments`.

    Returns:
        ``True`` if the download succeeded, ``False`` otherwise.
    """
    manager = ZerodhaInstrumentManager()
    return manager.refresh_instruments()


def check_installation():
    """
    Check if package is properly installed with all dependencies.

    Returns:
        bool: True if package is fully functional, False otherwise
    """
    if _IMPORT_ERROR:
        print(f"❌ Package installation incomplete: {_IMPORT_ERROR}")
        print("💡 Try: pip install zerodha-data-fetcher")
        print(
            "💡 Or install with all dependencies: pip install 'zerodha-data-fetcher[dev]'"
        )
        return False
    else:
        print("✅ Package is properly installed and ready to use!")
        print(f"📦 Version: {__version__}")
        print(f"🔗 Documentation: {__url__}")
        return True


def get_version():
    """Get package version."""
    return __version__


def get_info():
    """Get package information."""
    return {
        "name": "zerodha-data-fetcher",
        "version": __version__,
        "author": __author__,
        "email": __email__,
        "description": __description__,
        "url": __url__,
        "functional": _IMPORT_ERROR is None,
    }


# Quick usage example in docstring
__doc__ = """

Quick Start:
    >>> from zerodha_data_fetcher import ZerodhaDataFetcher, setup_logging
    >>> from datetime import date, timedelta
    >>> 
    >>> # Setup logging
    >>> setup_logging(log_level="INFO")
    >>> 
    >>> # Initialize fetcher
    >>> fetcher = ZerodhaDataFetcher(requests_per_second=2)
    >>> 
    >>> # Fetch data
    >>> end_date = date.today()
    >>> start_date = end_date - timedelta(days=7)
    >>> data = fetcher.fetch_historical_data("RELIANCE", start_date, end_date)
    >>> print(data.head())

For more examples, visit: https://github.com/JayceeGupta/Zerodha-Data-Fetcher
"""
