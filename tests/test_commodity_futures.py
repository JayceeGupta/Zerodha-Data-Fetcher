"""Phase 1 — loader column fix + get_futures_contracts query."""

import pandas as pd

from zerodha_data_fetcher.core.instrument_manager import ZerodhaInstrumentManager


def _patch_loader(monkeypatch, df: pd.DataFrame) -> None:
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: df,
    )


def test_get_futures_contracts_returns_gold_futures_sorted_by_expiry(
    monkeypatch, sample_mcx_futures_df
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    result = manager.get_futures_contracts("GOLD", include_expired=True)

    # Only the 4 GOLD FUT rows — no GOLDM/GOLDPETAL/GOLDGUINEA, no options.
    assert result["Name"].tolist() == [
        "GOLD24AUGFUT",
        "GOLD24OCTFUT",
        "GOLD24DECFUT",
        "GOLD25FEBFUT",
    ]
    assert result["Instrument_Token"].tolist() == [111, 112, 113, 114]


def test_get_futures_contracts_excludes_expired_relative_to_as_of(
    monkeypatch, sample_mcx_futures_df
):
    from datetime import date

    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    result = manager.get_futures_contracts("GOLD", as_of=date(2024, 11, 1))

    # Aug/Oct 2024 are past; Dec 2024 and Feb 2025 remain.
    assert result["Name"].tolist() == ["GOLD24DECFUT", "GOLD25FEBFUT"]


def test_get_futures_contracts_matches_underlying_exactly_not_prefix(
    monkeypatch, sample_mcx_futures_df
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    result = manager.get_futures_contracts("SILVER", include_expired=True)

    # SILVERM must not be swept in by a "SILVER" query.
    assert result["Name"].tolist() == ["SILVER24SEPFUT"]


def test_get_futures_contracts_excludes_options(monkeypatch, sample_mcx_futures_df):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    result = manager.get_futures_contracts("GOLD", include_expired=True)

    # No CE/PE (MCX-OPT) rows even though their name is GOLD.
    assert not result["InstrumentType"].isin(["CE", "PE"]).any()
    assert (result["Segment"] == "MCX-FUT").all()


def test_resolve_futures_contract_near_delegates_to_selector(
    monkeypatch, sample_mcx_futures_df
):
    from datetime import date

    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    contract = manager.resolve_futures_contract("GOLD", "near", as_of=date(2024, 11, 1))

    assert contract.tradingsymbol == "GOLD24DECFUT"
    assert contract.instrument_token == 113


def test_resolve_futures_contract_respects_underlying_exactly(
    monkeypatch, sample_mcx_futures_df
):
    from datetime import date

    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    contract = manager.resolve_futures_contract(
        "SILVER", "near", as_of=date(2024, 8, 1)
    )

    # SILVERM must never be returned for a SILVER query.
    assert contract.tradingsymbol == "SILVER24SEPFUT"


def test_resolve_futures_contract_unknown_underlying_returns_none(
    monkeypatch, sample_mcx_futures_df
):
    from datetime import date

    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    assert (
        manager.resolve_futures_contract("PLATINUM", "near", as_of=date(2024, 8, 1))
        is None
    )


def test_resolve_specific_contract_matches_named_month(
    monkeypatch, sample_mcx_futures_df
):
    _patch_loader(monkeypatch, sample_mcx_futures_df)
    manager = ZerodhaInstrumentManager()

    contract = manager.resolve_specific_contract("GOLD", 2024, 12)

    assert contract.tradingsymbol == "GOLD24DECFUT"
    assert contract.instrument_token == 113


def _write_csv(path, rows) -> str:
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def test_custom_path_csv_with_derivative_columns_preserves_them(tmp_path):
    csv_path = _write_csv(
        tmp_path / "instruments.csv",
        [
            {
                "instrument_token": 111,
                "tradingsymbol": "GOLD24AUGFUT",
                "name": "GOLD",
                "exchange": "MCX",
                "expiry": "2024-08-05",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
        ],
    )
    manager = ZerodhaInstrumentManager(instrument_id_path=csv_path)

    result = manager.get_futures_contracts("GOLD", include_expired=True)

    assert result["Name"].tolist() == ["GOLD24AUGFUT"]


def test_custom_path_csv_without_derivative_columns_degrades_gracefully(tmp_path):
    # Old 4-column CSV: stock path must still work; futures return empty.
    csv_path = _write_csv(
        tmp_path / "legacy.csv",
        [
            {
                "instrument_token": 101,
                "tradingsymbol": "INFY",
                "name": "Infosys",
                "exchange": "NSE",
            },
        ],
    )
    manager = ZerodhaInstrumentManager(instrument_id_path=csv_path)

    assert manager.resolve_symbol("INFY") == 101
    assert manager.get_futures_contracts("GOLD", include_expired=True).empty
