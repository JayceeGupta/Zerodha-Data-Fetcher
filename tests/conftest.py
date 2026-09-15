from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@pytest.fixture
def sample_instrument_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Instrument_Token": 101,
                "Name": "INFY",
                "FullName": "Infosys Limited",
                "Exchange": "NSE",
            },
            {
                "Instrument_Token": 202,
                "Name": "INFY",
                "FullName": "Infosys Limited",
                "Exchange": "BSE",
            },
            {
                "Instrument_Token": 303,
                "Name": "RELIANCE",
                "FullName": "Reliance Industries",
                "Exchange": "NSE",
            },
            {
                "Instrument_Token": 404,
                "Name": "GOLD PETAL",
                "FullName": "Gold Petal",
                "Exchange": "MCX",
            },
        ]
    )


@pytest.fixture
def sample_mcx_futures_df() -> pd.DataFrame:
    """Raw-lowercase instrument frame (as load_instrument_data returns it).

    Mirrors the discovery data: GOLD with non-consecutive expiries (no
    Sep/Nov/Jan), CRUDEOIL consecutive monthly, prefix-collision families
    (GOLDM/GOLDPETAL/GOLDGUINEA, SILVER/SILVERM), MCX-OPT rows that must be
    filtered out, and equity rows to prove the stock path is untouched.
    """
    return pd.DataFrame(
        [
            # GOLD futures — non-consecutive months (Aug, Oct, Dec, Feb)
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
            {
                "instrument_token": 113,
                "tradingsymbol": "GOLD24DECFUT",
                "name": "GOLD",
                "exchange": "MCX",
                "expiry": "2024-12-05",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 112,
                "tradingsymbol": "GOLD24OCTFUT",
                "name": "GOLD",
                "exchange": "MCX",
                "expiry": "2024-10-04",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 114,
                "tradingsymbol": "GOLD25FEBFUT",
                "name": "GOLD",
                "exchange": "MCX",
                "expiry": "2025-02-05",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            # CRUDEOIL futures — consecutive months (Jul, Aug, Sep)
            {
                "instrument_token": 121,
                "tradingsymbol": "CRUDEOIL24JULFUT",
                "name": "CRUDEOIL",
                "exchange": "MCX",
                "expiry": "2024-07-19",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 122,
                "tradingsymbol": "CRUDEOIL24AUGFUT",
                "name": "CRUDEOIL",
                "exchange": "MCX",
                "expiry": "2024-08-19",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 123,
                "tradingsymbol": "CRUDEOIL24SEPFUT",
                "name": "CRUDEOIL",
                "exchange": "MCX",
                "expiry": "2024-09-19",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            # Prefix-collision families — distinct underlyings, must NOT match "GOLD"/"SILVER"
            {
                "instrument_token": 131,
                "tradingsymbol": "GOLDM24AUGFUT",
                "name": "GOLDM",
                "exchange": "MCX",
                "expiry": "2024-08-05",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 132,
                "tradingsymbol": "GOLDPETAL24AUGFUT",
                "name": "GOLDPETAL",
                "exchange": "MCX",
                "expiry": "2024-08-31",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 133,
                "tradingsymbol": "GOLDGUINEA24AUGFUT",
                "name": "GOLDGUINEA",
                "exchange": "MCX",
                "expiry": "2024-08-31",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 141,
                "tradingsymbol": "SILVER24SEPFUT",
                "name": "SILVER",
                "exchange": "MCX",
                "expiry": "2024-09-05",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            {
                "instrument_token": 142,
                "tradingsymbol": "SILVERM24AUGFUT",
                "name": "SILVERM",
                "exchange": "MCX",
                "expiry": "2024-08-30",
                "strike": 0,
                "lot_size": 1,
                "instrument_type": "FUT",
                "segment": "MCX-FUT",
            },
            # MCX-OPT rows — must be excluded even though name matches GOLD
            {
                "instrument_token": 151,
                "tradingsymbol": "GOLD24DEC70000CE",
                "name": "GOLD",
                "exchange": "MCX",
                "expiry": "2024-12-05",
                "strike": 70000,
                "lot_size": 1,
                "instrument_type": "CE",
                "segment": "MCX-OPT",
            },
            {
                "instrument_token": 152,
                "tradingsymbol": "GOLD24DEC70000PE",
                "name": "GOLD",
                "exchange": "MCX",
                "expiry": "2024-12-05",
                "strike": 70000,
                "lot_size": 1,
                "instrument_type": "PE",
                "segment": "MCX-OPT",
            },
            # Equity rows — stock path must be unaffected
            {
                "instrument_token": 101,
                "tradingsymbol": "INFY",
                "name": "Infosys Limited",
                "exchange": "NSE",
                "expiry": "",
                "strike": 0,
                "lot_size": 0,
                "instrument_type": "EQ",
                "segment": "NSE",
            },
            {
                "instrument_token": 303,
                "tradingsymbol": "RELIANCE",
                "name": "Reliance Industries",
                "exchange": "NSE",
                "expiry": "",
                "strike": 0,
                "lot_size": 0,
                "instrument_type": "EQ",
                "segment": "NSE",
            },
        ]
    )


@pytest.fixture
def fake_config_kwargs() -> Dict[str, str]:
    return {
        "user_id": "test_user",
        "password": "test_pass",
        "totp_secret": "test_totp",
        "user_type": "user_id",
        "base_url": "https://example.test",
        "login_url": "https://example.test/login",
        "two_fa_url": "https://example.test/twofa",
        "historical_url": "https://example.test/{token}/{timeframe}?user_id={userid}&from={current_date}&to={next_date}",
        "keyring_token_key": "test_token_key",
        "keyring_encryption_key": "test_encryption_key",
    }


@pytest.fixture
def dummy_chunk_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Timestamp": "2024-01-01T09:15:00+0530",
                "Open": 100.0,
                "High": 105.0,
                "Low": 99.5,
                "Close": 104.0,
                "Volume": 1000,
            },
            {
                "Timestamp": "2024-01-01T09:16:00+0530",
                "Open": 104.0,
                "High": 106.0,
                "Low": 103.0,
                "Close": 105.0,
                "Volume": 1200,
            },
        ]
    )


@pytest.fixture
def clear_zerodha_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "ZERODHA_USER_ID",
        "ZERODHA_PASSWORD",
        "ZERODHA_TYPE",
        "ZERODHA_TOTP_SECRET",
        "ZERODHA_BASE_URL",
        "ZERODHA_LOGIN_URL",
        "ZERODHA_2FA_URL",
        "ZERODHA_HISTORICAL_URL",
        "ZERODHA_KEYRING_TOKEN_KEY",
        "ZERODHA_KEYRING_ENCRYPTION_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


class FakeFuture:
    def __init__(
        self, result_value: Any = None, exception: Optional[BaseException] = None
    ):
        self._result_value = result_value
        self._exception = exception
        self.cancel_called = False

    def result(self) -> Any:
        if self._exception is not None:
            raise self._exception
        return self._result_value

    def cancel(self) -> bool:
        self.cancel_called = True
        return True


class FakeExecutor:
    def __init__(
        self,
        max_workers: Optional[int] = None,
        requests_per_second: Optional[int] = None,
        future_factory: Optional[Callable[[Any, tuple], FakeFuture]] = None,
        rate_limiter: Any = None,
    ):
        self.max_workers = max_workers
        self.requests_per_second = requests_per_second
        self.future_factory = future_factory
        self.rate_limiter = rate_limiter
        self.submitted_params = []
        self.shutdown_called = False

    def __enter__(self) -> "FakeExecutor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def submit(self, fn: Callable[[tuple], Any], params: tuple) -> FakeFuture:
        self.submitted_params.append(params)
        if self.future_factory is not None:
            return self.future_factory(fn, params)
        return FakeFuture(result_value=fn(params))

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self.shutdown_called = True


def fake_as_completed(
    future_to_params: Dict[FakeFuture, tuple],
) -> Iterable[FakeFuture]:
    return list(future_to_params.keys())


@pytest.fixture
def fetcher_factory(
    monkeypatch: pytest.MonkeyPatch, fake_config_kwargs: Dict[str, str]
):
    from zerodha_data_fetcher.core import data_fetcher as data_fetcher_module

    class FakeAuthManager:
        def __init__(self, token_expiry_hours: float, config):
            self.token_expiry_hours = token_expiry_hours
            self.config = config
            self.get_auth_token = lambda: "auth-token"
            self.invalidate_token = lambda: None

    monkeypatch.setattr(data_fetcher_module, "AuthenticationManager", FakeAuthManager)

    def _factory(**overrides):
        kwargs = {**fake_config_kwargs, **overrides}
        instrument_manager = kwargs.pop("instrument_manager", None)
        return data_fetcher_module.ZerodhaDataFetcher(
            instrument_manager=instrument_manager,
            **kwargs,
        )

    return _factory
