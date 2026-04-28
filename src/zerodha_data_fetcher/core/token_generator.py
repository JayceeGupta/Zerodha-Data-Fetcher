"""Token generation functionality for Zerodha API authentication."""

import json
import logging
import os
from typing import Dict

import pyotp
from requests import Session
from requests.exceptions import HTTPError
from dotenv import load_dotenv

from ..utils.exceptions import AuthenticationError

load_dotenv()
logger = logging.getLogger(__name__)

# Browser-like User-Agent required by Zerodha's login endpoint to avoid
# bot-detection rejection.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


class ZerodhaTokenGenerator:
    """Handles generation of Zerodha authentication tokens."""

    def __init__(self, config):
        """
        Initialize the token generator.

        Args:
            config: A :class:`~zerodha_data_fetcher.utils.config.Config`
                instance that supplies Zerodha credentials (user ID,
                password, TOTP secret) and endpoint URLs.  If ``None``,
                a default ``Config()`` is created from environment
                variables.

        Configuration is validated eagerly so that missing credentials
        are surfaced at construction time rather than mid-authentication.

        Raises:
            ValueError: If required configuration fields are missing.
        """
        from ..utils.config import Config

        self.config = config or Config()

        # Validate required configuration
        if not self.config.validate_config():
            missing_vars = self.config.get_missing_config()
            logger.error(f"Missing required configuration: {', '.join(missing_vars)}")
            raise ValueError(
                f"Missing required configuration: {', '.join(missing_vars)}"
            )

    def get_totp(self, key: str = "") -> str:
        """
        Generates a Time-based One-Time Password (TOTP) value using the provided secret key.

        Args:
            key (str, optional): The TOTP secret key. If None, uses ZERODHA_TOTP_SECRET from env.

        Returns:
            str: The current TOTP value.

        Raises:
            AuthenticationError: If there is any error generating the TOTP value.
        """
        logger.debug("Generating TOTP for authentication")

        try:
            totp_secret = key or self.config.ZERODHA_TOTP_SECRET

            if totp_secret is None:
                raise AuthenticationError("TOTP secret not available")

            # 30-second time window per RFC 6238 (TOTP standard)
            totp = pyotp.TOTP(totp_secret, interval=30)
            logger.debug("TOTP object created successfully")
            return totp.now()

        except Exception as e:
            logger.error(f"Failed to generate TOTP: {str(e)}")
            raise AuthenticationError(f"TOTP generation failed: {str(e)}")

    def generate_auth_token(self) -> str:
        """
        Generates an encrypted authentication token for accessing the Zerodha API.

        This function performs the following steps:
        1. Generates a TOTP (Time-based One-Time Password) value
        2. Starts an initial session with the Zerodha base URL
        3. Sends a login request with credentials
        4. Sends a 2FA (Two-Factor Authentication) request with the TOTP value
        5. Retrieves the encrypted authentication token (enctoken) from response cookies

        Returns:
            str: The encrypted authentication token (enctoken) for accessing the Zerodha API.

        Raises:
            AuthenticationError: If authentication fails at any step
        """
        logger.info("Starting auth flow")

        try:
            # --- Stage 1: Prepare credentials & generate TOTP ---
            userid = self.config.ZERODHA_USER_ID
            password = self.config.ZERODHA_PASSWORD
            user_type = self.config.ZERODHA_TYPE
            totp_secret = self.config.ZERODHA_TOTP_SECRET
            base_url = self.config.ZERODHA_BASE_URL
            login_url = self.config.ZERODHA_LOGIN_URL
            two_factor_url = self.config.ZERODHA_2FA_URL

            logger.debug("Authentication configuration validated successfully")

            # Generate TOTP
            totp_value = self.get_totp(totp_secret)
            logger.debug("Generated TOTP successfully")

            # --- Stage 2: Start browser-like session ---
            session = Session()
            start_session_response = session.get(base_url)
            start_session_response.raise_for_status()
            logger.debug("Initial auth session started successfully")

            # Prepare headers
            generic_headers: Dict[str, str] = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept-Encoding": "gzip, deflate, br",
                "User-Agent": _DEFAULT_USER_AGENT,
            }

            # --- Stage 3: Login with credentials ---
            login_payload = {"user_id": userid, "password": password, "type": user_type}
            login_response = session.post(
                login_url, data=login_payload, headers=generic_headers
            )
            login_response.raise_for_status()
            logger.info("Login request succeeded")

            # Parse login response
            login_data = json.loads(login_response.content)

            if not login_data.get("data") or not login_data["data"].get("request_id"):
                error_msg = login_data.get("message", "Unknown error")
                logger.error("Login response missing request_id: %s", error_msg)
                raise AuthenticationError(f"Login failed: {error_msg}")

            request_id = login_data["data"]["request_id"]
            logger.debug("Received login request identifier")

            # --- Stage 4: Two-factor authentication ---
            two_factor_payload = {
                "user_id": userid,
                "request_id": request_id,
                "twofa_value": totp_value,
                "twofatype": "totp",
            }
            two_factor_response = session.post(
                two_factor_url, data=two_factor_payload, headers=generic_headers
            )
            two_factor_response.raise_for_status()
            logger.info("2FA succeeded")

            # --- Stage 5: Extract encrypted token from session cookies ---
            if "enctoken" not in session.cookies:
                logger.error(
                    "Authentication response did not include an enctoken cookie"
                )
                raise AuthenticationError("Authentication failed: No enctoken received")

            logger.info("Authentication token acquired")
            return session.cookies["enctoken"]

        except json.JSONDecodeError as e:
            logger.error("Failed to parse authentication response JSON")
            raise AuthenticationError(f"JSON parsing error: {str(e)}")
        except HTTPError as e:
            status_code = (
                e.response.status_code if e.response is not None else "unknown"
            )
            logger.error(
                "Authentication request failed with HTTP status %s", status_code
            )
            raise AuthenticationError(f"Token generation failed: {str(e)}")
        except Exception as e:
            logger.error("Authentication failed: %s", str(e))
            raise AuthenticationError(f"Token generation failed: {str(e)}")


# ---------------------------------------------------------------------------
# Legacy API — preserved for backward compatibility only.
# New code should use ZerodhaTokenGenerator directly.
# ---------------------------------------------------------------------------


def getEncAuthToken() -> str:
    """Generate an authentication token.

    .. deprecated::
        Use ``ZerodhaTokenGenerator(config).generate_auth_token()`` instead.
        This function is retained only so that existing callers continue
        to work without changes.

    Returns:
        str: The encrypted authentication token.
    """
    import warnings

    warnings.warn(
        "getEncAuthToken() is deprecated. "
        "Use ZerodhaTokenGenerator(config).generate_auth_token() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from ..utils.config import Config

    generator = ZerodhaTokenGenerator(config=Config())
    return generator.generate_auth_token()


def get_TOTP(key: str = "ZERODHA_TOTP_SECRET") -> str:
    """Generate a TOTP value.

    .. deprecated::
        Use ``ZerodhaTokenGenerator(config).get_totp(secret)`` instead.
        This function is retained only so that existing callers continue
        to work without changes.

    Args:
        key: TOTP secret key, **or** the name of an environment variable
            that holds the secret (detected when *key* is ALL_CAPS with
            underscores, e.g. ``"ZERODHA_TOTP_SECRET"``).

    Returns:
        str: The current TOTP value.
    """
    import warnings

    warnings.warn(
        "get_TOTP() is deprecated. "
        "Use ZerodhaTokenGenerator(config).get_totp(secret) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from ..utils.config import Config

    generator = ZerodhaTokenGenerator(config=Config())
    # If key looks like an env var name, get it from environment
    if key.isupper() and "_" in key:
        secret = os.getenv(key, "")
    else:
        secret = key
    return generator.get_totp(secret)
