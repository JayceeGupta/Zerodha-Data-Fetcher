"""Configuration management for Zerodha Data Fetcher."""

from __future__ import annotations

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
        self.ZERODHA_USER_ID = kwargs.get("user_id") or os.getenv("ZERODHA_USER_ID", "")
        self.ZERODHA_PASSWORD = kwargs.get("password") or os.getenv(
            "ZERODHA_PASSWORD", ""
        )
        self.ZERODHA_TYPE = kwargs.get("user_type") or os.getenv(
            "ZERODHA_TYPE", "user_id"
        )
        self.ZERODHA_TOTP_SECRET = kwargs.get("totp_secret") or os.getenv(
            "ZERODHA_TOTP_SECRET", ""
        )

        # URLs
        self.ZERODHA_BASE_URL = kwargs.get("base_url") or os.getenv(
            "ZERODHA_BASE_URL", "https://kite.zerodha.com/"
        )
        self.ZERODHA_LOGIN_URL = kwargs.get("login_url") or os.getenv(
            "ZERODHA_LOGIN_URL", "https://kite.zerodha.com/api/login"
        )
        self.ZERODHA_2FA_URL = kwargs.get("two_fa_url") or os.getenv(
            "ZERODHA_2FA_URL", "https://kite.zerodha.com/api/twofa"
        )
        self.ZERODHA_HISTORICAL_URL = kwargs.get("historical_url") or os.getenv(
            "ZERODHA_HISTORICAL_URL",
            "https://kite.zerodha.com/oms/instruments/historical/{token}/{timeframe}?user_id={userid}&oi=1&from={current_date}&to={next_date}",
        )

        # Keyring settings
        self.ZERODHA_KEYRING_TOKEN_KEY = kwargs.get("keyring_token_key") or os.getenv(
            "ZERODHA_KEYRING_TOKEN_KEY", "ZerodhaAuthToken"
        )
        self.ZERODHA_KEYRING_ENCRYPTION_KEY = kwargs.get(
            "keyring_encryption_key"
        ) or os.getenv("ZERODHA_KEYRING_ENCRYPTION_KEY", "ZerodhaEncryptionKey")

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
        raw_value = (
            os.getenv("ZERODHA_INSTRUMENT_CACHE_TTL")
            if env_value is None
            else env_value
        )
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

    def _required_config(self) -> "list[tuple[str, str]]":
        """Return ``(value, env-var-name)`` for the mandatory credentials.

        Only the three user credentials are required.  The URLs, keyring
        keys, and user type all have sensible built-in defaults (see
        :meth:`__init__`), so they are optional — never treat them as
        required or authentication rejects otherwise-valid configs whose
        URLs happen to be blank.
        """
        return [
            (self.ZERODHA_USER_ID, "ZERODHA_USER_ID"),
            (self.ZERODHA_PASSWORD, "ZERODHA_PASSWORD"),
            (self.ZERODHA_TOTP_SECRET, "ZERODHA_TOTP_SECRET"),
        ]

    def validate_config(self) -> bool:
        """
        Validate that all required configuration is present.

        Only the three user credentials (user ID, password, TOTP secret) are
        required; URLs/keyring/type are optional and default internally.

        Returns:
            bool: True if all required config is present, False otherwise
        """
        return not self.get_missing_config()

    def get_missing_config(self) -> list:
        """
        Get list of missing **required** configuration variables.

        Returns:
            list: Names of any missing credential env vars, in a stable order.
        """
        return [name for value, name in self._required_config() if not value]

    def to_dict(self) -> Dict[str, str]:
        """
        Convert configuration to dictionary.

        Returns:
            Dict[str, str]: Configuration as dictionary
        """
        return {
            "user_id": self.ZERODHA_USER_ID,
            "password": self.ZERODHA_PASSWORD,
            "user_type": self.ZERODHA_TYPE,
            "totp_secret": self.ZERODHA_TOTP_SECRET,
            "base_url": self.ZERODHA_BASE_URL,
            "login_url": self.ZERODHA_LOGIN_URL,
            "two_fa_url": self.ZERODHA_2FA_URL,
            "historical_url": self.ZERODHA_HISTORICAL_URL,
            "keyring_token_key": self.ZERODHA_KEYRING_TOKEN_KEY,
            "keyring_encryption_key": self.ZERODHA_KEYRING_ENCRYPTION_KEY,
        }
