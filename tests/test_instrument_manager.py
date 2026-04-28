import pandas as pd

from zerodha_data_fetcher.core.instrument_manager import ZerodhaInstrumentManager
from zerodha_data_fetcher.utils import data_loader as data_loader_module


def test_get_instrument_token_returns_stock_token(monkeypatch, sample_instrument_df):
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

    assert manager.get_instrument_token("INFY") == 101


def test_get_instrument_token_prefers_explicit_exchange(
    monkeypatch, sample_instrument_df
):
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

    assert manager.get_instrument_token("INFY", exchange="BSE") == 202


def test_get_instrument_token_returns_none_for_unknown_symbol(
    monkeypatch, sample_instrument_df
):
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

    assert manager.get_instrument_token("UNKNOWN") is None


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


def test_fetch_instrument_ids_for_equity_uses_loaded_symbols(
    monkeypatch, sample_instrument_df
):
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
    monkeypatch.setattr(
        manager, "_load_equity_stocks", lambda: ["INFY", "RELIANCE", "MISSING"]
    )

    results = manager.fetch_instrument_ids(is_stock=True)

    assert results["Name"].tolist() == ["INFY", "RELIANCE"]


def test_normalize_commodity_symbol_basic_case():
    manager = ZerodhaInstrumentManager()

    assert manager._normalize_commodity_symbol("GOLD petal") == "GOLD petal"


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
    manager.get_instrument_token("INFY")

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
