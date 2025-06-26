"""Authentication management for Zerodha API."""

import os
import time
import logging
from datetime import date
from typing import Optional

import keyring

from ..utils.config import Config
from ..utils.exceptions import AuthenticationError, TokenExpiredError
from ..utils.encryption import TokenEncryption
from .token_generator import ZerodhaTokenGenerator

logger = logging.getLogger(__name__)


class AuthenticationManager:
    """Manages authentication tokens for Zerodha API."""
    
    def __init__(self, token_expiry_hours: float = Config.DEFAULT_TOKEN_EXPIRY_HOURS):
        self.token_expiry_hours = token_expiry_hours
        self.token_key = Config.ZERODHA_KEYRING_TOKEN_KEY
        self.token_generator = ZerodhaTokenGenerator()
        
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
            
            logger.debug(f"Getting auth token for date: {today}")
            
            # Try to retrieve stored token
            encrypted_token = keyring.get_password(self.token_key, "token")
            token_date = keyring.get_password(self.token_key, "date")
            token_timestamp = keyring.get_password(self.token_key, "timestamp")
            
            if encrypted_token and token_date and token_timestamp:
                logger.debug("Found token data in keyring")
                time_elapsed = current_time - float(token_timestamp)
                logger.debug(f"Time elapsed since last token: {time_elapsed} seconds")
                
                if token_date == today and time_elapsed < expiry_seconds:
                    logger.info("Found valid token for today")
                    return TokenEncryption.decrypt_token(encrypted_token)
                else:
                    logger.debug("Stored token is outdated")
            else:
                logger.debug("No valid token data found in keyring")
                
        except Exception as e:
            logger.error(f"Error retrieving token: {str(e)}")
            
        # Generate new token
        return self._generate_new_token()
    
    def _generate_new_token(self) -> str:
        """Generate and store a new authentication token."""
        logger.info("Generating new auth token")
        
        try:
            new_token = self.token_generator.generate_auth_token()
            encrypted_token = TokenEncryption.encrypt_token(new_token)
                
            # Store the new token
            today = date.today().strftime('%Y-%m-%d')
            current_time = time.time()
            
            keyring.set_password(self.token_key, "token", encrypted_token)
            keyring.set_password(self.token_key, "date", today)
            keyring.set_password(self.token_key, "timestamp", str(current_time))
            keyring.set_password(self.token_key, "userid", Config.get_user_id())
            
            logger.info("Successfully saved new token to keyring")
            return new_token
            
        except Exception as e:
            logger.error(f"Failed to generate/save token: {str(e)}")
            raise AuthenticationError(f"Token generation failed: {str(e)}")
    
    def invalidate_token(self) -> None:
        """Invalidate the current stored token."""
        try:
            keyring.delete_password(self.token_key, "token")
            keyring.delete_password(self.token_key, "date") 
            keyring.delete_password(self.token_key, "timestamp")
            logger.info("Token invalidated successfully")
        except Exception as e:
            logger.warning(f"Failed to invalidate token: {str(e)}")
