"""Phase 3 — fetch_futures_historical_data (resolution → existing fetch path)."""

from datetime import date

import pandas as pd
import pytest

from zerodha_data_fetcher.core.contract_selector import ResolvedContract


def _contract(token: int = 113) -> ResolvedContract:
    return ResolvedContract(
        underlying="GOLD",
        tradingsymbol="GOLD24DECFUT",
        instrument_token=token,
        expiry=date(2024, 12, 5),
        segment="MCX-FUT",
        exchange="MCX",
        selector="near",
    )


def test_fetch_futures_resolves_then_delegates_with_token(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    captured = {}

    monkeypatch.setattr(
        fetcher.instrument_manager,
        "resolve_futures_contract",
        lambda *a, **k: _contract(113),
    )
    dummy = pd.DataFrame({"Date": [], "Time": []})

    def fake_fetch(ticker_token, start_date, end_date, **kwargs):
        captured["token"] = ticker_token
        return dummy

    monkeypatch.setattr(fetcher, "fetch_historical_data", fake_fetch)

    result = fetcher.fetch_futures_historical_data(
        "GOLD", date(2024, 1, 1), date(2024, 12, 1), selector="near"
    )

    assert captured["token"] == 113
    assert result is dummy


def test_fetch_futures_raises_when_contract_unresolved(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        fetcher.instrument_manager,
        "resolve_futures_contract",
        lambda *a, **k: None,
    )

    with pytest.raises(ValueError):
        fetcher.fetch_futures_historical_data(
            "GOLD", date(2024, 1, 1), date(2024, 12, 1), selector="near"
        )


def test_fetch_futures_specific_requires_year_and_month(fetcher_factory):
    fetcher = fetcher_factory()

    with pytest.raises(ValueError):
        fetcher.fetch_futures_historical_data(
            "GOLD", date(2024, 1, 1), date(2024, 12, 1), selector="specific"
        )


def test_fetch_futures_specific_delegates_with_token(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    captured = {}

    monkeypatch.setattr(
        fetcher.instrument_manager,
        "resolve_specific_contract",
        lambda *a, **k: _contract(113),
    )
    monkeypatch.setattr(
        fetcher,
        "fetch_historical_data",
        lambda ticker_token, *a, **k: captured.setdefault("token", ticker_token)
        or pd.DataFrame(),
    )

    fetcher.fetch_futures_historical_data(
        "GOLD",
        date(2024, 1, 1),
        date(2024, 12, 1),
        selector="specific",
        year=2024,
        month=12,
    )

    assert captured["token"] == 113
