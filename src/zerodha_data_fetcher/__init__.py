"""Zerodha Data Fetcher - A Python package for fetching historical data from Zerodha API."""

__version__ = "1.0.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

# Import main classes and functions for easy access
try:
    from .core.data_fetcher import ZerodhaDataFetcher, fetchDataZerodha
    from .utils.logging_config import setup_logging
    from .utils.config import Config
    
    __all__ = [
        "ZerodhaDataFetcher",
        "fetchDataZerodha", 
        "setup_logging",
        "Config",
        "__version__"
    ]
except ImportError as e:
    # Handle import errors gracefully during development
    import warnings
    warnings.warn(f"Some imports failed: {e}")
    __all__ = ["__version__"]
