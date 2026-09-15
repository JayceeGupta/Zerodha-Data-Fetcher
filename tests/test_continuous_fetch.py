"""Phase 5 — fetch_futures_continuous (enumerate range → fetch → stitch)."""

from datetime import date

import pandas as pd


def _contracts_frame():
    # Two GOLD contracts; front-month roll on each expiry.
    return pd.DataFrame(
        [
            {
                "Instrument_Token": 111,
                "Name": "GOLD24AUGFUT",
                "FullName": "GOLD",
                "Expiry": "2024-08-31",
                "Segment": "MCX-FUT",
                "Exchange": "MCX",
                "InstrumentType": "FUT",
            },
            {
                "Instrument_Token": 112,
                "Name": "GOLD24SEPFUT",
                "FullName": "GOLD",
                "Expiry": "2024-09-30",
                "Segment": "MCX-FUT",
                "Exchange": "MCX",
                "InstrumentType": "FUT",
            },
        ]
    )


def _seg(dates, closes):
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1] * len(closes),
        }
    )


def _patch(fetcher, monkeypatch):
    monkeypatch.setattr(
        fetcher.instrument_manager,
        "get_futures_contracts",
        lambda *a, **k: _contracts_frame(),
    )
    frames = {
        111: _seg(["2024-08-15", "2024-08-31", "2024-09-15"], [100, 110, 108]),
        112: _seg(["2024-08-31", "2024-09-15", "2024-09-30"], [120, 130, 140]),
    }
    monkeypatch.setattr(
        fetcher, "fetch_historical_data", lambda token, *a, **k: frames[token]
    )


def test_continuous_fetch_stitches_front_month(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory(requests_per_second=4)
    _patch(fetcher, monkeypatch)

    result = fetcher.fetch_futures_continuous(
        "GOLD", date(2024, 8, 1), date(2024, 9, 30), adjust="none"
    )

    # Windowed by expiry: A up to Aug 31, then B afterward.
    assert result["Close"].tolist() == [100, 110, 130, 140]


def test_continuous_fetch_applies_adjustment(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory(requests_per_second=4)
    _patch(fetcher, monkeypatch)

    result = fetcher.fetch_futures_continuous(
        "GOLD", date(2024, 8, 1), date(2024, 9, 30), adjust="diff"
    )

    # diff back-adjust: newest anchor unchanged (130,140); older shifted +20.
    assert result["Close"].tolist() == [120, 130, 130, 140]


def test_continuous_fetch_empty_when_no_contracts(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory(requests_per_second=4)
    monkeypatch.setattr(
        fetcher.instrument_manager,
        "get_futures_contracts",
        lambda *a, **k: _contracts_frame().iloc[0:0],
    )

    result = fetcher.fetch_futures_continuous(
        "GOLD", date(2024, 8, 1), date(2024, 9, 30)
    )
    assert result.empty
