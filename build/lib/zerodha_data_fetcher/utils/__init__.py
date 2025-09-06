# """Utility modules for Zerodha Data Fetcher."""

# from .exceptions import (
#     ZerodhaAPIError,
#     AuthenticationError,
#     InvalidTickerError,
#     RateLimitError,
#     DataFetchError,
#     TokenExpiredError
# )
# from .config import Config
# from .encryption import TokenEncryption
# from .logging_config import setup_logging, get_logger
# from .helpers import execution_timer, retry_on_failure

# __all__ = [
#     "ZerodhaAPIError",
#     "AuthenticationError", 
#     "InvalidTickerError",
#     "RateLimitError",
#     "DataFetchError",
#     "TokenExpiredError",
#     "Config",
#     "TokenEncryption",
#     "setup_logging",
#     "get_logger",
#     "execution_timer",
#     "retry_on_failure"
# ]


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
    TokenExpiredError
)
from .helpers import execution_timer, retry_on_failure

# Try to import data loader if it exists
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
    __all__.extend([
        "load_instrument_data",
        "get_package_data_path"
    ])

