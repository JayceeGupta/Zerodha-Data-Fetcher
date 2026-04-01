"""Authentication management for Zerodha API."""

import logging
import time
from datetime import date
from typing import Optional

import keyring

from ..utils.config import Config
from ..utils.exceptions import AuthenticationError
from ..utils.encryption import TokenEncryption
from .token_generator import ZerodhaTokenGenerator

logger = logging.getLogger(__name__)


class AuthenticationManager:
    """Manages authentication tokens for Zerodha API."""
    
    def __init__(self, token_expiry_hours: float = Config.DEFAULT_TOKEN_EXPIRY_HOURS, config: Optional['Config'] = None):
        self.token_expiry_hours = token_expiry_hours
        self.config = config or Config()
        self.token_key = self.config.ZERODHA_KEYRING_TOKEN_KEY
        self.token_generator = ZerodhaTokenGenerator(config=self.config)
        self.token_encryption = TokenEncryption(self.config.ZERODHA_KEYRING_ENCRYPTION_KEY)

    @property
    def _current_user_id(self) -> str:
        """Return the configured user ID for scoping cached credentials."""
        return self.config.get_user_id()

    def _scoped_account_name(self, field: str) -> str:
        """Return the user-scoped account name used in keyring storage."""
        return f"{field}:{self._current_user_id}"

    def _read_token_bundle(self, token_account: str, date_account: str, timestamp_account: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Read token metadata from keyring."""
        return (
            keyring.get_password(self.token_key, token_account),
            keyring.get_password(self.token_key, date_account),
            keyring.get_password(self.token_key, timestamp_account),
        )

    def _write_token_bundle(self, encrypted_token: str, token_date: str, token_timestamp: str) -> None:
        """Persist a user-scoped token bundle in keyring."""
        keyring.set_password(self.token_key, self._scoped_account_name("token"), encrypted_token)
        keyring.set_password(self.token_key, self._scoped_account_name("date"), token_date)
        keyring.set_password(self.token_key, self._scoped_account_name("timestamp"), token_timestamp)

    def _delete_password_best_effort(self, account_name: str) -> None:
        """Delete a keyring entry while tolerating missing backends/values."""
        try:
            keyring.delete_password(self.token_key, account_name)
        except Exception:
            logger.debug("Keyring entry %s did not need deletion", account_name)

    def _migrate_legacy_token_if_applicable(self) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Read the legacy shared token layout when it belongs to the current user.

        On success, rewrites the data into the new per-user layout.
        """
        legacy_user_id = keyring.get_password(self.token_key, "userid")
        if legacy_user_id != self._current_user_id:
            return None, None, None

        encrypted_token, token_date, token_timestamp = self._read_token_bundle("token", "date", "timestamp")
        if not (encrypted_token and token_date and token_timestamp):
            return None, None, None

        self._write_token_bundle(encrypted_token, token_date, token_timestamp)
        logger.info("Migrated legacy cached token into user-scoped storage")
        self._delete_password_best_effort("token")
        self._delete_password_best_effort("date")
        self._delete_password_best_effort("timestamp")
        self._delete_password_best_effort("userid")
        return encrypted_token, token_date, token_timestamp

    def get_auth_token(self) -> str:
        """
        Retrieves an authentication token for accessing the Zerodha API.
        
        Returns:
            str: The authentication token.
            
        Raises:
            AuthenticationError: If token generation fails.
        """
        try:
            expiry_seconds = self.token_expiry_hours * 3600
            today = date.today().strftime('%Y-%m-%d')
            current_time = time.time()
            
            logger.debug("Looking up auth token for user %s on %s", self._current_user_id, today)
            
            encrypted_token, token_date, token_timestamp = self._read_token_bundle(
                self._scoped_account_name("token"),
                self._scoped_account_name("date"),
                self._scoped_account_name("timestamp"),
            )

            if not (encrypted_token and token_date and token_timestamp):
                encrypted_token, token_date, token_timestamp = self._migrate_legacy_token_if_applicable()
            
            if encrypted_token and token_date and token_timestamp:
                logger.debug("Found cached token metadata in keyring")
                time_elapsed = current_time - float(token_timestamp)
                logger.debug("Cached token age: %.2f seconds, expiry window: %.2f seconds", time_elapsed, expiry_seconds)
                if token_date == today and time_elapsed < expiry_seconds:
                    logger.info("Using cached auth token for current user")
                    return self.token_encryption.decrypt_token(encrypted_token)
                else:
                    logger.debug("Cached token is expired or from a different day")
            else:
                logger.debug("No user-scoped token data found in keyring")
                
        except Exception as e:
            logger.error(f"Error retrieving token: {str(e)}")
            
        # Generate new token
        return self._generate_new_token()
    
    def _generate_new_token(self) -> str:
        """Generate and store a new authentication token."""
        logger.info("Generating new auth token")
        
        try:
            new_token = self.token_generator.generate_auth_token()
            encrypted_token = self.token_encryption.encrypt_token(new_token)
            if not new_token or not encrypted_token:
                raise AuthenticationError("Failed to generate or encrypt new token")
            # Store the new token
            today = date.today().strftime('%Y-%m-%d')
            current_time = time.time()
            
            self._write_token_bundle(encrypted_token, today, str(current_time))
            
            logger.info("Token cached for current user")
            return new_token
            
        except Exception as e:
            logger.error(f"Failed to generate/save token: {str(e)}")
            raise AuthenticationError(f"Token generation failed: {str(e)}")
    
    def invalidate_token(self) -> None:
        """Invalidate the current stored token."""
        try:
            self._delete_password_best_effort(self._scoped_account_name("token"))
            self._delete_password_best_effort(self._scoped_account_name("date"))
            self._delete_password_best_effort(self._scoped_account_name("timestamp"))
            self._delete_password_best_effort("token")
            self._delete_password_best_effort("date")
            self._delete_password_best_effort("timestamp")
            self._delete_password_best_effort("userid")
            logger.info("Token invalidated successfully for current user")
        except Exception as e:
            logger.warning(f"Failed to invalidate token: {str(e)}")
