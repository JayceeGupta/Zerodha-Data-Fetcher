"""Main data fetcher implementation for Zerodha historical data."""

import os
import json
import time
import logging
import threading
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from concurrent.futures import as_completed
from typing import Dict, List, Union, Optional, Any, Tuple

import requests
import pandas as pd

from ..utils.config import Config
from ..utils.exceptions import (
    ZerodhaAPIError, 
    AuthenticationError, 
    InvalidTickerError,
    DataFetchError,
    TokenExpiredError
)
from ..utils.helpers import execution_timer, retry_on_failure
from .auth import AuthenticationManager
from .rate_limiter import RateLimitedThreadPoolExecutor
from .instrument_manager import ZerodhaInstrumentManager

logger = logging.getLogger(__name__)


class ZerodhaDataFetcher:
    """Main class for fetching historical data from Zerodha API."""
    
    def __init__(self, 
                 requests_per_second: int = Config.DEFAULT_REQUESTS_PER_SECOND,
                 token_expiry_hours: float = Config.DEFAULT_TOKEN_EXPIRY_HOURS,
                 instrument_manager: Optional[ZerodhaInstrumentManager] = None):
        """
        Initialize the Zerodha Data Fetcher.
        
        Args:
            requests_per_second: Rate limit for API requests
            token_expiry_hours: Token expiry time in hours
            instrument_manager: Optional instrument manager instance
        """
        self.requests_per_second = max(
            Config.MIN_REQUESTS_PER_SECOND,
            min(requests_per_second, Config.MAX_REQUESTS_PER_SECOND)
        )
        
        self.auth_manager = AuthenticationManager(token_expiry_hours)
        self.instrument_manager = instrument_manager or ZerodhaInstrumentManager()
        
        logger.info(f"ZerodhaDataFetcher initialized with {self.requests_per_second} req/sec")
    
    def _validate_ticker_token(self, ticker_token: Union[int, str]) -> bool:
        """
        Validates a given ticker token by attempting to fetch a small data chunk.
        
        Args:
            ticker_token: The ticker token or symbol to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        try:
            today = date.today()
            before = today - relativedelta(days=28)
            token_data = self.auth_manager.get_auth_token()
            
            # Try to fetch a small chunk of data
            params = (
                before, today, 
                Config.get_user_id(), 
                'minute', 
                ticker_token, 
                {'Authorization': f'enctoken {token_data}'}
            )
            
            self._fetch_data_chunk(params)
            return True
            
        except Exception as e:
            error_message = str(e)
            
            # Parse error response if it's a JSON error
            try:
                if "Response: " in error_message:
                    error_dict = json.loads(error_message.split("Response: ")[1])
                    
                    if error_dict.get('status') == 'error':
                        if 'invalid token' in error_dict.get('message', '').lower():
                            logger.error(f"Invalid token for ticker token {ticker_token}")
                            return False
                        
                        if error_dict.get('error_type') == "TokenException":
                            # Token expired, invalidate and retry once
                            self.auth_manager.invalidate_token()
                            return self._validate_ticker_token(ticker_token)
                            
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
            
            logger.debug(f"Ticker validation failed for {ticker_token}: {error_message}")
            return False
    
    def _resolve_ticker_token(self, ticker_token: Union[int, str]) -> int:
        """
        Resolve ticker token from symbol or validate integer token.
        
        Args:
            ticker_token: Ticker token (int) or symbol (str)
            
        Returns:
            int: Resolved instrument token
            
        Raises:
            InvalidTickerError: If ticker token is invalid
        """
        if isinstance(ticker_token, int):
            logger.debug(f"Validating integer ticker token: {ticker_token}")
            if not self._validate_ticker_token(ticker_token):
                raise InvalidTickerError(f"Invalid ticker token: {ticker_token}")
            return ticker_token
        
        elif isinstance(ticker_token, str):
            logger.debug(f"Resolving symbol to instrument token: {ticker_token}")
            
            # Try to get instrument token from symbol
            instrument_token = self.instrument_manager.get_instrument_token(
                ticker_token.upper(), is_stock=True
            )
            
            if instrument_token is None:
                # Try commodities if stock lookup failed
                instrument_token = self.instrument_manager.get_instrument_token(
                    ticker_token, is_stock=False
                )
            
            if instrument_token is None:
                raise InvalidTickerError(f"Symbol not found: {ticker_token}")
            
            logger.debug(f"Resolved {ticker_token} to instrument token: {instrument_token}")
            return instrument_token
        
        else:
            raise InvalidTickerError(f"Invalid ticker token type: {type(ticker_token)}")
    
    @retry_on_failure(max_retries=3, delay=1.0)
    def _fetch_data_chunk(self, params: Tuple) -> pd.DataFrame:
        """
        Fetches a chunk of historical data from the Kite API.
        
        Args:
            params: Tuple containing (current_date, next_date, userid, timeframe, token, headers)
            
        Returns:
            pd.DataFrame: Historical data chunk
            
        Raises:
            DataFetchError: If data fetching fails
        """
        try:
            current_date, next_date, userid, timeframe, token, headers = params
            
            # Set thread name for better logging
            thread_name = f"({current_date.strftime('%d/%m/%Y')} --> {next_date.strftime('%d/%m/%Y')}) in ({timeframe})"
            threading.current_thread().name = thread_name
            
            logger.debug(f"Fetching data chunk: {thread_name}")
            
            # Get URL template
            url_template = Config.get_historical_url()
            if not url_template:
                raise DataFetchError("Historical URL template not configured")
            
            # Format URL
            url = url_template.format(
                token=token,
                timeframe=timeframe,
                userid=userid,
                current_date=current_date,
                next_date=next_date
            )
            
            logger.debug(f"Making API request to: {url}")
            
            # Make API request
            response = requests.get(
                url, 
                headers=headers, 
                timeout=Config.REQUEST_TIMEOUT
            )
            
            logger.debug(f"API Response Status: {response.status_code}")
            
            if response.status_code != 200:
                error_msg = f"API request failed with status {response.status_code}. Response: {response.text}"
                logger.error(error_msg)
                raise DataFetchError(error_msg)
            
            # Parse response
            response_data = response.json()
            logger.debug("Successfully parsed JSON response")
            
            # Validate response structure
            if 'data' not in response_data or 'candles' not in response_data['data']:
                logger.error(f"Unexpected response structure: {response_data}")
                raise DataFetchError("Invalid response structure from API")
            
            candles = response_data['data']['candles']
            if not candles:
                logger.warning(f"No data found for period: {current_date} to {next_date}")
                return pd.DataFrame()
            
            logger.debug(f"Retrieved {len(candles)} candles")
            
            # Create DataFrame
            columns = ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'OI']
            df = pd.DataFrame(candles, columns=columns)
            
            # Remove OI column as it's not needed for most use cases
            df.drop(['OI'], axis=1, inplace=True, errors='ignore')
            
            logger.info(f"Successfully fetched chunk: {df.shape} for {current_date} to {next_date}")
            return df
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            raise DataFetchError(f"Connection error: {str(e)}")
        except requests.exceptions.Timeout as e:
            logger.error(f"Request timeout: {str(e)}")
            raise DataFetchError(f"Request timeout: {str(e)}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            raise DataFetchError(f"Request failed: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {str(e)}")
            raise DataFetchError(f"Invalid JSON response: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in data chunk fetch: {str(e)}")
            raise DataFetchError(f"Data fetch failed: {str(e)}")
    
    def _validate_date_range(self, start_date: date, end_date: date) -> Tuple[date, date]:
        """
        Validate and adjust date range parameters.
        
        Args:
            start_date: Start date for data fetch
            end_date: End date for data fetch
            
        Returns:
            Tuple[date, date]: Validated start and end dates
        """
        # Adjust end date if it's in the future
        if end_date > date.today():
            logger.warning(f"End date {end_date} is in future, setting to today")
            end_date = date.today()
        
        # Adjust start date if it's too far in the past
        ten_years_ago = date.today() - relativedelta(years=Config.MAX_HISTORICAL_YEARS)
        if start_date < ten_years_ago:
            logger.warning(f"Start date {start_date} is too old, setting to {ten_years_ago}")
            start_date = ten_years_ago
        
        # Swap dates if start > end
        if start_date > end_date:
            logger.warning(f"Start date {start_date} > end date {end_date}, swapping")
            start_date, end_date = end_date, start_date
        
        return start_date, end_date
    
    def _generate_date_ranges(self, start_date: date, end_date: date, 
                            userid: str, timeframe: str, token: int, 
                            headers: Dict[str, str]) -> List[Tuple]:
        """
        Generate date ranges for parallel data fetching.
        
        Args:
            start_date: Start date
            end_date: End date
            userid: User ID
            timeframe: Data timeframe
            token: Instrument token
            headers: Request headers
            
        Returns:
            List of parameter tuples for parallel processing
        """
        date_ranges = []
        interval = timedelta(days=Config.DEFAULT_CHUNK_DAYS)
        current_date = start_date
        
        while current_date < end_date:
            next_date = min(current_date + interval, end_date)
            date_ranges.append((current_date, next_date, userid, timeframe, token, headers))
            current_date = next_date + timedelta(days=1)
        
        logger.debug(f"Generated {len(date_ranges)} date ranges for processing")
        return date_ranges
    
    @execution_timer
    def fetch_historical_data(self, 
                            ticker_token: Union[int, str],
                            start_date: date,
                            end_date: date,
                            timeframe: str = 'minute') -> pd.DataFrame:
        """
        Fetch historical data from Zerodha API.
        
        Args:
            ticker_token: Instrument token or symbol
            start_date: Start date for data fetch
            end_date: End date for data fetch
            timeframe: Data timeframe ('minute', 'day', etc.)
            
        Returns:
            pd.DataFrame: Historical data with columns [Open, High, Low, Close, Volume, Time, Date]
            
        Raises:
            InvalidTickerError: If ticker token is invalid
            DataFetchError: If data fetching fails
            AuthenticationError: If authentication fails
        """
        logger.info(f"Starting historical data fetch for {ticker_token}")
        logger.info(f"Date range: {start_date} to {end_date}, Timeframe: {timeframe}")
        
        try:
            # Validate and resolve ticker token
            resolved_token = self._resolve_ticker_token(ticker_token)
            
            # Validate date range
            start_date, end_date = self._validate_date_range(start_date, end_date)
            
            # Get authentication token and headers
            auth_token = self.auth_manager.get_auth_token()
            headers = {'Authorization': f'enctoken {auth_token}'}
            userid = Config.get_user_id()
            
            logger.debug(f"Using resolved token: {resolved_token}, User ID: {userid}")
            
            # Generate date ranges for parallel processing
            date_ranges = self._generate_date_ranges(
                start_date, end_date, userid, timeframe, resolved_token, headers
            )
            
            # Fetch data chunks in parallel
            all_data = []
            empty_chunks = 0
            
            logger.info(f"Fetching {len(date_ranges)} data chunks in parallel")
            
            with RateLimitedThreadPoolExecutor(
                max_workers=Config.MAX_WORKERS, 
                requests_per_second=self.requests_per_second
            ) as executor:
                
                # Submit all tasks
                future_to_params = {
                    executor.submit(self._fetch_data_chunk, params): params 
                    for params in date_ranges
                }
                
                # Process completed tasks
                for future in as_completed(future_to_params):
                    try:
                        params = future_to_params[future]
                        current_date, next_date = params[0], params[1]
                        
                        df = future.result()
                        
                        if df.empty:
                            logger.warning(f"Empty data for range: {current_date} to {next_date}")
                            empty_chunks += 1
                            continue
                        
                        all_data.append(df)
                        logger.debug(f"Processed chunk successfully, total chunks: {len(all_data)}")
                        
                    except Exception as e:
                        logger.error(f"Error processing data chunk: {str(e)}")
                        # Continue processing other chunks
            
            if empty_chunks > 0:
                logger.warning(f"Found {empty_chunks}/{len(date_ranges)} empty data ranges")
            
            if not all_data:
                logger.warning(f"No data found for {ticker_token} in range {start_date} to {end_date}")
                return pd.DataFrame()
            
            logger.info(f"Processing {len(all_data)} data chunks")
            
                        # Combine all data
            final_df = pd.concat(all_data, ignore_index=True)
            logger.debug(f"Combined DataFrame shape: {final_df.shape}")
            
            # Process timestamps and create time/date columns
            final_df['Time'] = final_df['Timestamp'].str[11:16]  # Extract 'HH:MM'
            final_df['Date'] = final_df['Timestamp'].str[:10]   # Extract 'YYYY-MM-DD'
            
            # Sort by timestamp and clean up
            final_df.sort_values('Timestamp', inplace=True, ignore_index=True)
            final_df.drop(['Timestamp'], axis=1, inplace=True)
            
            # Reorder columns for better readability
            column_order = ['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume']
            final_df = final_df[column_order]
            
            logger.info(f"Data fetch completed successfully. Final shape: {final_df.shape}")
            logger.info(f"Date range in data: {final_df['Date'].min()} to {final_df['Date'].max()}")
            
            return final_df
            
        except (InvalidTickerError, AuthenticationError) as e:
            logger.error(f"Validation error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during data fetch: {str(e)}")
            raise DataFetchError(f"Data fetch failed: {str(e)}")
    
    def get_instrument_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get instrument information for a symbol.
        
        Args:
            symbol: Trading symbol to lookup
            
        Returns:
            Dict with instrument information or None if not found
        """
        try:
            # Search in instrument manager
            results = self.instrument_manager.search_symbol(symbol, limit=1)
            
            if not results.empty:
                info = results.iloc[0].to_dict()
                logger.debug(f"Found instrument info for {symbol}: {info}")
                return info
            else:
                logger.warning(f"No instrument info found for symbol: {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting instrument info for {symbol}: {str(e)}")
            return None
    
    def search_symbols(self, partial_name: str, limit: int = 10) -> pd.DataFrame:
        """
        Search for symbols matching partial name.
        
        Args:
            partial_name: Partial symbol name to search
            limit: Maximum results to return
            
        Returns:
            DataFrame with matching symbols
        """
        try:
            return self.instrument_manager.search_symbol(partial_name, limit)
        except Exception as e:
            logger.error(f"Error searching symbols for '{partial_name}': {str(e)}")
            return pd.DataFrame()


# Backward compatibility function
@execution_timer
def fetchDataZerodha(ticker_token: Union[int, str] = 408065, 
                    startDate: date = date(2021, 5, 9), 
                    endDate: date = date(2021, 6, 9), 
                    reqPerSec: int = 2) -> pd.DataFrame:
    """
    Backward compatibility function for existing code.
    
    Args:
        ticker_token: Instrument token or symbol
        startDate: Start date for data fetch
        endDate: End date for data fetch
        reqPerSec: Requests per second rate limit
        
    Returns:
        pd.DataFrame: Historical data
    """
    fetcher = ZerodhaDataFetcher(requests_per_second=reqPerSec)
    return fetcher.fetch_historical_data(ticker_token, startDate, endDate)

