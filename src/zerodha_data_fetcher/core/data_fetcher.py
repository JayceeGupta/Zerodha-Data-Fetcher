"""Main data fetcher implementation for Zerodha historical data."""

import json
import logging
import threading
from concurrent.futures import as_completed
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from ..utils.config import Config
from ..utils.exceptions import (
    AuthenticationError,
    DataFetchError,
    InvalidTickerError,
)
from ..utils.helpers import execution_timer, retry_on_failure
from .auth import AuthenticationManager
from .instrument_manager import ZerodhaInstrumentManager
from .rate_limiter import RateLimitedThreadPoolExecutor

logger = logging.getLogger(__name__)

ChunkFailureMode = Literal["strict", "partial"]


class ZerodhaDataFetcher:
    """Main class for fetching historical data from Zerodha API."""

    def __init__(
        self,
        requests_per_second: int = Config.DEFAULT_REQUESTS_PER_SECOND,
        token_expiry_hours: float = Config.DEFAULT_TOKEN_EXPIRY_HOURS,
        instrument_manager: Optional[ZerodhaInstrumentManager] = None,
        cache_ttl_minutes: Optional[int] = None,
        chunk_failure_mode: ChunkFailureMode = "strict",
        user_id: Optional[str] = None,
        password: Optional[str] = None,
        user_type: Optional[str] = None,
        totp_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        login_url: Optional[str] = None,
        two_fa_url: Optional[str] = None,
        historical_url: Optional[str] = None,
        keyring_token_key: Optional[str] = None,
        keyring_encryption_key: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize the Zerodha Data Fetcher.

        Args:
            requests_per_second: Rate limit for API requests.
            token_expiry_hours: Token expiry time in hours.
            instrument_manager: Optional instrument manager instance.
            cache_ttl_minutes: Instrument cache TTL in minutes (default: 1440 = 24 h).
            chunk_failure_mode: Default chunk failure policy. ``"strict"`` raises on
                any failed chunk. ``"partial"`` returns successful chunks and logs one
                summary warning unless all chunks fail.
            user_id: Zerodha user ID (overrides env var).
            password: Zerodha password (overrides env var).
            user_type: Zerodha user type (overrides env var/default value).
            totp_secret: TOTP secret key (overrides env var).
            base_url: Zerodha base URL (overrides env var/default value).
            login_url: Zerodha login URL (overrides env var/default value).
            two_fa_url: Zerodha 2FA URL (overrides env var/default value).
            historical_url: Zerodha historical data URL (overrides env var/default value).
            keyring_token_key: Keyring token key (overrides env var/default value).
            keyring_encryption_key: Keyring encryption key (overrides env var/default value).
            **kwargs: Additional configuration parameters.
        """
        self.requests_per_second = max(
            Config.MIN_REQUESTS_PER_SECOND,
            min(requests_per_second, Config.MAX_REQUESTS_PER_SECOND),
        )
        self.chunk_failure_mode = self._normalize_chunk_failure_mode(chunk_failure_mode)

        config_params = {
            "user_id": user_id,
            "password": password,
            "user_type": user_type,
            "totp_secret": totp_secret,
            "base_url": base_url,
            "login_url": login_url,
            "two_fa_url": two_fa_url,
            "historical_url": historical_url,
            "keyring_token_key": keyring_token_key,
            "keyring_encryption_key": keyring_encryption_key,
            **kwargs,
        }
        config_params = {
            key: value for key, value in config_params.items() if value is not None
        }

        self.config = Config(**config_params)
        self.auth_manager = AuthenticationManager(
            token_expiry_hours, config=self.config
        )
        self.instrument_manager = instrument_manager or ZerodhaInstrumentManager(
            cache_ttl_minutes=cache_ttl_minutes,
        )

        logger.info(
            "ZerodhaDataFetcher initialized with %s req/sec and chunk_failure_mode=%s",
            self.requests_per_second,
            self.chunk_failure_mode,
        )

        if self.config.validate_config():
            logger.info("All required configuration parameters are set")
        else:
            missing = self.config.get_missing_config()
            logger.warning("Missing configuration parameters: %s", missing)

    @staticmethod
    def _normalize_chunk_failure_mode(mode: ChunkFailureMode) -> ChunkFailureMode:
        """Validate and normalize chunk failure mode values."""
        if mode not in ("strict", "partial"):
            raise ValueError("chunk_failure_mode must be either 'strict' or 'partial'")
        return mode

    @staticmethod
    def _format_date_range_label(start_date: date, end_date: date) -> str:
        """Format a human-readable date range label."""
        return f"{start_date} to {end_date}"

    def _format_params_range_label(self, params: Tuple) -> str:
        """Format a date range label from chunk parameters."""
        return self._format_date_range_label(params[0], params[1])

    def _summarize_failed_ranges(
        self, failed_chunks: List[Tuple[Tuple, Exception]]
    ) -> str:
        """Return a compact range summary for failed chunk parameters."""
        return ", ".join(
            self._format_params_range_label(params) for params, _ in failed_chunks
        )

    def _extract_error_payload(self, error_message: str) -> Optional[Dict[str, Any]]:
        """Attempt to extract a Zerodha JSON error payload from an exception message."""
        if "Response: " not in error_message:
            return None

        try:
            return json.loads(error_message.split("Response: ", 1)[1])
        except (json.JSONDecodeError, IndexError):
            return None

    def _cancel_pending_futures(
        self, future_to_params: Dict[Any, Tuple], exclude_future: Any
    ) -> int:
        """Best-effort cancellation for futures that have not started yet."""
        cancelled = 0
        for future in future_to_params:
            if future is exclude_future:
                continue
            cancel = getattr(future, "cancel", None)
            if callable(cancel) and cancel():
                cancelled += 1
        return cancelled

    def _prepare_final_dataframe(self, all_data: List[pd.DataFrame]) -> pd.DataFrame:
        """Combine chunk data and restore the public historical-data schema."""
        final_df = pd.concat(all_data, ignore_index=True)
        logger.debug("Combined DataFrame shape: %s", final_df.shape)

        # Zerodha returns timestamps as "YYYY-MM-DD HH:MM:SS+ZZZZ"
        final_df["Time"] = final_df["Timestamp"].str[11:16]  # Extract "HH:MM"
        final_df["Date"] = final_df["Timestamp"].str[:10]  # Extract "YYYY-MM-DD"
        final_df.sort_values("Timestamp", inplace=True, ignore_index=True)
        final_df.drop(["Timestamp"], axis=1, inplace=True)

        column_order = ["Date", "Time", "Open", "High", "Low", "Close", "Volume"]
        return final_df[column_order]

    def _validate_ticker_token(self, ticker_token: Union[int, str]) -> bool:
        """
        Validate a ticker token by fetching a small data slice.

        Allows one token refresh retry when Zerodha reports token expiry.
        """
        today = date.today()
        before = today - relativedelta(days=28)
        userid = self.config.get_user_id()

        for attempt in range(2):
            try:
                token_data = self.auth_manager.get_auth_token()
                params = (
                    before,
                    today,
                    userid,
                    "minute",
                    ticker_token,
                    {"Authorization": f"enctoken {token_data}"},
                )
                self._fetch_data_chunk(params)
                return True
            except Exception as exc:
                error_message = str(exc)
                error_payload = self._extract_error_payload(error_message)

                if error_payload and error_payload.get("status") == "error":
                    message = error_payload.get("message", "")

                    if "invalid token" in message.lower():
                        logger.error("Invalid token for ticker token %s", ticker_token)
                        return False

                    if error_payload.get("error_type") == "TokenException":
                        if attempt == 0:
                            logger.warning(
                                "Token expired while validating ticker token %s; refreshing once",
                                ticker_token,
                            )
                            self.auth_manager.invalidate_token()
                            continue

                        logger.warning(
                            "Ticker token validation still hit TokenException after one refresh for %s",
                            ticker_token,
                        )
                        return False

                logger.debug(
                    "Ticker validation failed for %s: %s", ticker_token, error_message
                )
                return False

        return False

    def _resolve_ticker_token(self, ticker_token: Union[int, str]) -> int:
        """
        Resolve ticker token from symbol or validate integer token.

        Args:
            ticker_token: Ticker token (int) or symbol (str).

        Returns:
            int: Resolved instrument token.

        Raises:
            InvalidTickerError: If ticker token is invalid.
        """
        if isinstance(ticker_token, int):
            logger.debug("Validating integer ticker token: %s", ticker_token)
            if not self._validate_ticker_token(ticker_token):
                raise InvalidTickerError(f"Invalid ticker token: {ticker_token}")
            return ticker_token

        if isinstance(ticker_token, str):
            logger.debug("Resolving symbol to instrument token: %s", ticker_token)

            instrument_token = self.instrument_manager.get_instrument_token(
                ticker_token.upper(),
                is_stock=True,
            )

            if instrument_token is None:
                instrument_token = self.instrument_manager.get_instrument_token(
                    ticker_token,
                    is_stock=False,
                )

            if instrument_token is None:
                raise InvalidTickerError(f"Symbol not found: {ticker_token}")

            logger.debug(
                "Resolved %s to instrument token: %s", ticker_token, instrument_token
            )
            return instrument_token

        raise InvalidTickerError(f"Invalid ticker token type: {type(ticker_token)}")

    @retry_on_failure(max_retries=3, delay=1.0)
    def _fetch_data_chunk(self, params: Tuple) -> pd.DataFrame:
        """
        Fetch a chunk of historical data from the Kite API.

        Args:
            params: Tuple containing (current_date, next_date, userid, timeframe, token, headers).

        Returns:
            pd.DataFrame: Historical data chunk.

        Raises:
            DataFetchError: If data fetching fails.
        """
        try:
            current_date, next_date, userid, timeframe, token, headers = params

            thread_name = (
                f"({current_date.strftime('%d/%m/%Y')} --> "
                f"{next_date.strftime('%d/%m/%Y')}) in ({timeframe})"
            )
            threading.current_thread().name = thread_name

            logger.debug("Fetching data chunk: %s", thread_name)

            url_template = self.config.get_historical_url()
            if not url_template:
                raise DataFetchError("Historical URL template not configured")

            url = url_template.format(
                token=token,
                timeframe=timeframe,
                userid=userid,
                current_date=current_date,
                next_date=next_date,
            )

            logger.debug("Making API request to: %s", url)

            response = requests.get(
                url,
                headers=headers,
                timeout=Config.REQUEST_TIMEOUT,
            )

            logger.debug("API Response Status: %s", response.status_code)

            if response.status_code != 200:
                error_msg = (
                    f"API request failed with status {response.status_code}. "
                    f"Response: {response.text}"
                )
                logger.error(error_msg)
                raise DataFetchError(error_msg)

            response_data = response.json()
            logger.debug("Successfully parsed JSON response")

            if "data" not in response_data or "candles" not in response_data["data"]:
                logger.error("Unexpected response structure: %s", response_data)
                raise DataFetchError("Invalid response structure from API")

            candles = response_data["data"]["candles"]
            if not candles:
                logger.warning(
                    "No data found for period: %s to %s", current_date, next_date
                )
                return pd.DataFrame()

            columns = ["Timestamp", "Open", "High", "Low", "Close", "Volume", "OI"]
            df = pd.DataFrame(candles, columns=columns)
            # "OI" = Open Interest; included in the API response but not
            # relevant for historical OHLCV data, so we drop it.
            df.drop(["OI"], axis=1, inplace=True, errors="ignore")

            logger.info(
                "Successfully fetched chunk: %s for %s to %s",
                df.shape,
                current_date,
                next_date,
            )
            return df

        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error: %s", str(exc))
            raise DataFetchError(f"Connection error: {str(exc)}")
        except requests.exceptions.Timeout as exc:
            logger.error("Request timeout: %s", str(exc))
            raise DataFetchError(f"Request timeout: {str(exc)}")
        except requests.exceptions.RequestException as exc:
            logger.error("Request failed: %s", str(exc))
            raise DataFetchError(f"Request failed: {str(exc)}")
        except json.JSONDecodeError as exc:
            logger.error("JSON parsing error: %s", str(exc))
            raise DataFetchError(f"Invalid JSON response: {str(exc)}")
        except DataFetchError:
            raise
        except Exception as exc:
            logger.error("Unexpected error in data chunk fetch: %s", str(exc))
            raise DataFetchError(f"Data fetch failed: {str(exc)}")

    def _validate_date_range(
        self, start_date: date, end_date: date
    ) -> Tuple[date, date]:
        """
        Validate and adjust date range parameters.

        Args:
            start_date: Start date for data fetch.
            end_date: End date for data fetch.

        Returns:
            Tuple[date, date]: Validated start and end dates.
        """
        if end_date > date.today():
            logger.warning("End date %s is in future, setting to today", end_date)
            end_date = date.today()

        ten_years_ago = date.today() - relativedelta(years=Config.MAX_HISTORICAL_YEARS)
        if start_date < ten_years_ago:
            logger.warning(
                "Start date %s is too old, setting to %s", start_date, ten_years_ago
            )
            start_date = ten_years_ago

        if start_date > end_date:
            logger.warning(
                "Start date %s > end date %s, swapping", start_date, end_date
            )
            start_date, end_date = end_date, start_date

        return start_date, end_date

    def _generate_date_ranges(
        self,
        start_date: date,
        end_date: date,
        userid: str,
        timeframe: str,
        token: int,
        headers: Dict[str, str],
    ) -> List[Tuple]:
        """
        Generate date ranges for parallel data fetching.

        Args:
            start_date: Start date.
            end_date: End date.
            userid: User ID.
            timeframe: Data timeframe.
            token: Instrument token.
            headers: Request headers.

        Returns:
            List[Tuple]: Parameter tuples for parallel processing.
        """
        date_ranges = []
        interval = timedelta(days=Config.DEFAULT_CHUNK_DAYS)
        current_date = start_date

        while current_date < end_date:
            next_date = min(current_date + interval, end_date)
            date_ranges.append(
                (current_date, next_date, userid, timeframe, token, headers)
            )
            current_date = next_date + timedelta(days=1)

        logger.debug("Generated %s date ranges for processing", len(date_ranges))
        return date_ranges

    @execution_timer
    def fetch_futures_historical_data(
        self,
        underlying: str,
        start_date: date,
        end_date: date,
        *,
        selector: str = "near",
        year: Optional[int] = None,
        month: Optional[int] = None,
        exchange: str = "MCX",
        segment: str = "MCX-FUT",
        timeframe: str = "minute",
        roll_offset_days: int = 0,
        on_stale: Optional[str] = None,
        chunk_failure_mode: Optional[ChunkFailureMode] = None,
    ) -> pd.DataFrame:
        """Resolve one futures contract for *underlying*, then fetch it.

        The historical fetch path is instrument-token driven, so this method
        only adds contract resolution on top of :meth:`fetch_historical_data`;
        the output schema is unchanged: ``[Date, Time, Open, High, Low, Close,
        Volume]``.

        Args:
            underlying: Underlying name (e.g. ``"GOLD"``), matched exactly.
            selector: ``"near"``/``"near_prev"``/``"near_next"`` (by expiry) or
                ``"specific"`` (requires *year* and *month*).
            year, month: Required when ``selector == "specific"``.
            roll_offset_days: Roll the ``near`` contract this many days before
                expiry (see :meth:`ZerodhaInstrumentManager.resolve_futures_contract`).
            on_stale: Freshness policy for forward selectors; ``None`` uses the
                instrument manager's default.

        Raises:
            ValueError: If ``selector == "specific"`` without *year*/*month*,
                or if no contract can be resolved for the request.
        """
        if selector == "specific":
            if year is None or month is None:
                raise ValueError(
                    "selector='specific' requires both 'year' and 'month'."
                )
            contract = self.instrument_manager.resolve_specific_contract(
                underlying, year, month, exchange=exchange, segment=segment
            )
        else:
            contract = self.instrument_manager.resolve_futures_contract(
                underlying,
                selector,
                exchange=exchange,
                segment=segment,
                roll_offset_days=roll_offset_days,
                on_stale=on_stale,
            )

        if contract is None:
            raise ValueError(
                "Could not resolve a %s futures contract for %r (selector=%r)."
                % (segment, underlying, selector)
            )

        logger.info(
            "Resolved %s %s → %s (token %s, expiry %s)",
            underlying,
            selector,
            contract.tradingsymbol,
            contract.instrument_token,
            contract.expiry,
        )
        return self.fetch_historical_data(
            contract.instrument_token,
            start_date,
            end_date,
            timeframe=timeframe,
            chunk_failure_mode=chunk_failure_mode,
        )

    def fetch_historical_data(
        self,
        ticker_token: Union[int, str],
        start_date: date,
        end_date: date,
        timeframe: str = "minute",
        chunk_failure_mode: Optional[ChunkFailureMode] = None,
    ) -> pd.DataFrame:
        """
        Fetch historical data from Zerodha API.

        Args:
            ticker_token: Instrument token or symbol.
            start_date: Start date for data fetch.
            end_date: End date for data fetch.
            timeframe: Data timeframe (``"minute"``, ``"day"``, etc.).
            chunk_failure_mode: Optional per-call override for chunk failure policy.
                ``"strict"`` raises on any failed chunk and never returns partial
                data. ``"partial"`` returns successful chunks, emits one warning
                summary for failed ranges, and raises only when every chunk fails.

        Returns:
            pd.DataFrame: Historical data with columns
                [Date, Time, Open, High, Low, Close, Volume].

        Raises:
            InvalidTickerError: If ticker token is invalid.
            DataFetchError: If data fetching fails.
            AuthenticationError: If authentication fails.
        """
        effective_chunk_failure_mode = self._normalize_chunk_failure_mode(
            chunk_failure_mode or self.chunk_failure_mode
        )

        logger.info("Starting historical data fetch for %s", ticker_token)
        logger.info(
            "Date range: %s to %s, Timeframe: %s, chunk_failure_mode=%s",
            start_date,
            end_date,
            timeframe,
            effective_chunk_failure_mode,
        )

        try:
            resolved_token = self._resolve_ticker_token(ticker_token)
            start_date, end_date = self._validate_date_range(start_date, end_date)

            auth_token = self.auth_manager.get_auth_token()
            headers = {"Authorization": f"enctoken {auth_token}"}
            userid = self.config.get_user_id()

            logger.debug(
                "Using resolved token: %s, User ID: %s", resolved_token, userid
            )

            date_ranges = self._generate_date_ranges(
                start_date,
                end_date,
                userid,
                timeframe,
                resolved_token,
                headers,
            )

            all_data: List[pd.DataFrame] = []
            failed_chunks: List[Tuple[Tuple, Exception]] = []
            empty_chunks = 0
            cancelled_pending_chunks = 0

            logger.info("Fetching %s data chunks in parallel", len(date_ranges))

            with RateLimitedThreadPoolExecutor(
                max_workers=Config.MAX_WORKERS,
                requests_per_second=self.requests_per_second,
            ) as executor:
                future_to_params = {
                    executor.submit(self._fetch_data_chunk, params): params
                    for params in date_ranges
                }

                for future in as_completed(future_to_params):
                    params = future_to_params[future]
                    current_date, next_date = params[0], params[1]

                    try:
                        df = future.result()
                    except Exception as exc:
                        failed_chunks.append((params, exc))

                        if effective_chunk_failure_mode == "strict":
                            cancelled_pending_chunks = self._cancel_pending_futures(
                                future_to_params,
                                exclude_future=future,
                            )
                            logger.error(
                                "Chunk failed in strict mode for range %s",
                                self._format_date_range_label(current_date, next_date),
                            )
                            break
                        continue

                    if df.empty:
                        logger.warning(
                            "Empty data for range: %s to %s", current_date, next_date
                        )
                        empty_chunks += 1
                        continue

                    all_data.append(df)
                    logger.debug(
                        "Processed chunk successfully, total chunks: %s", len(all_data)
                    )

            if empty_chunks > 0:
                logger.warning(
                    "Found %s/%s empty data ranges", empty_chunks, len(date_ranges)
                )

            if failed_chunks:
                if effective_chunk_failure_mode == "strict":
                    first_failed_params, first_error = failed_chunks[0]
                    summary = (
                        f"Historical fetch failed in strict mode after "
                        f"{len(failed_chunks)} chunk failure(s); first failed range "
                        f"{self._format_params_range_label(first_failed_params)}: {first_error}"
                    )
                    if cancelled_pending_chunks:
                        summary += (
                            f"; cancelled {cancelled_pending_chunks} pending chunk(s)"
                        )
                    raise DataFetchError(summary)

                if all_data:
                    logger.warning(
                        "Historical fetch completed with partial data: %s/%s chunks failed. Failed ranges: %s",
                        len(failed_chunks),
                        len(date_ranges),
                        self._summarize_failed_ranges(failed_chunks),
                    )
                else:
                    first_failed_params, first_error = failed_chunks[0]
                    raise DataFetchError(
                        "Historical fetch failed: all "
                        f"{len(failed_chunks)} chunk(s) failed. Failed ranges: "
                        f"{self._summarize_failed_ranges(failed_chunks)}. First error from "
                        f"{self._format_params_range_label(first_failed_params)}: {first_error}"
                    )

            if not all_data:
                logger.warning(
                    "No data found for %s in range %s to %s",
                    ticker_token,
                    start_date,
                    end_date,
                )
                return pd.DataFrame()

            logger.info("Processing %s data chunks", len(all_data))
            final_df = self._prepare_final_dataframe(all_data)

            logger.info(
                "Data fetch completed successfully. Final shape: %s", final_df.shape
            )
            logger.info(
                "Date range in data: %s to %s",
                final_df["Date"].min(),
                final_df["Date"].max(),
            )
            return final_df

        except (InvalidTickerError, AuthenticationError, DataFetchError) as exc:
            logger.error("Historical data fetch failed: %s", str(exc))
            raise
        except Exception as exc:
            logger.error("Unexpected error during data fetch: %s", str(exc))
            raise DataFetchError(f"Data fetch failed: {str(exc)}")

    def get_instrument_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get instrument information for a symbol.

        Args:
            symbol: Trading symbol to lookup.

        Returns:
            Dict with instrument information or None if not found.
        """
        try:
            results = self.instrument_manager.search_symbol(symbol, limit=1)

            if not results.empty:
                info = results.iloc[0].to_dict()
                logger.debug("Found instrument info for %s: %s", symbol, info)
                return info

            logger.warning("No instrument info found for symbol: %s", symbol)
            return None

        except Exception as exc:
            logger.error("Error getting instrument info for %s: %s", symbol, str(exc))
            return None

    def search_symbols(self, partial_name: str, limit: int = 10) -> pd.DataFrame:
        """
        Search for symbols matching partial name.

        Args:
            partial_name: Partial symbol name to search.
            limit: Maximum results to return.

        Returns:
            DataFrame with matching symbols.
        """
        try:
            return self.instrument_manager.search_symbol(partial_name, limit)
        except Exception as exc:
            logger.error("Error searching symbols for '%s': %s", partial_name, str(exc))
            return pd.DataFrame()


# ---------------------------------------------------------------------------
# Legacy API — preserved for backward compatibility only.
# New code should use ZerodhaDataFetcher directly.
# ---------------------------------------------------------------------------


@execution_timer
def fetchDataZerodha(
    ticker_token: Union[int, str] = 408065,
    startDate: date = date(2021, 5, 9),
    endDate: date = date(2021, 6, 9),
    reqPerSec: int = 2,
) -> pd.DataFrame:
    """Fetch historical data from Zerodha.

    .. deprecated::
        Use :class:`ZerodhaDataFetcher` and its
        :meth:`~ZerodhaDataFetcher.fetch_historical_data` method instead.
        This function is retained only so that existing callers continue
        to work without changes.

    Args:
        ticker_token: Instrument token or symbol.
        startDate: Start date for data fetch.
        endDate: End date for data fetch.
        reqPerSec: Requests per second rate limit.

    Returns:
        pd.DataFrame: Historical data.
    """
    import warnings

    warnings.warn(
        "fetchDataZerodha() is deprecated. "
        "Use ZerodhaDataFetcher().fetch_historical_data() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    fetcher = ZerodhaDataFetcher(requests_per_second=reqPerSec)
    return fetcher.fetch_historical_data(ticker_token, startDate, endDate)
