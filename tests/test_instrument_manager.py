import pandas as pd
import pytest

from zerodha_data_fetcher.core.instrument_manager import ZerodhaInstrumentManager
from zerodha_data_fetcher.utils import data_loader as data_loader_module


def _as_raw_columns(df):
    return df.rename(
        columns={
            "Instrument_Token": "instrument_token",
            "Name": "tradingsymbol",
            "FullName": "name",
            "Exchange": "exchange",
        }
    )


@pytest.fixture
def manager_with_sample(monkeypatch, sample_instrument_df):
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: _as_raw_columns(sample_instrument_df),
    )
    return ZerodhaInstrumentManager()


@pytest.fixture
def manager_with_mcx(monkeypatch, sample_mcx_futures_df):
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: sample_mcx_futures_df,
    )
    return ZerodhaInstrumentManager()


def test_resolve_symbol_exact_futures_tradingsymbol(manager_with_mcx):
    # A specific contract's tradingsymbol is unambiguous and must resolve.
    assert manager_with_mcx.resolve_symbol("GOLD24AUGFUT") == 111


def test_resolve_symbol_underlying_does_not_pick_a_futures_expiry(manager_with_mcx):
    # "GOLD" is only a futures underlying here; it must NOT silently resolve
    # to an arbitrary expiry token (111-114) via full-name/substring matching.
    assert manager_with_mcx.resolve_symbol("GOLD") is None


def test_validate_symbol_false_for_futures_underlying(manager_with_mcx):
    assert manager_with_mcx.validate_symbol("GOLD") is False


def test_resolve_symbol_passes_through_integer_token(manager_with_sample):
    assert manager_with_sample.resolve_symbol(408065) == 408065


def test_resolve_symbol_treats_numeric_string_as_token(manager_with_sample):
    assert manager_with_sample.resolve_symbol("202") == 202


def test_resolve_symbol_matches_tradingsymbol_with_nse_preference(manager_with_sample):
    # INFY exists on both NSE (101) and BSE (202); NSE wins by default.
    assert manager_with_sample.resolve_symbol("infy") == 101


def test_resolve_symbol_honours_exchange_prefix(manager_with_sample):
    assert manager_with_sample.resolve_symbol("BSE:INFY") == 202


def test_resolve_symbol_honours_exchange_argument(manager_with_sample):
    assert manager_with_sample.resolve_symbol("INFY", exchange="BSE") == 202


def test_resolve_symbol_falls_back_to_full_name(manager_with_sample):
    assert manager_with_sample.resolve_symbol("Reliance Industries") == 303


def test_resolve_symbol_best_effort_substring(manager_with_sample):
    assert manager_with_sample.resolve_symbol("RELIAN") == 303


def test_resolve_symbol_returns_none_for_unknown(manager_with_sample):
    assert manager_with_sample.resolve_symbol("ZZZ-NOT-A-SYMBOL") is None


def test_resolve_symbol_returns_none_for_blank(manager_with_sample):
    assert manager_with_sample.resolve_symbol("   ") is None


def test_search_symbol_returns_matches_with_limit(monkeypatch, sample_instrument_df):
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: sample_instrument_df.rename(
            columns={
                "Instrument_Token": "instrument_token",
                "Name": "tradingsymbol",
                "FullName": "name",
                "Exchange": "exchange",
            }
        ),
    )
    manager = ZerodhaInstrumentManager()

    results = manager.search_symbol("INF", limit=1)

    assert len(results) == 1
    assert results.iloc[0]["Name"] == "INFY"


def test_search_symbol_orders_exact_match_first(monkeypatch, sample_instrument_df):
    instrument_df = pd.concat(
        [
            sample_instrument_df.rename(
                columns={
                    "Instrument_Token": "instrument_token",
                    "Name": "tradingsymbol",
                    "FullName": "name",
                    "Exchange": "exchange",
                }
            ),
            pd.DataFrame(
                [
                    {
                        "instrument_token": 505,
                        "tradingsymbol": "INF",
                        "name": "INF Corporation",
                        "exchange": "NSE",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: instrument_df,
    )
    manager = ZerodhaInstrumentManager()

    results = manager.search_symbol("INF", limit=3)

    assert results.iloc[0]["Name"] == "INF"


def test_validate_symbol_true_for_existing_symbol(monkeypatch, sample_instrument_df):
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: sample_instrument_df.rename(
            columns={
                "Instrument_Token": "instrument_token",
                "Name": "tradingsymbol",
                "FullName": "name",
                "Exchange": "exchange",
            }
        ),
    )
    manager = ZerodhaInstrumentManager()

    assert manager.validate_symbol("RELIANCE") is True


def test_validate_symbol_false_for_missing_symbol(monkeypatch, sample_instrument_df):
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        lambda **kwargs: sample_instrument_df.rename(
            columns={
                "Instrument_Token": "instrument_token",
                "Name": "tradingsymbol",
                "FullName": "name",
                "Exchange": "exchange",
            }
        ),
    )
    manager = ZerodhaInstrumentManager()

    assert manager.validate_symbol("MISSING") is False


def test_instrument_manager_uses_shared_ttl_resolution(
    monkeypatch, sample_instrument_df
):
    captured = {}

    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.Config.resolve_instrument_cache_ttl_minutes",
        classmethod(lambda cls, env_value=None: 77),
    )

    def fake_load_instrument_data(**kwargs):
        captured["cache_ttl_minutes"] = kwargs["cache_ttl_minutes"]
        return sample_instrument_df.rename(
            columns={
                "Instrument_Token": "instrument_token",
                "Name": "tradingsymbol",
                "FullName": "name",
                "Exchange": "exchange",
            }
        )

    monkeypatch.setattr(
        "zerodha_data_fetcher.core.instrument_manager.load_instrument_data",
        fake_load_instrument_data,
    )

    manager = ZerodhaInstrumentManager()
    manager.resolve_symbol("INFY")

    assert manager.cache_ttl_minutes == 77
    assert captured["cache_ttl_minutes"] == 77


def test_data_loader_uses_shared_ttl_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(
        data_loader_module.Config,
        "resolve_instrument_cache_ttl_minutes",
        classmethod(lambda cls, env_value=None: 33),
    )
    monkeypatch.setattr(
        data_loader_module, "get_cache_path", lambda filename: tmp_path / filename
    )
    monkeypatch.setattr(data_loader_module, "get_cache_age_minutes", lambda path: 0)

    expected = pd.DataFrame([{"instrument_token": 1}])
    monkeypatch.setattr(data_loader_module.pd, "read_csv", lambda path: expected)

    result = data_loader_module.load_instrument_data()

    assert result.equals(expected)
