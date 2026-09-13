"""Phase 2 — pure contract-selection logic (no manager/fetcher wiring)."""

from datetime import date

import pandas as pd

import pytest

from zerodha_data_fetcher.core.contract_selector import (
    ResolvedContract,
    select_contract,
    select_specific_contract,
)


def _gold_frame() -> pd.DataFrame:
    """GOLD futures in the manager's output format, non-consecutive months.

    Aug, Oct, Dec 2024, Feb 2025 — no Sep/Nov/Jan, so near_prev/near_next
    cannot be faked with calendar-month arithmetic.
    """
    return pd.DataFrame(
        [
            {
                "Instrument_Token": 111,
                "Name": "GOLD24AUGFUT",
                "FullName": "GOLD",
                "Expiry": "2024-08-05",
                "Segment": "MCX-FUT",
                "Exchange": "MCX",
                "InstrumentType": "FUT",
            },
            {
                "Instrument_Token": 112,
                "Name": "GOLD24OCTFUT",
                "FullName": "GOLD",
                "Expiry": "2024-10-04",
                "Segment": "MCX-FUT",
                "Exchange": "MCX",
                "InstrumentType": "FUT",
            },
            {
                "Instrument_Token": 113,
                "Name": "GOLD24DECFUT",
                "FullName": "GOLD",
                "Expiry": "2024-12-05",
                "Segment": "MCX-FUT",
                "Exchange": "MCX",
                "InstrumentType": "FUT",
            },
            {
                "Instrument_Token": 114,
                "Name": "GOLD25FEBFUT",
                "FullName": "GOLD",
                "Expiry": "2025-02-05",
                "Segment": "MCX-FUT",
                "Exchange": "MCX",
                "InstrumentType": "FUT",
            },
        ]
    )


def test_near_returns_earliest_contract_expiring_on_or_after_cutoff():
    result = select_contract(_gold_frame(), "near", as_of=date(2024, 11, 1))

    assert isinstance(result, ResolvedContract)
    assert result.tradingsymbol == "GOLD24DECFUT"
    assert result.instrument_token == 113
    assert result.expiry == date(2024, 12, 5)
    assert result.selector == "near"


def test_near_next_returns_second_future_contract():
    result = select_contract(_gold_frame(), "near_next", as_of=date(2024, 11, 1))

    assert result.tradingsymbol == "GOLD25FEBFUT"


def test_near_next_past_last_listed_contract_returns_none():
    # as_of after the last expiry: no future contract, hence no "next".
    assert select_contract(_gold_frame(), "near_next", as_of=date(2025, 3, 1)) is None


def test_near_prev_returns_previous_listed_contract_not_calendar_month():
    # near is Dec 2024; the previous LISTED contract is Oct 2024 (not Nov —
    # that month is not listed). Proves list-index stepping, not month math.
    result = select_contract(_gold_frame(), "near_prev", as_of=date(2024, 11, 1))

    assert result.tradingsymbol == "GOLD24OCTFUT"
    assert result.expiry == date(2024, 10, 4)


def test_near_prev_returns_none_when_near_is_earliest():
    # as_of before every expiry: near is the first contract, so no prior one.
    assert select_contract(_gold_frame(), "near_prev", as_of=date(2024, 1, 1)) is None


def test_roll_offset_days_rolls_near_early():
    # as_of is 3 days before the Dec expiry; without offset near is Dec, but
    # a 5-day roll offset pushes the cutoff past Dec so near becomes Feb.
    as_of = date(2024, 12, 2)
    assert (
        select_contract(_gold_frame(), "near", as_of=as_of).tradingsymbol
        == "GOLD24DECFUT"
    )
    rolled = select_contract(_gold_frame(), "near", as_of=as_of, roll_offset_days=5)
    assert rolled.tradingsymbol == "GOLD25FEBFUT"


def test_specific_returns_named_month_contract():
    result = select_specific_contract(_gold_frame(), 2024, 12)

    assert result.tradingsymbol == "GOLD24DECFUT"
    assert result.selector == "specific"


def test_specific_returns_none_for_unlisted_month():
    # November is a skipped month for GOLD.
    assert select_specific_contract(_gold_frame(), 2024, 11) is None


def test_empty_frame_returns_none():
    empty = _gold_frame().iloc[0:0]
    assert select_contract(empty, "near", as_of=date(2024, 11, 1)) is None
    assert select_specific_contract(empty, 2024, 12) is None


def test_unparseable_expiry_row_is_dropped():
    frame = _gold_frame()
    frame.loc[len(frame)] = {
        "Instrument_Token": 999,
        "Name": "GOLDBADFUT",
        "FullName": "GOLD",
        "Expiry": "not-a-date",
        "Segment": "MCX-FUT",
        "Exchange": "MCX",
        "InstrumentType": "FUT",
    }
    result = select_contract(frame, "near", as_of=date(2025, 3, 1))
    # The only "future" candidate would be the bad row; it is dropped → None.
    assert result is None


def test_unknown_selector_raises_value_error():
    with pytest.raises(ValueError):
        select_contract(_gold_frame(), "front_month", as_of=date(2024, 11, 1))
