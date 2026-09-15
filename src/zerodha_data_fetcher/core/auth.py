"""Authentication management for Zerodha API."""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Dict, Optional, Tuple

from ..utils import secret_store
from ..utils.config import Config
from ..utils.exceptions import AuthenticationError
from ..utils.encryption import TokenEncryption
from .token_generator import ZerodhaTokenGenerator

logger = logging.getLogger(__name__)


class AuthenticationManager:
    """Manages authentication tokens for the Zerodha API.

    Token lifecycle:
      1. **Generate** — perform the full login + 2FA flow via
         :class:`ZerodhaTokenGenerator` to obtain an ``enctoken``.
      2. **Encrypt** — encrypt the token with Fernet via
         :class:`~zerodha_data_fetcher.utils.encryption.TokenEncryption`.
      3. **Cache** — store the encrypted token, today's date, and a
         timestamp in the OS keyring (scoped per Zerodha user ID).
      4. **Reuse** — on subsequent calls within the same day and expiry
         window, decrypt and return the cached token without hitting
         the login endpoint again.
      5. **Invalidate** — delete cached entries when the token expires
         or the caller explicitly invalidates it.

    Multi-account support: each user ID gets its own keyring entries,
    so switching between Zerodha accounts does not overwrite tokens.

    Multi-threaded reuse: a decrypted token is also held in a
    process-global in-memory cache keyed by user ID and guarded by
    :attr:`_CACHE_LOCK`.  On the hot path (token still fresh) callers
    return straight from memory without touching the keyring.  When the
    token has expired, double-checked locking ensures that exactly **one**
    thread runs the expensive login + 2FA flow while every other concurrent
    caller waits and then reuses the freshly generated token — instead of
    each thread independently re-authenticating.
    """

    # Process-global cache shared by every instance for the same account:
    # user_id -> (decrypted_token, token_date "YYYY-MM-DD", token_timestamp).
    _MEMORY_CACHE: Dict[str, Tuple[str, str, str]] = {}
    # Serialises token refresh so concurrent callers don't stampede the
    # login endpoint when a token expires.
    _CACHE_LOCK = threading.Lock()

    def __init__(
        self,
        token_expiry_hours: float = Config.DEFAULT_TOKEN_EXPIRY_HOURS,
        config: Optional["Config"] = None,
    ):
        self.token_expiry_hours = token_expiry_hours
        self.config = config or Config()
        self.token_key = self.config.ZERODHA_KEYRING_TOKEN_KEY
        self.token_generator = ZerodhaTokenGenerator(config=self.config)
        self.token_encryption = TokenEncryption(
            self.config.ZERODHA_KEYRING_ENCRYPTION_KEY
        )

    @property
    def _current_user_id(self) -> str:
        """Return the configured user ID for scoping cached credentials."""
        return self.config.get_user_id()

    def _scoped_account_name(self, field: str) -> str:
        """Return the user-scoped account name used in keyring storage."""
        return f"{field}:{self._current_user_id}"

    def _read_token_bundle(
        self, token_account: str, date_account: str, timestamp_account: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Read token metadata from keyring."""
        return (
            secret_store.get_password(self.token_key, token_account),
            secret_store.get_password(self.token_key, date_account),
            secret_store.get_password(self.token_key, timestamp_account),
        )

    def _write_token_bundle(
        self, encrypted_token: str, token_date: str, token_timestamp: str
    ) -> None:
        """Persist a user-scoped token bundle in keyring."""
        secret_store.set_password(
            self.token_key, self._scoped_account_name("token"), encrypted_token
        )
        secret_store.set_password(
            self.token_key, self._scoped_account_name("date"), token_date
        )
        secret_store.set_password(
            self.token_key, self._scoped_account_name("timestamp"), token_timestamp
        )

    def _delete_password_best_effort(self, account_name: str) -> None:
        """Delete a keyring entry while tolerating missing backends/values."""
        try:
            secret_store.delete_password(self.token_key, account_name)
        except Exception:  # store may raise varied exceptions on missing entries
            logger.debug("Keyring entry %s did not need deletion", account_name)

    # ------------------------------------------------------------------
    # Legacy migration
    #
    # v0.x stored tokens in the keyring without user-scoping: a single
    # "token" / "date" / "timestamp" / "userid" set was shared across
    # all accounts.  When multiple Zerodha accounts are used on the
    # same machine, this layout silently overwrites tokens.
    #
    # The migration below detects the old layout, rewrites it into the
    # new per-user format (``<field>:<user_id>``), and deletes the
    # legacy entries so they don't cause confusion.
    # ------------------------------------------------------------------

    def _migrate_legacy_token_if_applicable(
        self,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Read the legacy shared token layout when it belongs to the current user.

        On success, rewrites the data into the new per-user layout and
        removes the old unscoped entries.
        """
        legacy_user_id = secret_store.get_password(self.token_key, "userid")
        if legacy_user_id != self._current_user_id:
            return None, None, None

        encrypted_token, token_date, token_timestamp = self._read_token_bundle(
            "token", "date", "timestamp"
        )
        if not (encrypted_token and token_date and token_timestamp):
            return None, None, None

        self._write_token_bundle(encrypted_token, token_date, token_timestamp)
        logger.info("Migrated legacy cached token into user-scoped storage")
        self._delete_password_best_effort("token")
        self._delete_password_best_effort("date")
        self._delete_password_best_effort("timestamp")
        self._delete_password_best_effort("userid")
        return encrypted_token, token_date, token_timestamp

    # ------------------------------------------------------------------
    # In-memory (process-global) token cache
    # ------------------------------------------------------------------

    @classmethod
    def clear_memory_cache(cls) -> None:
        """Drop every in-memory cached token (all accounts)."""
        with cls._CACHE_LOCK:
            cls._MEMORY_CACHE.clear()

    def _read_memory_cache(self, user_id: str, expiry_seconds: float) -> Optional[str]:
        """Return a still-fresh in-memory token for *user_id*, else ``None``.

        Reads are lock-free: a single ``dict.get`` is atomic under the GIL,
        so the common "token still valid" path never contends on the lock.
        """
        entry = type(self)._MEMORY_CACHE.get(user_id)
        if not entry:
            return None
        token, token_date, token_timestamp = entry
        today = date.today().strftime("%Y-%m-%d")
        try:
            time_elapsed = time.time() - float(token_timestamp)
        except (TypeError, ValueError):
            return None
        if token_date == today and time_elapsed < expiry_seconds:
            return token
        return None

    def _store_memory_cache(
        self, user_id: str, token: str, token_date: str, token_timestamp: str
    ) -> None:
        """Publish a decrypted token into the process-global cache."""
        type(self)._MEMORY_CACHE[user_id] = (token, token_date, str(token_timestamp))

    def get_auth_token(self) -> str:
        """
        Retrieves an authentication token for accessing the Zerodha API.

        Returns:
            str: The authentication token.

        Raises:
            AuthenticationError: If token generation fails.
        """
        user_id = self._current_user_id
        expiry_seconds = self.token_expiry_hours * 3600

        # Fast path: reuse a still-fresh token straight from memory, so
        # concurrent worker threads never re-read the keyring or re-login.
        cached = self._read_memory_cache(user_id, expiry_seconds)
        if cached is not None:
            logger.debug("Using in-memory cached auth token for current user")
            return cached

        # Slow path: serialise refresh so only one thread logs in on expiry.
        with type(self)._CACHE_LOCK:
            # Another thread may have refreshed while we waited for the lock.
            cached = self._read_memory_cache(user_id, expiry_seconds)
            if cached is not None:
                logger.debug("Auth token refreshed by another thread; reusing it")
                return cached

            return self._load_or_generate_token(user_id, expiry_seconds)

    def _load_or_generate_token(self, user_id: str, expiry_seconds: float) -> str:
        """Resolve a token from the keyring, or generate a fresh one.

        Called with :attr:`_CACHE_LOCK` held.  Retrieval order:

        1. Look up the user-scoped token in the system keyring.
        2. If not found, attempt legacy (unscoped) token migration.
        3. If a cached token exists and is fresh (same day + within the
           expiry window), decrypt it, publish it to the in-memory cache,
           and return it.
        4. Otherwise, generate a new token via the full login flow.
        """
        try:
            today = date.today().strftime("%Y-%m-%d")
            current_time = time.time()

            logger.debug("Looking up auth token for user %s on %s", user_id, today)

            encrypted_token, token_date, token_timestamp = self._read_token_bundle(
                self._scoped_account_name("token"),
                self._scoped_account_name("date"),
                self._scoped_account_name("timestamp"),
            )

            if not (encrypted_token and token_date and token_timestamp):
                encrypted_token, token_date, token_timestamp = (
                    self._migrate_legacy_token_if_applicable()
                )

            if encrypted_token and token_date and token_timestamp:
                logger.debug("Found cached token metadata in keyring")
                time_elapsed = current_time - float(token_timestamp)
                logger.debug(
                    "Cached token age: %.2f seconds, expiry window: %.2f seconds",
                    time_elapsed,
                    expiry_seconds,
                )
                if token_date == today and time_elapsed < expiry_seconds:
                    logger.info("Using cached auth token for current user")
                    token = self.token_encryption.decrypt_token(encrypted_token)
                    self._store_memory_cache(
                        user_id, token, token_date, token_timestamp
                    )
                    return token
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
            today = date.today().strftime("%Y-%m-%d")
            current_time = time.time()

            self._write_token_bundle(encrypted_token, today, str(current_time))
            self._store_memory_cache(
                self._current_user_id, new_token, today, str(current_time)
            )

            logger.info("Token cached for current user")
            return new_token

        except Exception as e:
            logger.error(f"Failed to generate/save token: {str(e)}")
            raise AuthenticationError(f"Token generation failed: {str(e)}")

    def invalidate_token(self) -> None:
        """Invalidate the current stored token (in-memory and persisted).

        The whole invalidation runs under :attr:`_CACHE_LOCK` so a concurrent
        :meth:`get_auth_token` cannot slip in between the memory eviction and
        the keyring deletion, reload the still-persisted token, and republish
        it — which would defeat the invalidation.
        """
        try:
            with type(self)._CACHE_LOCK:
                type(self)._MEMORY_CACHE.pop(self._current_user_id, None)
                self._delete_password_best_effort(self._scoped_account_name("token"))
                self._delete_password_best_effort(self._scoped_account_name("date"))
                self._delete_password_best_effort(
                    self._scoped_account_name("timestamp")
                )
                self._delete_password_best_effort("token")
                self._delete_password_best_effort("date")
                self._delete_password_best_effort("timestamp")
                self._delete_password_best_effort("userid")
            logger.info("Token invalidated successfully for current user")
        except Exception as e:
            logger.warning(f"Failed to invalidate token: {str(e)}")
