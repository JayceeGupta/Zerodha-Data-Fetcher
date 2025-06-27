# """Core functionality for Zerodha Data Fetcher."""

# from .data_fetcher import ZerodhaDataFetcher
# from .auth import AuthenticationManager
# from .token_generator import ZerodhaTokenGenerator, getEncAuthToken, get_TOTP
# from .instrument_manager import ZerodhaInstrumentManager, fetchZerodhaID
# from .rate_limiter import RateLimitedThreadPoolExecutor

# __all__ = [
#     "ZerodhaDataFetcher",
#     "AuthenticationManager", 
#     "ZerodhaTokenGenerator",
#     "ZerodhaInstrumentManager",
#     "RateLimitedThreadPoolExecutor",
#     "getEncAuthToken",  # Backward compatibility
#     "get_TOTP",         # Backward compatibility
#     "fetchZerodhaID"    # Backward compatibility
# ]


"""
Core modules for Zerodha Data Fetcher.

This module contains the main functionality:
- Data fetching and processing
- Authentication management  
- Rate limiting
- Instrument management
"""

from .data_fetcher import ZerodhaDataFetcher, fetchDataZerodha
from .instrument_manager import ZerodhaInstrumentManager, fetchZerodhaID
from .auth import AuthenticationManager
from .rate_limiter import RateLimitedThreadPoolExecutor

__all__ = [
    "ZerodhaDataFetcher",
    "fetchDataZerodha", 
    "ZerodhaInstrumentManager",
    "fetchZerodhaID",
    "AuthenticationManager",
    "RateLimitedThreadPoolExecutor",
]
