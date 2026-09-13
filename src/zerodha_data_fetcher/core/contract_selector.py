"""Pure contract-selection logic for futures (no I/O, no manager wiring).

Given a DataFrame of futures rows for a *single underlying* (the output of
:meth:`ZerodhaInstrumentManager.get_futures_contracts` with
``include_expired=True``), pick a contract by selector:

- ``near``       — earliest contract expiring on/after the roll cutoff
- ``near_next``  — the contract immediately after ``near`` by expiry
- ``near_prev``  — the contract immediately before ``near`` by expiry
                   (the previous *listed* contract, never calendar-month math)
- specific       — a named ``(year, month)`` matched on parsed expiry

The functions here are deliberately free of any network or file access so
they can be unit-tested in isolation.  Freshness/staleness *policy* (warn/
error/refresh) lives in the manager; this module only reports the facts.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

import logging

import pandas as pd

logger = logging.getLogger(__name__)

FORWARD_SELECTORS = ("near", "near_next")
_ALL_ROLL_SELECTORS = ("near", "near_next", "near_prev")


@dataclass(frozen=True)
class ResolvedContract:
    """A single resolved futures contract plus its selection audit trail."""

    underlying: str  # FullName, e.g. "GOLD"
    tradingsymbol: str  # Name, e.g. "GOLD24DECFUT"
    instrument_token: int
    expiry: date
    segment: str  # "MCX-FUT"
    exchange: str  # "MCX"
    selector: str  # "near" | "near_prev" | "near_next" | "specific"
    stale: bool = False
    newest_available_expiry: Optional[date] = None


def _sorted_contracts(contracts: pd.DataFrame) -> Tuple[pd.DataFrame, List[date]]:
    """Return (frame sorted ascending by parsed expiry, list of expiry dates).

    Rows with an unparseable ``Expiry`` are dropped (logged at debug level).
    """
    if contracts is None or contracts.empty or "Expiry" not in contracts.columns:
        return contracts.iloc[0:0] if contracts is not None else pd.DataFrame(), []

    parsed = pd.to_datetime(contracts["Expiry"], errors="coerce")
    bad = parsed.isna()
    if bad.any():
        logger.debug(
            "Dropping %d contract row(s) with unparseable expiry.", int(bad.sum())
        )
    frame = contracts[~bad].copy()
    parsed = parsed[~bad]
    order = parsed.argsort(kind="stable")
    frame = frame.iloc[order.to_numpy()].reset_index(drop=True)
    expiries = [d.date() for d in parsed.iloc[order.to_numpy()]]
    return frame, expiries


def _to_contract(row: pd.Series, expiry: date, selector: str) -> ResolvedContract:
    return ResolvedContract(
        underlying=str(row["FullName"]),
        tradingsymbol=str(row["Name"]),
        instrument_token=int(row["Instrument_Token"]),
        expiry=expiry,
        segment=str(row.get("Segment", "")),
        exchange=str(row.get("Exchange", "")),
        selector=selector,
    )


def select_contract(
    contracts: pd.DataFrame,
    selector: str,
    *,
    as_of: Optional[date] = None,
    roll_offset_days: int = 0,
) -> Optional[ResolvedContract]:
    """Resolve a near / near_next / near_prev contract by expiry order.

    Returns ``None`` when the requested position does not exist (e.g.
    ``near`` on an all-expired frame, ``near_next`` past the last listed
    contract, ``near_prev`` when ``near`` is already the earliest).
    """
    if selector not in _ALL_ROLL_SELECTORS:
        raise ValueError(
            "Unknown selector %r; expected one of %s" % (selector, _ALL_ROLL_SELECTORS)
        )

    frame, expiries = _sorted_contracts(contracts)
    if not expiries:
        return None

    cutoff = (as_of or date.today()) + timedelta(days=roll_offset_days)

    # split = index of the first contract expiring on/after the cutoff (near).
    split = next((i for i, e in enumerate(expiries) if e >= cutoff), len(expiries))

    if selector == "near":
        idx = split
    elif selector == "near_next":
        idx = split + 1
    else:  # near_prev
        idx = split - 1

    if idx < 0 or idx >= len(expiries):
        return None

    return _to_contract(frame.iloc[idx], expiries[idx], selector)


def select_specific_contract(
    contracts: pd.DataFrame,
    year: int,
    month: int,
) -> Optional[ResolvedContract]:
    """Resolve a specific ``(year, month)`` contract by parsed expiry.

    Matches on the parsed expiry's year+month rather than string-building a
    tradingsymbol.  If more than one row expires in the same month, the
    earliest is returned and a warning is logged.  Returns ``None`` if no
    contract expires in that month.
    """
    frame, expiries = _sorted_contracts(contracts)
    hits = [i for i, e in enumerate(expiries) if e.year == year and e.month == month]
    if not hits:
        return None
    if len(hits) > 1:
        logger.warning(
            "Multiple contracts expire in %04d-%02d; returning the earliest.",
            year,
            month,
        )
    idx = hits[0]
    return _to_contract(frame.iloc[idx], expiries[idx], "specific")
