"""Instrument ID management for Zerodha symbols."""

import os
import logging
from dataclasses import replace
from datetime import date
from typing import List, Optional

import pandas as pd

from ..utils.config import Config
from ..utils.exceptions import StaleInstrumentDataError, ZerodhaAPIError
from ..utils.data_loader import (
    load_instrument_data,
    download_instruments,
    get_cache_path,
)
from .contract_selector import (
    ResolvedContract,
    SelectionResult,
    resolve as resolve_selection,
    select_specific_contract,
)

# Allowed values for the near-month freshness policy (see resolve_futures_contract).
ON_STALE_POLICIES = ("ignore", "warn", "error", "refresh")

logger = logging.getLogger(__name__)


class ZerodhaInstrumentManager:
    """Manages Zerodha instrument IDs and symbol lookups.

    Provides methods to resolve trading symbols to Zerodha instrument
    tokens, search for instruments by partial name, and validate whether
    a symbol exists.  Instrument data is loaded lazily on first access
    and cached in memory for the lifetime of the instance.
    """

    # When a symbol is listed on multiple exchanges, prefer NSE over BSE
    # because NSE generally has higher liquidity and tighter spreads.
    EXCHANGE_PREFERENCE = ("NSE", "BSE")

    def __init__(
        self,
        equity_scrip_path: Optional[str] = None,
        commodity_scrip_path: Optional[str] = None,
        instrument_id_path: Optional[str] = None,
        cache_ttl_minutes: Optional[int] = None,
        on_stale: str = "warn",
    ):
        """
        Initialize the instrument manager.

        Data is loaded lazily: the instrument CSV is not read until a
        method actually needs it, then cached in ``_instrument_data`` for
        subsequent lookups.

        Args:
            equity_scrip_path: Path to an Excel file containing equity
                scrip names (column ``'Scrip Name'``).  Optional — only
                needed when using :meth:`fetch_instrument_ids`.
            commodity_scrip_path: Path to an Excel file containing
                commodity scrip names (same column layout).  Optional.
            instrument_id_path: Path to a custom CSV with Zerodha
                instrument data.  When omitted, the library uses a
                cached/bundled copy of the official Kite instruments CSV.
            cache_ttl_minutes: How long (in minutes) the cached
                instrument CSV is considered fresh before re-downloading.
                Defaults to ``ZERODHA_INSTRUMENT_CACHE_TTL`` env var,
                then 1440 (24 hours).
        """
        self.equity_scrip_path = equity_scrip_path
        self.commodity_scrip_path = commodity_scrip_path
        self.instrument_id_path = instrument_id_path
        self.on_stale = self._validate_on_stale(on_stale)

        # Resolve TTL: param → env var → default (1440 = 24 h)
        if cache_ttl_minutes is not None:
            self.cache_ttl_minutes = cache_ttl_minutes
        else:
            self.cache_ttl_minutes = Config.resolve_instrument_cache_ttl_minutes()

        self._equity_stocks: Optional[List[str]] = None
        self._commodities: Optional[List[str]] = None
        self._instrument_data: Optional[pd.DataFrame] = None

        logger.info(
            "Zerodha Instrument Manager initialized (cache TTL: %d min)",
            self.cache_ttl_minutes,
        )
        if self.instrument_id_path:
            logger.info(
                "Using custom instrument data path: %s", self.instrument_id_path
            )
        else:
            logger.info("Using cached/bundled instrument data")

    def _load_equity_stocks(self) -> List[str]:
        """Load equity stock symbols from an NSE/BSE scrip master Excel file.

        Reads the ``'Scrip Name'`` column — the standard column header
        used by exchange-provided scrip master spreadsheets.  The result
        is cached in ``_equity_stocks`` so the file is read at most once.
        """
        if self._equity_stocks is None:
            if not self.equity_scrip_path or not os.path.exists(self.equity_scrip_path):
                logger.warning(
                    "Equity scrip list path not provided or file doesn't exist"
                )
                return []

            try:
                df = pd.read_excel(self.equity_scrip_path)
                self._equity_stocks = df["Scrip Name"].to_list()
                logger.debug(
                    "Loaded %s stocks from equity scrip list", len(self._equity_stocks)
                )
            except Exception as exc:
                logger.error("Failed to load equity scrip list: %s", exc)
                self._equity_stocks = []

        return self._equity_stocks

    def _load_commodities(self) -> List[str]:
        """Load commodity symbols from an exchange scrip master Excel file.

        Uses the same ``'Scrip Name'`` column as equity scrip masters.
        The result is cached in ``_commodities`` so the file is read at
        most once.
        """
        if self._commodities is None:
            if not self.commodity_scrip_path or not os.path.exists(
                self.commodity_scrip_path
            ):
                logger.warning(
                    "Commodity scrip list path not provided or file doesn't exist"
                )
                return []

            try:
                df = pd.read_excel(self.commodity_scrip_path)
                self._commodities = df["Scrip Name"].to_list()
                logger.debug(
                    "Loaded %s commodities from commodity scrip list",
                    len(self._commodities),
                )
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
                        logger.error(
                            "Custom instrument ID path not found: %s",
                            self.instrument_id_path,
                        )
                        raise ZerodhaAPIError(
                            "Custom Zerodha instrument ID file not found"
                        )

                    # Keep the equity columns plus the derivative-aware
                    # columns needed for futures selection, but only those
                    # actually present — older/custom CSVs that lack expiry/
                    # segment/instrument_type must still load (they simply
                    # won't support futures resolution).
                    desired_columns = [
                        "instrument_token",
                        "tradingsymbol",
                        "name",
                        "exchange",
                        "expiry",
                        "segment",
                        "instrument_type",
                    ]
                    self._instrument_data = pd.read_csv(
                        self.instrument_id_path,
                        usecols=lambda col: col in desired_columns,
                    )
                else:
                    self._instrument_data = load_instrument_data(
                        cache_ttl_minutes=self.cache_ttl_minutes,
                    )

                expected_columns = [
                    "instrument_token",
                    "tradingsymbol",
                    "name",
                    "exchange",
                ]
                available_columns = self._instrument_data.columns.tolist()
                if not all(col in available_columns for col in expected_columns):
                    logger.warning(
                        "Expected columns %s, found %s",
                        expected_columns,
                        available_columns,
                    )
                    if "instrument_token" not in available_columns:
                        raise ZerodhaAPIError(
                            "Instrument data missing required 'instrument_token' column"
                        )

                # Rename Zerodha API column names to the shorter internal
                # names used throughout this class.  The Kite instruments
                # CSV uses lowercase snake_case; we map to PascalCase for
                # clarity in downstream DataFrame operations.
                column_mapping = {
                    "instrument_token": "Instrument_Token",
                    "tradingsymbol": "Name",
                    "name": "FullName",
                    "exchange": "Exchange",
                    # Derivative-aware columns (commodity futures selection).
                    # The underlying/grouping key is FullName (raw ``name``),
                    # NOT Name (raw ``tradingsymbol``).
                    "expiry": "Expiry",
                    "segment": "Segment",
                    "instrument_type": "InstrumentType",
                }
                existing_mapping = {
                    k: v
                    for k, v in column_mapping.items()
                    if k in self._instrument_data.columns
                }
                self._instrument_data = self._instrument_data.rename(
                    columns=existing_mapping
                )
                logger.debug(
                    "Loaded Zerodha instrument IDs with %s entries",
                    len(self._instrument_data),
                )
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

    # Columns required for futures-contract selection. Absent on custom
    # CSVs that predate derivative support — treated as "no futures here".
    _FUTURES_COLUMNS = ("FullName", "Expiry", "Segment", "InstrumentType")

    def get_futures_contracts(
        self,
        underlying: str,
        *,
        exchange: str = "MCX",
        segment: str = "MCX-FUT",
        include_expired: bool = False,
        as_of: Optional[date] = None,
    ) -> pd.DataFrame:
        """Return all futures contracts for one *underlying*, sorted by expiry.

        Matches ``FullName`` (the underlying, e.g. ``GOLD``) on **exact
        equality** — never substring — so prefix families like ``GOLDM`` /
        ``GOLDPETAL`` are not swept in.  Filtered to ``Exchange``/``Segment``
        and ``InstrumentType == "FUT"``.  Rows are sorted ascending by parsed
        ``Expiry``; unparseable expiries are dropped.  When *include_expired*
        is ``False`` (default), contracts whose expiry is before *as_of*
        (default ``date.today()``) are excluded.

        Returns an empty DataFrame when the source lacks the derivative
        columns (e.g. a custom 4-column CSV) or when nothing matches.
        """
        data = self._load_instrument_data()

        missing = [c for c in self._FUTURES_COLUMNS if c not in data.columns]
        if missing:
            logger.warning(
                "Instrument data missing futures columns %s; "
                "no futures contracts available.",
                missing,
            )
            return data.iloc[0:0]

        target = str(underlying).strip().upper()
        mask = (
            (data["Exchange"] == exchange.strip().upper())
            & (data["Segment"] == segment.strip().upper())
            & (data["InstrumentType"] == "FUT")
            & (data["FullName"].astype(str).str.strip().str.upper() == target)
        )
        matches = data[mask].copy()
        if matches.empty:
            return matches

        parsed = pd.to_datetime(matches["Expiry"], errors="coerce")
        unparseable = parsed.isna()
        if unparseable.any():
            logger.debug(
                "Dropping %d %s futures row(s) with unparseable expiry.",
                int(unparseable.sum()),
                target,
            )
        matches = matches[~unparseable]
        parsed = parsed[~unparseable]
        matches = matches.assign(_expiry_dt=parsed).sort_values("_expiry_dt")

        if not include_expired:
            cutoff = as_of or date.today()
            keep = matches["_expiry_dt"].dt.date >= cutoff
            matches = matches[keep]

        return matches.drop(columns="_expiry_dt").reset_index(drop=True)

    @staticmethod
    def _validate_on_stale(on_stale: str) -> str:
        if on_stale not in ON_STALE_POLICIES:
            raise ValueError(
                "on_stale must be one of %s, got %r" % (ON_STALE_POLICIES, on_stale)
            )
        return on_stale

    def resolve_futures_contract(
        self,
        underlying: str,
        selector: str = "near",
        *,
        exchange: str = "MCX",
        segment: str = "MCX-FUT",
        as_of: Optional[date] = None,
        roll_offset_days: int = 0,
        on_stale: Optional[str] = None,
    ) -> Optional[ResolvedContract]:
        """Resolve the near / previous-listed / next-listed futures contract.

        Loads the full futures list for *underlying* (including expired
        contracts, so ``near_prev`` can look back) and delegates to the pure
        selector.  Returns ``None`` when the requested contract does not exist.

        For forward selectors (``near``/``near_next``) the *on_stale* policy
        governs what happens when the loaded file has no contract expiring on
        or after the roll cutoff (``None`` → the instance default):

        - ``ignore``  : return the strict result (``None``) silently.
        - ``warn``    : log a warning and return the most recent listed
          contract as a best-guess, flagged ``stale=True``.
        - ``error``   : raise :class:`StaleInstrumentDataError`.
        - ``refresh`` : force-download once, reload, and re-resolve; if still
          stale, degrade to ``warn``.
        """
        policy = self._validate_on_stale(on_stale or self.on_stale)

        result = self._resolve_selection(
            underlying,
            selector,
            exchange=exchange,
            segment=segment,
            as_of=as_of,
            roll_offset_days=roll_offset_days,
        )

        if not result.is_stale:
            return result.contract

        if policy == "refresh":
            if self.refresh_instruments():
                refreshed = self._resolve_selection(
                    underlying,
                    selector,
                    exchange=exchange,
                    segment=segment,
                    as_of=as_of,
                    roll_offset_days=roll_offset_days,
                )
                if not refreshed.is_stale:
                    return refreshed.contract
                result = refreshed
            policy = "warn"  # refresh didn't help → degrade, do not loop

        if policy == "ignore":
            return result.contract

        message = (
            "Instrument file is stale for near-month %s: newest available "
            "expiry %s is before the roll cutoff (as_of=%s). "
            "Call refresh_instruments() for current contracts."
            % (underlying, result.newest_available_expiry, as_of or date.today())
        )
        if policy == "error":
            raise StaleInstrumentDataError(message)

        # warn
        logger.warning(message)
        if result.latest_listed is None:
            return None
        return replace(
            result.latest_listed,
            stale=True,
            newest_available_expiry=result.newest_available_expiry,
        )

    def _resolve_selection(
        self,
        underlying: str,
        selector: str,
        *,
        exchange: str,
        segment: str,
        as_of: Optional[date],
        roll_offset_days: int,
    ) -> SelectionResult:
        contracts = self.get_futures_contracts(
            underlying,
            exchange=exchange,
            segment=segment,
            include_expired=True,
        )
        return resolve_selection(
            contracts,
            selector,
            as_of=as_of,
            roll_offset_days=roll_offset_days,
        )

    def resolve_specific_contract(
        self,
        underlying: str,
        year: int,
        month: int,
        *,
        exchange: str = "MCX",
        segment: str = "MCX-FUT",
    ) -> Optional[ResolvedContract]:
        """Resolve a specific ``(year, month)`` futures contract by expiry."""
        contracts = self.get_futures_contracts(
            underlying,
            exchange=exchange,
            segment=segment,
            include_expired=True,
        )
        return select_specific_contract(contracts, year, month)

    def _normalize_commodity_symbol(self, symbol: str) -> Optional[str]:
        """Normalize commodity lookup strings into the bundled data format."""
        parts = [part for part in str(symbol).strip().split() if part]
        if len(parts) < 2:
            logger.warning("Malformed commodity symbol: %s", symbol)
            return None
        return f"{parts[0]} {parts[-1].replace('-', ' ')}"

    def _select_preferred_equity_match(
        self, matches: pd.DataFrame, exchange: Optional[str] = None
    ) -> pd.DataFrame:
        """Return the single best match for an equity symbol.

        Selection logic:
          1. If *exchange* is explicitly provided, filter to that exchange.
          2. Otherwise walk :attr:`EXCHANGE_PREFERENCE` (NSE first, then
             BSE) and return the first hit.
          3. If no preferred exchange matches, return the first row as a
             fallback.
        """
        if matches.empty:
            return matches

        if exchange:
            filtered = matches[matches["Exchange"] == exchange.upper()]
            return filtered.head(1)

        for preferred_exchange in self.EXCHANGE_PREFERENCE:
            filtered = matches[matches["Exchange"] == preferred_exchange]
            if not filtered.empty:
                return filtered.head(1)

        return matches.head(1)

    def fetch_instrument_ids(self, is_stock: bool = True) -> pd.DataFrame:
        """Fetch Zerodha instrument IDs for stock or commodity symbols."""
        logger.info(
            "Fetching instrument IDs for %s", "stocks" if is_stock else "commodities"
        )

        instrument_data = self._load_instrument_data()
        rows = []

        if is_stock:
            for symbol in self._load_equity_stocks():
                normalized_symbol = str(symbol).strip().upper()
                matches = instrument_data[instrument_data["Name"] == normalized_symbol]
                result = self._select_preferred_equity_match(matches)
                if result.empty:
                    logger.warning(
                        "No matching instrument ID found for stock: %s", symbol
                    )
                else:
                    rows.append(result)
        else:
            for symbol in self._load_commodities():
                normalized_symbol = self._normalize_commodity_symbol(str(symbol))
                if not normalized_symbol:
                    continue
                result = instrument_data[
                    instrument_data["Name"].astype(str).str.strip() == normalized_symbol
                ]
                if result.empty:
                    logger.warning(
                        "No matching instrument ID found for commodity: %s",
                        normalized_symbol,
                    )
                else:
                    rows.append(result)

        final_df = (
            pd.concat(rows, ignore_index=True)
            if rows
            else pd.DataFrame(columns=instrument_data.columns)
        )
        if "Name" in final_df.columns:
            final_df["Name"] = final_df["Name"].astype(str).str.strip()
        logger.info("Found %s matching instruments", len(final_df))
        return final_df

    def get_instrument_token(
        self, symbol: str, is_stock: bool = True, exchange: Optional[str] = None
    ) -> Optional[int]:
        """Get instrument token for a specific symbol."""
        try:
            instrument_data = self._load_instrument_data()

            if is_stock:
                normalized_symbol = str(symbol).strip().upper()
                matches = instrument_data[instrument_data["Name"] == normalized_symbol]
                result = self._select_preferred_equity_match(matches, exchange=exchange)
            else:
                normalized_symbol = self._normalize_commodity_symbol(symbol)
                if not normalized_symbol:
                    return None
                result = instrument_data[
                    instrument_data["Name"].astype(str).str.strip() == normalized_symbol
                ]

            if result.empty:
                logger.warning("No instrument token found for symbol: %s", symbol)
                return None

            token = result.iloc[0]["Instrument_Token"]
            logger.debug("Found instrument token %s for symbol %s", token, symbol)
            return int(token)
        except Exception as exc:
            logger.error("Error getting instrument token for %s: %s", symbol, exc)
            return None

    def search_symbol(
        self, partial_name: str, limit: int = 10, exchange: Optional[str] = None
    ) -> pd.DataFrame:
        """Search for symbols containing the partial name."""
        try:
            instrument_data = self._load_instrument_data().copy()
            search_term = str(partial_name).strip()
            mask = (
                instrument_data["Name"]
                .astype(str)
                .str.contains(search_term, case=False, na=False, regex=False)
            )
            results = instrument_data[mask]
            if exchange:
                results = results[results["Exchange"] == exchange.upper()]

            exact_matches = (
                results["Name"].astype(str).str.upper() == search_term.upper()
            )
            results = pd.concat(
                [results[exact_matches], results[~exact_matches]], ignore_index=True
            )
            logger.debug(
                "Found %s symbols matching '%s'", len(results.head(limit)), partial_name
            )
            return results.head(limit)
        except Exception as exc:
            logger.error("Error searching for symbol '%s': %s", partial_name, exc)
            return pd.DataFrame()

    def validate_symbol(
        self, symbol: str, is_stock: bool = True, exchange: Optional[str] = None
    ) -> bool:
        """Validate if a symbol exists in the instrument data."""
        token = self.get_instrument_token(symbol, is_stock=is_stock, exchange=exchange)
        return token is not None


# ---------------------------------------------------------------------------
# Legacy API — preserved for backward compatibility only.
# New code should use ZerodhaInstrumentManager directly.
# ---------------------------------------------------------------------------


def fetchZerodhaID(
    stock: bool,
    equity_scrip_path: Optional[str] = None,
    commodity_scrip_path: Optional[str] = None,
    instrument_id_path: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch instrument IDs for a list of symbols.

    .. deprecated::
        Use :class:`ZerodhaInstrumentManager` and its
        :meth:`~ZerodhaInstrumentManager.fetch_instrument_ids` method
        instead.  This function is retained only so that existing callers
        continue to work without changes.

    Args:
        stock: ``True`` for equity stocks, ``False`` for commodities.
        equity_scrip_path: Path to the equity scrip master Excel file.
        commodity_scrip_path: Path to the commodity scrip master Excel file.
        instrument_id_path: Path to a custom Zerodha instruments CSV.

    Returns:
        pd.DataFrame: Matching instrument data.
    """
    import warnings

    warnings.warn(
        "fetchZerodhaID() is deprecated. "
        "Use ZerodhaInstrumentManager().fetch_instrument_ids() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    manager = ZerodhaInstrumentManager(
        equity_scrip_path=equity_scrip_path,
        commodity_scrip_path=commodity_scrip_path,
        instrument_id_path=instrument_id_path,
    )
    return manager.fetch_instrument_ids(is_stock=stock)
