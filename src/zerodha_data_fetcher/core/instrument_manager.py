"""Instrument ID management for Zerodha symbols."""

import os
import logging
from typing import List, Optional, Union

import pandas as pd

from ..utils.exceptions import ZerodhaAPIError
from ..utils.data_loader import load_instrument_data, get_default_instrument_path

logger = logging.getLogger(__name__)


class ZerodhaInstrumentManager:
    """Manages Zerodha instrument IDs and symbol lookups."""
    
    def __init__(self, 
                 equity_scrip_path: Optional[str] = None,
                 commodity_scrip_path: Optional[str] = None,
                 instrument_id_path: Optional[str] = None):
        """
        Initialize the instrument manager.
        
        Args:
            equity_scrip_path: Path to equity scrip list Excel file
            commodity_scrip_path: Path to commodity scrip list Excel file  
            instrument_id_path: Path to Zerodha instrument ID CSV file.
                               If None, uses bundled instrument data.
        """
        self.equity_scrip_path = equity_scrip_path
        self.commodity_scrip_path = commodity_scrip_path
        self.instrument_id_path = instrument_id_path
        
        # Initialize data containers
        self._equity_stocks: Optional[List[str]] = None
        self._commodities: Optional[List[str]] = None
        self._instrument_data: Optional[pd.DataFrame] = None
        
        logger.info("Zerodha Instrument Manager initialized")
        
        # Log which instrument data source will be used
        if self.instrument_id_path:
            logger.info(f"Using custom instrument data path: {self.instrument_id_path}")
        else:
            logger.info("Using bundled instrument data")
    
    def _load_equity_stocks(self) -> List[str]:
        """Load equity stock list from Excel file."""
        if self._equity_stocks is None:
            if not self.equity_scrip_path or not os.path.exists(self.equity_scrip_path):
                logger.warning("Equity scrip list path not provided or file doesn't exist")
                return []
                
            try:
                df = pd.read_excel(self.equity_scrip_path)
                self._equity_stocks = df['Scrip Name'].to_list()
                logger.debug(f"Loaded {len(self._equity_stocks)} stocks from equity scrip list")
            except Exception as e:
                logger.error(f"Failed to load equity scrip list: {str(e)}")
                self._equity_stocks = []
                
        return self._equity_stocks
    
    def _load_commodities(self) -> List[str]:
        """Load commodity list from Excel file."""
        if self._commodities is None:
            if not self.commodity_scrip_path or not os.path.exists(self.commodity_scrip_path):
                logger.warning("Commodity scrip list path not provided or file doesn't exist")
                return []
                
            try:
                df = pd.read_excel(self.commodity_scrip_path)
                self._commodities = df['Scrip Name'].to_list()
                logger.debug(f"Loaded {len(self._commodities)} commodities from commodity scrip list")
            except Exception as e:
                logger.error(f"Failed to load commodity scrip list: {str(e)}")
                self._commodities = []
                
        return self._commodities
    
    def _load_instrument_data(self) -> pd.DataFrame:
        """Load Zerodha instrument ID data from CSV file."""
        if self._instrument_data is None:
            try:
                # Use the data loader utility
                if self.instrument_id_path:
                    # Custom path provided
                    if not os.path.exists(self.instrument_id_path):
                        logger.error(f"Custom instrument ID path not found: {self.instrument_id_path}")
                        raise ZerodhaAPIError("Custom Zerodha instrument ID file not found")
                    
                    logger.debug(f"Loading instrument data from custom path: {self.instrument_id_path}")
                    self._instrument_data = pd.read_csv(
                        self.instrument_id_path,
                        usecols=['instrument_token', 'tradingsymbol', 'name', 'exchange']
                    )
                else:
                    # Use bundled data
                    logger.debug("Loading instrument data from bundled package data")
                    self._instrument_data = load_instrument_data()
                    
                    # Check if the bundled data has the expected columns
                    expected_columns = ['instrument_token', 'tradingsymbol', 'name', 'exchange']
                    available_columns = self._instrument_data.columns.tolist()
                    
                    # Try to use available columns or raise error
                    if not all(col in available_columns for col in expected_columns):
                        logger.warning(f"Expected columns {expected_columns}, found {available_columns}")
                        # Try to use the data as-is if it has some required columns
                        if 'instrument_token' not in available_columns:
                            raise ZerodhaAPIError("Instrument data missing required 'instrument_token' column")
                
                # Rename columns for consistency
                column_mapping = {
                    'instrument_token': 'Instrument_Token',
                    'tradingsymbol': 'Name', 
                    'name': 'FullName',
                    'exchange': 'Exchange'
                }
                
                # Only rename columns that exist
                existing_mapping = {k: v for k, v in column_mapping.items() if k in self._instrument_data.columns}
                self._instrument_data = self._instrument_data.rename(columns=existing_mapping)
                
                logger.debug(f"Loaded Zerodha instrument IDs with {len(self._instrument_data)} entries")
                logger.debug(f"Available columns: {self._instrument_data.columns.tolist()}")
                
            except Exception as e:
                logger.error(f"Failed to load instrument data: {str(e)}")
                raise ZerodhaAPIError(f"Failed to load instrument data: {str(e)}")
                
        return self._instrument_data
    
    def fetch_instrument_ids(self, is_stock: bool = True) -> pd.DataFrame:
        """
        Fetches the Zerodha instrument IDs for the specified stock or commodity symbols.

        Args:
            is_stock (bool): If True, fetch instrument IDs for stocks, otherwise fetch for commodities.

        Returns:
            pd.DataFrame: A DataFrame containing the instrument IDs.
        """
        logger.info(f"Fetching instrument IDs for {'stocks' if is_stock else 'commodities'}")
        
        instrument_data = self._load_instrument_data()
        final_df = pd.DataFrame()
        
        if is_stock:
            stocks = self._load_equity_stocks()
            logger.debug(f"Processing {len(stocks)} stocks")
            
            for symbol in stocks:
                result = instrument_data[
                    (instrument_data['Name'] == symbol) & 
                    (instrument_data['Exchange'] == 'NSE')
                ]
                if len(result) == 0:
                    logger.warning(f"No matching instrument ID found for stock: {symbol}")
                final_df = pd.concat([final_df, result], ignore_index=True)
        
        else:  # Commodities
            commodities = self._load_commodities()
            logger.debug(f"Processing {len(commodities)} commodities")
            
            for symbol in commodities:
                symbol = str(symbol)
                original_symbol = symbol
                # Process commodity symbol format
                symbol = symbol.split(" ")[0] + " " + symbol.split(" ")[-1].replace("-", " ")    
                logger.debug(f"Looking up commodity symbol: {symbol} (original: {original_symbol})")
                
                result = instrument_data[instrument_data['Name'].str.strip() == symbol]
                if len(result) == 0:
                    logger.warning(f"No matching instrument ID found for commodity: {symbol}")
                final_df = pd.concat([final_df, result], ignore_index=True)
            
            # Clean up commodity names
            final_df['Name'] = final_df['Name'].apply(lambda x: x.strip())
        
        logger.info(f"Found {len(final_df)} matching instruments")
        return final_df
    
    def get_instrument_token(self, symbol: str, is_stock: bool = True) -> Optional[int]:
        """
        Get instrument token for a specific symbol.
        
        Args:
            symbol: Trading symbol to lookup
            is_stock: Whether to search in stocks (True) or commodities (False)
            
        Returns:
            int: Instrument token if found, None otherwise
        """
        try:
            instrument_data = self._load_instrument_data()
            
            if is_stock:
                result = instrument_data[
                    (instrument_data['Name'] == symbol.upper()) & 
                    (instrument_data['Exchange'] == 'NSE')
                ]
            else:
                # Process commodity symbol format
                processed_symbol = symbol.split(" ")[0] + " " + symbol.split(" ")[-1].replace("-", " ")
                result = instrument_data[instrument_data['Name'].str.strip() == processed_symbol]
            
            if len(result) > 0:
                token = result.iloc[0]['Instrument_Token']
                logger.debug(f"Found instrument token {token} for symbol {symbol}")
                return int(token)
            else:
                logger.warning(f"No instrument token found for symbol: {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting instrument token for {symbol}: {str(e)}")
            return None
    
    def search_symbol(self, partial_name: str, limit: int = 10) -> pd.DataFrame:
        """
        Search for symbols containing the partial name.
        
        Args:
            partial_name: Partial symbol name to search for
            limit: Maximum number of results to return
            
        Returns:
            pd.DataFrame: DataFrame with matching symbols
        """
        try:
            instrument_data = self._load_instrument_data()
            
            # Case-insensitive search
            mask = instrument_data['Name'].str.contains(partial_name, case=False, na=False)
            results = instrument_data[mask].head(limit)
            
            logger.debug(f"Found {len(results)} symbols matching '{partial_name}'")
            return results
            
        except Exception as e:
            logger.error(f"Error searching for symbol '{partial_name}': {str(e)}")
            return pd.DataFrame()
    
    def validate_symbol(self, symbol: str, is_stock: bool = True) -> bool:
        """
        Validate if a symbol exists in the instrument data.
        
        Args:
            symbol: Symbol to validate
            is_stock: Whether to validate as stock or commodity
            
        Returns:
            bool: True if symbol exists, False otherwise
        """
        token = self.get_instrument_token(symbol, is_stock)
        return token is not None


# Backward compatibility function
def fetchZerodhaID(stock: bool, 
                   equity_scrip_path: Optional[str] = None,
                   commodity_scrip_path: Optional[str] = None,
                   instrument_id_path: Optional[str] = None) -> pd.DataFrame:
    """
    Backward compatibility function for existing code.
    
    Args:
        stock: If True, fetch instrument IDs for stocks, otherwise for commodities
        equity_scrip_path: Path to equity scrip list
        commodity_scrip_path: Path to commodity scrip list
        instrument_id_path: Path to instrument ID file (if None, uses bundled data)
        
    Returns:
        pd.DataFrame: Instrument IDs DataFrame
    """
    manager = ZerodhaInstrumentManager(
        equity_scrip_path=equity_scrip_path,
        commodity_scrip_path=commodity_scrip_path,
        instrument_id_path=instrument_id_path
    )
    return manager.fetch_instrument_ids(is_stock=stock)
