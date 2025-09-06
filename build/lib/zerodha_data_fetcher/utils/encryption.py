"""Token encryption utilities for Zerodha Data Fetcher."""

import os
import logging
import keyring
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

ENCRYPTION_KEY = os.getenv("ZERODHA_KEYRING_ENCRYPTION_KEY", "")

class TokenEncryption:
    """Handles encryption and decryption of authentication tokens."""
    
    @staticmethod
    def get_encryption_key() -> bytes:
        """
        Get the encryption key used for token encryption and decryption.

        If the encryption key is not found in the system keyring, a new key is generated and stored in the keyring.

        Returns:
            bytes: The encryption key as bytes.
        """
        logger.info("Attempting to retrieve encryption key from keyring")
        encryption_key = keyring.get_password(ENCRYPTION_KEY, "key")
        
        if encryption_key is None:
            logger.warning("Encryption key not found in keyring. Generating new key")
            encryption_key = Fernet.generate_key().decode()
            keyring.set_password(ENCRYPTION_KEY, "key", encryption_key)
            logger.info("New encryption key generated and stored in keyring")
        else:
            logger.debug("Existing encryption key retrieved successfully")
            
        return encryption_key.encode()

    @staticmethod
    def encrypt_token(token: str) -> str:
        """
        Encrypt a token using Fernet encryption.

        Args:
            token (str): The token to be encrypted.

        Returns:
            str: The encrypted token.

        Raises:
            Exception: If there is an error during the encryption process.
        """
        logger.info("Starting token encryption process")
        try:
            fernet = Fernet(TokenEncryption.get_encryption_key())
            encrypted_token = fernet.encrypt(token.encode()).decode()
            logger.debug("Token encrypted successfully")
            return encrypted_token
        except Exception as e:
            logger.error(f"Token encryption failed: {str(e)}")
            raise

    @staticmethod
    def decrypt_token(encrypted_token: str) -> str:
        """
        Decrypt an encrypted token using Fernet encryption.
    
        Args:
            encrypted_token (str): The encrypted token to be decrypted.
    
        Returns:
            str: The decrypted token.
    
        Raises:
            Exception: If there is an error during the decryption process.
        """
        logger.info("Starting token decryption process")
        try:
            fernet = Fernet(TokenEncryption.get_encryption_key())
            decrypted_token = fernet.decrypt(encrypted_token.encode()).decode()
            logger.debug("Token decrypted successfully")
            return decrypted_token
        except Exception as e:
            logger.error(f"Token decryption failed: {str(e)}")
            raise
