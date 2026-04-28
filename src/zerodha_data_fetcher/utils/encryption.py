"""Token encryption utilities for Zerodha Data Fetcher."""

import os
import logging
import keyring
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class TokenEncryption:
    """Handles encryption and decryption of authentication tokens.

    Uses `Fernet symmetric encryption <https://cryptography.io/en/latest/fernet/>`_
    (AES-128-CBC + HMAC-SHA256) for token encryption.  The encryption
    key is itself stored in the OS keyring so that it persists across
    sessions without being written to disk in plaintext.
    """

    # Default service name used in the system keyring to store/retrieve
    # the Fernet encryption key.
    DEFAULT_KEYRING_SERVICE_NAME = "ZerodhaEncryptionKey"

    def __init__(self, encryption_key: str = ""):
        """
        Initialize token encryption.

        The keyring service name is resolved in this order:
          1. *encryption_key* parameter (if non-empty).
          2. ``ZERODHA_KEYRING_ENCRYPTION_KEY`` environment variable.
          3. :attr:`DEFAULT_KEYRING_SERVICE_NAME` (``"ZerodhaEncryptionKey"``).

        Args:
            encryption_key: Keyring service name under which the Fernet
                key is stored.  Leave empty to use the env var or default.

        Raises:
            ValueError: If the resolved key is empty.
        """
        self.encryption_key = encryption_key or os.getenv(
            "ZERODHA_KEYRING_ENCRYPTION_KEY", self.DEFAULT_KEYRING_SERVICE_NAME
        )
        if not self.encryption_key:
            raise ValueError("Encryption key must be provided")

    def get_encryption_key(self) -> bytes:
        """
        Get the encryption key used for token encryption and decryption.

        If the encryption key is not found in the system keyring, a new key is generated and stored in the keyring.

        Returns:
            bytes: The encryption key as bytes.
        """
        logger.debug("Retrieving encryption key from keyring")
        encryption_key = keyring.get_password(self.encryption_key, "key")

        if encryption_key is None:
            logger.warning("Encryption key not found in keyring. Generating new key")
            encryption_key = Fernet.generate_key().decode()
            keyring.set_password(self.encryption_key, "key", encryption_key)
            logger.info("New encryption key generated and stored in keyring")
        else:
            logger.debug("Existing encryption key retrieved successfully")

        return encryption_key.encode()

    def encrypt_token(self, token: str) -> str:
        """
        Encrypt a token using Fernet encryption.

        Args:
            token (str): The token to be encrypted.

        Returns:
            str: The encrypted token.

        Raises:
            Exception: If there is an error during the encryption process.
        """
        logger.debug("Encrypting token for keyring storage")
        try:
            fernet = Fernet(self.get_encryption_key())
            encrypted_token = fernet.encrypt(token.encode()).decode()
            logger.debug("Token encrypted successfully")
            return encrypted_token
        except Exception as e:
            logger.error(f"Token encryption failed: {str(e)}")
            raise

    def decrypt_token(self, encrypted_token: str) -> str:
        """
        Decrypt an encrypted token using Fernet encryption.

        Args:
            encrypted_token (str): The encrypted token to be decrypted.

        Returns:
            str: The decrypted token.

        Raises:
            Exception: If there is an error during the decryption process.
        """
        logger.debug("Decrypting token from keyring storage")
        try:
            fernet = Fernet(self.get_encryption_key())
            decrypted_token = fernet.decrypt(encrypted_token.encode()).decode()
            logger.debug("Token decrypted successfully")
            return decrypted_token
        except Exception as e:
            logger.error(f"Token decryption failed: {str(e)}")
            raise
