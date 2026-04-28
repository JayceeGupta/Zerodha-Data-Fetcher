"""
Utility modules for Zerodha Data Fetcher.

This module contains:
- Configuration management
- Logging setup
- Custom exceptions
- Helper functions
- Data loading utilities
"""

from .config import Config
from .logging_config import setup_logging
from .exceptions import (
    ZerodhaAPIError,
    AuthenticationError,
    InvalidTickerError,
    DataFetchError,
    TokenExpiredError,
)
from .helpers import execution_timer, retry_on_failure

# data_loader depends on platformdirs & requests which are core deps,
# but guard the import so the utils sub-package remains importable
# even if those optional dependencies are missing at import time.
try:
    from .data_loader import load_instrument_data, get_package_data_path

    _DATA_LOADER_AVAILABLE = True
except ImportError:
    _DATA_LOADER_AVAILABLE = False

__all__ = [
    "Config",
    "setup_logging",
    "ZerodhaAPIError",
    "AuthenticationError",
    "InvalidTickerError",
    "DataFetchError",
    "TokenExpiredError",
    "execution_timer",
    "retry_on_failure",
]

# Add data loader functions if available
if _DATA_LOADER_AVAILABLE:
    __all__.extend(["load_instrument_data", "get_package_data_path"])
