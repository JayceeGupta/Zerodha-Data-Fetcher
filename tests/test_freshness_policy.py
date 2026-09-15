"""Phase 3 — on_stale freshness policy for forward selectors."""

import logging
from datetime import date

import pytest

from zerodha_data_fetcher.core.instrument_manager import ZerodhaInstrumentManager
from zerodha_data_fetcher.utils.exceptions import StaleInstrumentDataError

# Every GOLD expiry in the fixture is <= 2025-02-05, so this as_of makes the
# file "stale for near-month" (no contract expiring on/after the cutoff).
STALE_AS_OF = date(2025, 6, 1)
FRESH_AS_OF = date(2024, 11, 1)


def _patch_loader(monkeypatch, df) -> None:
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: df,
    )


def test_warn_policy_returns_best_guess_flagged_stale(
    monkeypatch, sample_mcx_futures_df, caplog
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()  # default on_stale="warn"

    with caplog.at_level(logging.WARNING):
        contract = manager.resolve_futures_contract("GOLD", "near", as_of=STALE_AS_OF)

    # Best guess = most recent listed contract, flagged stale.
    assert contract.tradingsymbol == "GOLD25FEBFUT"
    assert contract.stale is True
    assert contract.newest_available_expiry == date(2025, 2, 5)
    assert any("stale" in r.message.lower() for r in caplog.records)


def test_error_policy_raises(monkeypatch, sample_mcx_futures_df):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    with pytest.raises(StaleInstrumentDataError) as exc:
        manager.resolve_futures_contract(
            "GOLD", "near", as_of=STALE_AS_OF, on_stale="error"
        )
    assert "2025-02-05" in str(exc.value)


def test_refresh_policy_refreshes_once_then_resolves(
    monkeypatch, sample_mcx_futures_df
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    fresh = sample_mcx_futures_df.copy()
    fresh.loc[fresh["tradingsymbol"] == "GOLD25FEBFUT", "expiry"] = "2025-08-05"
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1
        _patch_loader(monkeypatch, fresh)
        manager._instrument_data = None  # force reload from the fresh source
        return True

    monkeypatch.setattr(manager, "refresh_instruments", fake_refresh)

    contract = manager.resolve_futures_contract(
        "GOLD", "near", as_of=STALE_AS_OF, on_stale="refresh"
    )

    assert calls["n"] == 1
    assert contract.tradingsymbol == "GOLD25FEBFUT"
    assert contract.stale is False


def test_refresh_policy_degrades_to_warn_when_still_stale(
    monkeypatch, sample_mcx_futures_df, caplog
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1
        manager._instrument_data = None  # reloads the same still-stale frame
        return True

    monkeypatch.setattr(manager, "refresh_instruments", fake_refresh)

    with caplog.at_level(logging.WARNING):
        contract = manager.resolve_futures_contract(
            "GOLD", "near", as_of=STALE_AS_OF, on_stale="refresh"
        )

    assert calls["n"] == 1  # refreshed exactly once, no loop
    assert contract.stale is True
    assert any("stale" in r.message.lower() for r in caplog.records)


def test_ignore_policy_returns_strict_result_without_warning(
    monkeypatch, sample_mcx_futures_df, caplog
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    with caplog.at_level(logging.WARNING):
        contract = manager.resolve_futures_contract(
            "GOLD", "near", as_of=STALE_AS_OF, on_stale="ignore"
        )

    # Strict near on an all-expired file is None; ignore stays silent.
    assert contract is None
    assert not any("stale" in r.message.lower() for r in caplog.records)


def test_fresh_file_is_not_flagged_stale(monkeypatch, sample_mcx_futures_df):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    contract = manager.resolve_futures_contract(
        "GOLD", "near", as_of=FRESH_AS_OF, on_stale="error"
    )

    assert contract.tradingsymbol == "GOLD24DECFUT"
    assert contract.stale is False


def test_near_prev_exempt_from_stale_policy(monkeypatch, sample_mcx_futures_df):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    # near_prev is a backward-looking selector; even on a stale-for-near file
    # and error policy it must not raise.
    contract = manager.resolve_futures_contract(
        "GOLD", "near_prev", as_of=STALE_AS_OF, on_stale="error"
    )
    assert contract is not None


def test_specific_exempt_from_stale_policy(monkeypatch, sample_mcx_futures_df):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    # resolve_specific_contract never applies the stale policy.
    contract = manager.resolve_specific_contract("GOLD", 2024, 12)
    assert contract.tradingsymbol == "GOLD24DECFUT"


def test_unknown_on_stale_value_raises_value_error(monkeypatch, sample_mcx_futures_df):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    with pytest.raises(ValueError):
        manager.resolve_futures_contract(
            "GOLD", "near", as_of=STALE_AS_OF, on_stale="bogus"
        )


def test_instance_default_on_stale_overridable_per_call(
    monkeypatch, sample_mcx_futures_df
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager(on_stale="error")

    # Instance default raises...
    with pytest.raises(StaleInstrumentDataError):
        manager.resolve_futures_contract("GOLD", "near", as_of=STALE_AS_OF)

    # ...but a per-call value overrides it to warn (returns best guess).
    contract = manager.resolve_futures_contract(
        "GOLD", "near", as_of=STALE_AS_OF, on_stale="warn"
    )
    assert contract.stale is True
