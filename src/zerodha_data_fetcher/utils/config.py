"""Configuration management for Zerodha Data Fetcher."""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

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
    
    # Environment variable keys
    ZERODHA_USER_ID = os.getenv("ZERODHA_USER_ID", "")
    ZERODHA_PASSWORD = os.getenv("ZERODHA_PASSWORD", "")
    ZERODHA_TYPE = os.getenv("ZERODHA_TYPE", "")
    ZERODHA_TOTP_SECRET = os.getenv("ZERODHA_TOTP_SECRET", "")
    
    # URLs
    ZERODHA_BASE_URL = os.getenv("ZERODHA_BASE_URL", "")
    ZERODHA_LOGIN_URL = os.getenv("ZERODHA_LOGIN_URL", "")
    ZERODHA_2FA_URL = os.getenv("ZERODHA_2FA_URL", "")
    ZERODHA_HISTORICAL_URL = os.getenv("ZERODHA_HISTORICAL_URL", "")
    
    # Keyring settings
    ZERODHA_KEYRING_TOKEN_KEY = os.getenv("ZERODHA_KEYRING_TOKEN_KEY", "")
    ZERODHA_KEYRING_ENCRYPTION_KEY = os.getenv("ZERODHA_KEYRING_ENCRYPTION_KEY", "")
    
    @classmethod
    def get_user_id(cls) -> str:
        """Get Zerodha user ID from environment."""
        return cls.ZERODHA_USER_ID or ""
    
    @classmethod
    def get_historical_url(cls) -> str:
        """Get historical data URL template."""
        return cls.ZERODHA_HISTORICAL_URL or ""
    
    @classmethod
    def validate_config(cls) -> bool:
        """
        Validate that all required configuration is present.
        
        Returns:
            bool: True if all required config is present, False otherwise
        """
        required_vars = [
            cls.ZERODHA_USER_ID,
            cls.ZERODHA_PASSWORD,
            cls.ZERODHA_TYPE,
            cls.ZERODHA_TOTP_SECRET,
            cls.ZERODHA_BASE_URL,
            cls.ZERODHA_LOGIN_URL,
            cls.ZERODHA_2FA_URL,
            cls.ZERODHA_HISTORICAL_URL,
            cls.ZERODHA_KEYRING_TOKEN_KEY,
            cls.ZERODHA_KEYRING_ENCRYPTION_KEY
        ]
        
        missing_vars = [var for var in required_vars if not var]
        
        if missing_vars:
            return False
        return True
    
    @classmethod
    def get_missing_config(cls) -> list:
        """
        Get list of missing configuration variables.
        
        Returns:
            list: List of missing environment variable names
        """
        config_mapping = {
            cls.ZERODHA_USER_ID: "ZERODHA_USER_ID",
            cls.ZERODHA_PASSWORD: "ZERODHA_PASSWORD",
            cls.ZERODHA_TYPE: "ZERODHA_TYPE",
            cls.ZERODHA_TOTP_SECRET: "ZERODHA_TOTP_SECRET",
            cls.ZERODHA_BASE_URL: "ZERODHA_BASE_URL",
            cls.ZERODHA_LOGIN_URL: "ZERODHA_LOGIN_URL",
            cls.ZERODHA_2FA_URL: "ZERODHA_2FA_URL",
            cls.ZERODHA_HISTORICAL_URL: "ZERODHA_HISTORICAL_URL",
            cls.ZERODHA_KEYRING_TOKEN_KEY: "ZERODHA_KEYRING_TOKEN_KEY",
            cls.ZERODHA_KEYRING_ENCRYPTION_KEY: "ZERODHA_KEYRING_ENCRYPTION_KEY"
        }
        
        return [var_name for var_value, var_name in config_mapping.items() if not var_value]
