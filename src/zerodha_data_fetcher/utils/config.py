"""Configuration management for Zerodha Data Fetcher."""

import logging
import os
from typing import Dict

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
_WARNED_INVALID_TTL_VALUES: set[str] = set()

class Config:
    """Configuration settings for Zerodha Data Fetcher."""
    
    # Rate limiting settings
    DEFAULT_REQUESTS_PER_SECOND = 2
    MIN_REQUESTS_PER_SECOND = 1
    MAX_REQUESTS_PER_SECOND = 10
    
    # Token settings
    DEFAULT_TOKEN_EXPIRY_HOURS = 3.0
    
    # Data fetching settings
    MAX_HISTORICAL_YEARS = 10
    DEFAULT_CHUNK_DAYS = 30
    MAX_WORKERS = 10
    REQUEST_TIMEOUT = 30

    # Instrument cache settings
    DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES = 1440  # 24 hours
    
    def __init__(self, **kwargs):
        """
        Initialize configuration with optional keyword arguments.
        
        Args:
            **kwargs: Configuration overrides
        """
        # Environment variable keys with defaults from env or kwargs
        self.ZERODHA_USER_ID = kwargs.get('user_id') or os.getenv("ZERODHA_USER_ID", "")
        self.ZERODHA_PASSWORD = kwargs.get('password') or os.getenv("ZERODHA_PASSWORD", "")
        self.ZERODHA_TYPE = kwargs.get('user_type') or os.getenv("ZERODHA_TYPE", "user_id")
        self.ZERODHA_TOTP_SECRET = kwargs.get('totp_secret') or os.getenv("ZERODHA_TOTP_SECRET", "")
        
        # URLs
        self.ZERODHA_BASE_URL = kwargs.get('base_url') or os.getenv("ZERODHA_BASE_URL", "https://kite.zerodha.com/")
        self.ZERODHA_LOGIN_URL = kwargs.get('login_url') or os.getenv("ZERODHA_LOGIN_URL", "https://kite.zerodha.com/api/login")
        self.ZERODHA_2FA_URL = kwargs.get('two_fa_url') or os.getenv("ZERODHA_2FA_URL", "https://kite.zerodha.com/api/twofa")
        self.ZERODHA_HISTORICAL_URL = kwargs.get('historical_url') or os.getenv("ZERODHA_HISTORICAL_URL", "https://kite.zerodha.com/oms/instruments/historical/{token}/{timeframe}?user_id={userid}&oi=1&from={current_date}&to={next_date}")
        
        # Keyring settings
        self.ZERODHA_KEYRING_TOKEN_KEY = kwargs.get('keyring_token_key') or os.getenv("ZERODHA_KEYRING_TOKEN_KEY", "ZerodhaAuthToken")
        self.ZERODHA_KEYRING_ENCRYPTION_KEY = kwargs.get('keyring_encryption_key') or os.getenv("ZERODHA_KEYRING_ENCRYPTION_KEY", "ZerodhaEncryptionKey")
    
    def get_user_id(self) -> str:
        """Get Zerodha user ID from configuration."""
        return self.ZERODHA_USER_ID or ""
    
    def get_historical_url(self) -> str:
        """Get historical data URL template."""
        return self.ZERODHA_HISTORICAL_URL or ""

    @classmethod
    def resolve_instrument_cache_ttl_minutes(cls, env_value: str | None = None) -> int:
        """
        Resolve the instrument cache TTL from configuration.

        Args:
            env_value: Optional explicit environment value to parse. When omitted,
                reads ``ZERODHA_INSTRUMENT_CACHE_TTL`` from the environment.

        Returns:
            int: Cache TTL in minutes.
        """
        raw_value = os.getenv("ZERODHA_INSTRUMENT_CACHE_TTL") if env_value is None else env_value
        if raw_value is None or str(raw_value).strip() == "":
            return cls.DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES

        try:
            return int(raw_value)
        except (TypeError, ValueError):
            normalized = str(raw_value)
            if normalized not in _WARNED_INVALID_TTL_VALUES:
                logger.warning(
                    "Invalid ZERODHA_INSTRUMENT_CACHE_TTL=%r; falling back to %d minutes",
                    raw_value,
                    cls.DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES,
                )
                _WARNED_INVALID_TTL_VALUES.add(normalized)
            return cls.DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES

    @property
    def instrument_cache_ttl_minutes(self) -> int:
        """
        Instrument cache TTL in minutes.

        Reads ``ZERODHA_INSTRUMENT_CACHE_TTL`` env var, falling back to
        :pyattr:`DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES` (1440 = 24 h).
        """
        return self.resolve_instrument_cache_ttl_minutes()

    def validate_config(self) -> bool:
        """
        Validate that all required configuration is present.
        
        Returns:
            bool: True if all required config is present, False otherwise
        """
        required_vars = [
            self.ZERODHA_USER_ID,
            self.ZERODHA_PASSWORD,
            self.ZERODHA_TYPE,
            self.ZERODHA_TOTP_SECRET,
            self.ZERODHA_BASE_URL,
            self.ZERODHA_LOGIN_URL,
            self.ZERODHA_2FA_URL,
            self.ZERODHA_HISTORICAL_URL,
            self.ZERODHA_KEYRING_TOKEN_KEY,
            self.ZERODHA_KEYRING_ENCRYPTION_KEY
        ]
        
        missing_vars = [var for var in required_vars if not var]
        
        if missing_vars:
            return False
        return True
    
    def get_missing_config(self) -> list:
        """
        Get list of missing configuration variables.
        
        Returns:
            list: List of missing environment variable names
        """
        config_mapping = {
            self.ZERODHA_USER_ID: "ZERODHA_USER_ID",
            self.ZERODHA_PASSWORD: "ZERODHA_PASSWORD",
            self.ZERODHA_TYPE: "ZERODHA_TYPE",
            self.ZERODHA_TOTP_SECRET: "ZERODHA_TOTP_SECRET",
            self.ZERODHA_BASE_URL: "ZERODHA_BASE_URL",
            self.ZERODHA_LOGIN_URL: "ZERODHA_LOGIN_URL",
            self.ZERODHA_2FA_URL: "ZERODHA_2FA_URL",
            self.ZERODHA_HISTORICAL_URL: "ZERODHA_HISTORICAL_URL",
            self.ZERODHA_KEYRING_TOKEN_KEY: "ZERODHA_KEYRING_TOKEN_KEY",
            self.ZERODHA_KEYRING_ENCRYPTION_KEY: "ZERODHA_KEYRING_ENCRYPTION_KEY"
        }
        return [var_name for var_value, var_name in config_mapping.items() if not var_value]

    def to_dict(self) -> Dict[str, str]:
        """
        Convert configuration to dictionary.
        
        Returns:
            Dict[str, str]: Configuration as dictionary
        """
        return {
            'user_id': self.ZERODHA_USER_ID,
            'password': self.ZERODHA_PASSWORD,
            'user_type': self.ZERODHA_TYPE,
            'totp_secret': self.ZERODHA_TOTP_SECRET,
            'base_url': self.ZERODHA_BASE_URL,
            'login_url': self.ZERODHA_LOGIN_URL,
            'two_fa_url': self.ZERODHA_2FA_URL,
            'historical_url': self.ZERODHA_HISTORICAL_URL,
            'keyring_token_key': self.ZERODHA_KEYRING_TOKEN_KEY,
            'keyring_encryption_key': self.ZERODHA_KEYRING_ENCRYPTION_KEY
        }


# # Create a default instance for backward compatibility
# _default_config = Config()

# # Backward compatibility - expose as class attributes
# Config.ZERODHA_USER_ID = _default_config.ZERODHA_USER_ID
# Config.ZERODHA_PASSWORD = _default_config.ZERODHA_PASSWORD
# Config.ZERODHA_TYPE = _default_config.ZERODHA_TYPE
# Config.ZERODHA_TOTP_SECRET = _default_config.ZERODHA_TOTP_SECRET
# Config.ZERODHA_BASE_URL = _default_config.ZERODHA_BASE_URL
# Config.ZERODHA_LOGIN_URL = _default_config.ZERODHA_LOGIN_URL
# Config.ZERODHA_2FA_URL = _default_config.ZERODHA_2FA_URL
# Config.ZERODHA_HISTORICAL_URL = _default_config.ZERODHA_HISTORICAL_URL
# Config.ZERODHA_KEYRING_TOKEN_KEY = _default_config.ZERODHA_KEYRING_TOKEN_KEY
# Config.ZERODHA_KEYRING_ENCRYPTION_KEY = _default_config.ZERODHA_KEYRING_ENCRYPTION_KEY

# # Backward compatibility static methods - DO NOT assign to Config class
# # These are only for direct class method calls like Config.validate_config()
# def get_user_id_static() -> str:
#     """Get Zerodha user ID from environment."""
#     return _default_config.get_user_id()

# def get_historical_url_static() -> str:
#     """Get historical data URL template."""
#     return _default_config.get_historical_url()

# def validate_config_static() -> bool:
#     """Validate that all required configuration is present."""
#     return _default_config.validate_config()

# def get_missing_config_static() -> list:
#     """Get list of missing configuration variables."""
#     return _default_config.get_missing_config()

# # Only assign static methods as class methods, not instance methods
# Config.get_user_id_static = staticmethod(get_user_id_static)
# Config.get_historical_url_static = staticmethod(get_historical_url_static)
# Config.validate_config_static = staticmethod(validate_config_static)
# Config.get_missing_config_static = staticmethod(get_missing_config_static)
