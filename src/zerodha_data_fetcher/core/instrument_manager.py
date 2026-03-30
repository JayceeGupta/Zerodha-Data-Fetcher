"""Instrument ID management for Zerodha symbols."""

import os
import logging
from typing import List, Optional

import pandas as pd

from ..utils.exceptions import ZerodhaAPIError
from ..utils.data_loader import load_instrument_data, download_instruments, get_cache_path

logger = logging.getLogger(__name__)


class ZerodhaInstrumentManager:
    """Manages Zerodha instrument IDs and symbol lookups."""

    EXCHANGE_PREFERENCE = ("NSE", "BSE")

    def __init__(self,
                 equity_scrip_path: Optional[str] = None,
                 commodity_scrip_path: Optional[str] = None,
                 instrument_id_path: Optional[str] = None,
                 cache_ttl_minutes: Optional[int] = None):
        self.equity_scrip_path = equity_scrip_path
        self.commodity_scrip_path = commodity_scrip_path
        self.instrument_id_path = instrument_id_path

        # Resolve TTL: param → env var → default (1440 = 24 h)
        if cache_ttl_minutes is not None:
            self.cache_ttl_minutes = cache_ttl_minutes
        else:
            env_ttl = os.getenv("ZERODHA_INSTRUMENT_CACHE_TTL")
            self.cache_ttl_minutes = int(env_ttl) if env_ttl is not None else 1440

        self._equity_stocks: Optional[List[str]] = None
        self._commodities: Optional[List[str]] = None
        self._instrument_data: Optional[pd.DataFrame] = None

        logger.info("Zerodha Instrument Manager initialized (cache TTL: %d min)", self.cache_ttl_minutes)
        if self.instrument_id_path:
            logger.info("Using custom instrument data path: %s", self.instrument_id_path)
        else:
            logger.info("Using cached/bundled instrument data")

    def _load_equity_stocks(self) -> List[str]:
        """Load equity stock list from Excel file."""
        if self._equity_stocks is None:
            if not self.equity_scrip_path or not os.path.exists(self.equity_scrip_path):
                logger.warning("Equity scrip list path not provided or file doesn't exist")
                return []

            try:
                df = pd.read_excel(self.equity_scrip_path)
                self._equity_stocks = df['Scrip Name'].to_list()
                logger.debug("Loaded %s stocks from equity scrip list", len(self._equity_stocks))
            except Exception as exc:
                logger.error("Failed to load equity scrip list: %s", exc)
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
                logger.debug("Loaded %s commodities from commodity scrip list", len(self._commodities))
            except Exception as exc:
                logger.error("Failed to load commodity scrip list: %s", exc)
                self._commodities = []

        return self._commodities

    def _load_instrument_data(self) -> pd.DataFrame:
        """Load Zerodha instrument ID data from CSV file."""
        if self._instrument_data is None:
            try:
                if self.instrument_id_path:
                    if not os.path.exists(self.instrument_id_path):
                        logger.error("Custom instrument ID path not found: %s", self.instrument_id_path)
                        raise ZerodhaAPIError("Custom Zerodha instrument ID file not found")

                    self._instrument_data = pd.read_csv(
                        self.instrument_id_path,
                        usecols=['instrument_token', 'tradingsymbol', 'name', 'exchange']
                    )
                else:
                    self._instrument_data = load_instrument_data(
                        cache_ttl_minutes=self.cache_ttl_minutes,
                    )

                expected_columns = ['instrument_token', 'tradingsymbol', 'name', 'exchange']
                available_columns = self._instrument_data.columns.tolist()
                if not all(col in available_columns for col in expected_columns):
                    logger.warning("Expected columns %s, found %s", expected_columns, available_columns)
                    if 'instrument_token' not in available_columns:
                        raise ZerodhaAPIError("Instrument data missing required 'instrument_token' column")

                column_mapping = {
                    'instrument_token': 'Instrument_Token',
                    'tradingsymbol': 'Name',
                    'name': 'FullName',
                    'exchange': 'Exchange'
                }
                existing_mapping = {k: v for k, v in column_mapping.items() if k in self._instrument_data.columns}
                self._instrument_data = self._instrument_data.rename(columns=existing_mapping)
                logger.debug("Loaded Zerodha instrument IDs with %s entries", len(self._instrument_data))
            except Exception as exc:
                logger.error("Failed to load instrument data: %s", exc)
                raise ZerodhaAPIError(f"Failed to load instrument data: {exc}")

        return self._instrument_data

    def refresh_instruments(self) -> bool:
        """
        Force-download the latest instrument data, ignoring TTL.

        After a successful download the in-memory cache is cleared so the
        next access reloads from the fresh file.

        Returns:
            ``True`` if the download succeeded, ``False`` otherwise.
        """
        dest = get_cache_path()
        ok = download_instruments(dest)
        if ok:
            # Reset so next _load_instrument_data() re-reads from disk
            self._instrument_data = None
            logger.info("Instrument data refreshed successfully.")
        return ok

    def _normalize_commodity_symbol(self, symbol: str) -> Optional[str]:
        """Normalize commodity lookup strings into the bundled data format."""
        parts = [part for part in str(symbol).strip().split() if part]
        if len(parts) < 2:
            logger.warning("Malformed commodity symbol: %s", symbol)
            return None
        return f"{parts[0]} {parts[-1].replace('-', ' ')}"

    def _select_preferred_equity_match(self, matches: pd.DataFrame, exchange: Optional[str] = None) -> pd.DataFrame:
        """Return the preferred exchange match for an equity symbol."""
        if matches.empty:
            return matches

        if exchange:
            filtered = matches[matches['Exchange'] == exchange.upper()]
            return filtered.head(1)

        for preferred_exchange in self.EXCHANGE_PREFERENCE:
            filtered = matches[matches['Exchange'] == preferred_exchange]
            if not filtered.empty:
                return filtered.head(1)

        return matches.head(1)

    def fetch_instrument_ids(self, is_stock: bool = True) -> pd.DataFrame:
        """Fetch Zerodha instrument IDs for stock or commodity symbols."""
        logger.info("Fetching instrument IDs for %s", 'stocks' if is_stock else 'commodities')

        instrument_data = self._load_instrument_data()
        rows = []

        if is_stock:
            for symbol in self._load_equity_stocks():
                normalized_symbol = str(symbol).strip().upper()
                matches = instrument_data[instrument_data['Name'] == normalized_symbol]
                result = self._select_preferred_equity_match(matches)
                if result.empty:
                    logger.warning("No matching instrument ID found for stock: %s", symbol)
                else:
                    rows.append(result)
        else:
            for symbol in self._load_commodities():
                normalized_symbol = self._normalize_commodity_symbol(str(symbol))
                if not normalized_symbol:
                    continue
                result = instrument_data[instrument_data['Name'].astype(str).str.strip() == normalized_symbol]
                if result.empty:
                    logger.warning("No matching instrument ID found for commodity: %s", normalized_symbol)
                else:
                    rows.append(result)

        final_df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=instrument_data.columns)
        if 'Name' in final_df.columns:
            final_df['Name'] = final_df['Name'].astype(str).str.strip()
        logger.info("Found %s matching instruments", len(final_df))
        return final_df

    def get_instrument_token(self, symbol: str, is_stock: bool = True, exchange: Optional[str] = None) -> Optional[int]:
        """Get instrument token for a specific symbol."""
        try:
            instrument_data = self._load_instrument_data()

            if is_stock:
                normalized_symbol = str(symbol).strip().upper()
                matches = instrument_data[instrument_data['Name'] == normalized_symbol]
                result = self._select_preferred_equity_match(matches, exchange=exchange)
            else:
                normalized_symbol = self._normalize_commodity_symbol(symbol)
                if not normalized_symbol:
                    return None
                result = instrument_data[instrument_data['Name'].astype(str).str.strip() == normalized_symbol]

            if result.empty:
                logger.warning("No instrument token found for symbol: %s", symbol)
                return None

            token = result.iloc[0]['Instrument_Token']
            logger.debug("Found instrument token %s for symbol %s", token, symbol)
            return int(token)
        except Exception as exc:
            logger.error("Error getting instrument token for %s: %s", symbol, exc)
            return None

    def search_symbol(self, partial_name: str, limit: int = 10, exchange: Optional[str] = None) -> pd.DataFrame:
        """Search for symbols containing the partial name."""
        try:
            instrument_data = self._load_instrument_data().copy()
            search_term = str(partial_name).strip()
            mask = instrument_data['Name'].astype(str).str.contains(search_term, case=False, na=False, regex=False)
            results = instrument_data[mask]
            if exchange:
                results = results[results['Exchange'] == exchange.upper()]

            exact_matches = results['Name'].astype(str).str.upper() == search_term.upper()
            results = pd.concat([results[exact_matches], results[~exact_matches]], ignore_index=True)
            logger.debug("Found %s symbols matching '%s'", len(results.head(limit)), partial_name)
            return results.head(limit)
        except Exception as exc:
            logger.error("Error searching for symbol '%s': %s", partial_name, exc)
            return pd.DataFrame()

    def validate_symbol(self, symbol: str, is_stock: bool = True, exchange: Optional[str] = None) -> bool:
        """Validate if a symbol exists in the instrument data."""
        token = self.get_instrument_token(symbol, is_stock=is_stock, exchange=exchange)
        return token is not None


def fetchZerodhaID(stock: bool,
                   equity_scrip_path: Optional[str] = None,
                   commodity_scrip_path: Optional[str] = None,
                   instrument_id_path: Optional[str] = None) -> pd.DataFrame:
    """Backward compatibility function for existing code."""
    manager = ZerodhaInstrumentManager(
        equity_scrip_path=equity_scrip_path,
        commodity_scrip_path=commodity_scrip_path,
        instrument_id_path=instrument_id_path
    )
    return manager.fetch_instrument_ids(is_stock=stock)
