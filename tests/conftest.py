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
    def __init__(self, result_value: Any = None, exception: Optional[BaseException] = None):
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
    ):
        self.max_workers = max_workers
        self.requests_per_second = requests_per_second
        self.future_factory = future_factory
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


def fake_as_completed(future_to_params: Dict[FakeFuture, tuple]) -> Iterable[FakeFuture]:
    return list(future_to_params.keys())


@pytest.fixture
def fetcher_factory(monkeypatch: pytest.MonkeyPatch, fake_config_kwargs: Dict[str, str]):
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
