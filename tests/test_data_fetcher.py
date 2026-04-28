import json
import logging
from datetime import date

import pandas as pd
import pytest
import requests
from dateutil.relativedelta import relativedelta

from zerodha_data_fetcher.core import data_fetcher as data_fetcher_module
from zerodha_data_fetcher.utils import helpers as helpers_module
from zerodha_data_fetcher.utils.config import Config
from zerodha_data_fetcher.utils.exceptions import (
    AuthenticationError,
    DataFetchError,
    InvalidTickerError,
)


class ResponseStub:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


@pytest.fixture(autouse=True)
def disable_retry_sleep(monkeypatch):
    monkeypatch.setattr(helpers_module.time, "sleep", lambda _seconds: None)


def test_init_clamps_requests_per_second_to_minimum(fetcher_factory):
    fetcher = fetcher_factory(requests_per_second=0)

    assert fetcher.requests_per_second == Config.MIN_REQUESTS_PER_SECOND


def test_init_clamps_requests_per_second_to_maximum(fetcher_factory):
    fetcher = fetcher_factory(requests_per_second=Config.MAX_REQUESTS_PER_SECOND + 5)

    assert fetcher.requests_per_second == Config.MAX_REQUESTS_PER_SECOND


def test_init_uses_supplied_instrument_manager(fetcher_factory):
    instrument_manager = object()

    fetcher = fetcher_factory(instrument_manager=instrument_manager)

    assert fetcher.instrument_manager is instrument_manager


def test_init_defaults_chunk_failure_mode_to_strict(fetcher_factory):
    fetcher = fetcher_factory()

    assert fetcher.chunk_failure_mode == "strict"


def test_init_rejects_invalid_chunk_failure_mode(fetcher_factory):
    with pytest.raises(ValueError, match="chunk_failure_mode"):
        fetcher_factory(chunk_failure_mode="invalid")


def test_validate_ticker_token_returns_true_when_chunk_fetch_succeeds(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "token")
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda _params: pd.DataFrame())

    assert fetcher._validate_ticker_token(12345) is True


def test_validate_ticker_token_returns_false_for_invalid_token_error(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "token")

    def raise_invalid(_params):
        raise Exception('Response: {"status":"error","message":"invalid token"}')

    monkeypatch.setattr(fetcher, "_fetch_data_chunk", raise_invalid)

    assert fetcher._validate_ticker_token(12345) is False


def test_validate_ticker_token_invalidates_and_retries_for_token_exception(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    calls = {"count": 0}
    invalidations = {"count": 0}
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "token")
    monkeypatch.setattr(
        fetcher.auth_manager,
        "invalidate_token",
        lambda: invalidations.__setitem__("count", invalidations["count"] + 1),
    )

    def flaky_chunk(_params):
        calls["count"] += 1
        if calls["count"] == 1:
            raise Exception(
                'Response: {"status":"error","error_type":"TokenException","message":"expired"}'
            )
        return pd.DataFrame()

    monkeypatch.setattr(fetcher, "_fetch_data_chunk", flaky_chunk)

    assert fetcher._validate_ticker_token(12345) is True
    assert invalidations["count"] == 1
    assert calls["count"] == 2


def test_validate_ticker_token_returns_false_after_second_token_exception(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    calls = {"count": 0}
    invalidations = {"count": 0}
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "token")
    monkeypatch.setattr(
        fetcher.auth_manager,
        "invalidate_token",
        lambda: invalidations.__setitem__("count", invalidations["count"] + 1),
    )

    def always_expired(_params):
        calls["count"] += 1
        raise Exception(
            'Response: {"status":"error","error_type":"TokenException","message":"expired"}'
        )

    monkeypatch.setattr(fetcher, "_fetch_data_chunk", always_expired)

    assert fetcher._validate_ticker_token(12345) is False
    assert invalidations["count"] == 1
    assert calls["count"] == 2


def test_validate_ticker_token_returns_false_on_unparseable_error(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "token")
    monkeypatch.setattr(
        fetcher,
        "_fetch_data_chunk",
        lambda _params: (_ for _ in ()).throw(Exception("boom")),
    )

    assert fetcher._validate_ticker_token(12345) is False


def test_resolve_ticker_token_accepts_valid_integer_token(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher, "_validate_ticker_token", lambda token: token == 123)

    assert fetcher._resolve_ticker_token(123) == 123


def test_resolve_ticker_token_raises_for_invalid_integer_token(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher, "_validate_ticker_token", lambda _token: False)

    with pytest.raises(InvalidTickerError, match="Invalid ticker token: 123"):
        fetcher._resolve_ticker_token(123)


def test_resolve_ticker_token_resolves_stock_symbol(fetcher_factory):
    class InstrumentManagerStub:
        def get_instrument_token(self, symbol, is_stock=True, exchange=None):
            if symbol == "INFY" and is_stock:
                return 111
            return None

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    assert fetcher._resolve_ticker_token("infy") == 111


def test_resolve_ticker_token_falls_back_to_commodity_lookup(fetcher_factory):
    class InstrumentManagerStub:
        def get_instrument_token(self, symbol, is_stock=True, exchange=None):
            if symbol == "gold petal" and not is_stock:
                return 444
            return None

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    assert fetcher._resolve_ticker_token("gold petal") == 444


def test_resolve_ticker_token_raises_when_symbol_missing(fetcher_factory):
    class InstrumentManagerStub:
        def get_instrument_token(self, symbol, is_stock=True, exchange=None):
            return None

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    with pytest.raises(InvalidTickerError, match="Symbol not found"):
        fetcher._resolve_ticker_token("missing")


def test_resolve_ticker_token_raises_for_invalid_type(fetcher_factory):
    fetcher = fetcher_factory()

    with pytest.raises(InvalidTickerError, match="Invalid ticker token type"):
        fetcher._resolve_ticker_token(3.14)


def test_fetch_data_chunk_formats_url_and_returns_dataframe(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return ResponseStub(
            status_code=200,
            json_data={
                "data": {
                    "candles": [["2024-01-01T09:15:00+0530", 1, 2, 0.5, 1.5, 10, 99]]
                }
            },
        )

    monkeypatch.setattr(data_fetcher_module.requests, "get", fake_get)
    params = (
        date(2024, 1, 1),
        date(2024, 1, 2),
        "test_user",
        "minute",
        321,
        {"Authorization": "enctoken token"},
    )

    df = fetcher._fetch_data_chunk(params)

    assert "https://example.test/321/minute?user_id=test_user" in captured["url"]
    assert captured["headers"] == {"Authorization": "enctoken token"}
    assert captured["timeout"] == Config.REQUEST_TIMEOUT
    assert list(df.columns) == ["Timestamp", "Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 1


def test_fetch_data_chunk_returns_empty_dataframe_when_no_candles(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        data_fetcher_module.requests,
        "get",
        lambda *args, **kwargs: ResponseStub(
            status_code=200, json_data={"data": {"candles": []}}
        ),
    )

    df = fetcher._fetch_data_chunk(
        (
            date(2024, 1, 1),
            date(2024, 1, 2),
            "user",
            "minute",
            321,
            {"Authorization": "token"},
        )
    )

    assert df.empty is True


def test_fetch_data_chunk_raises_for_non_200_response(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        return ResponseStub(status_code=500, text="server error")

    monkeypatch.setattr(data_fetcher_module.requests, "get", fake_get)

    with pytest.raises(DataFetchError, match="status 500"):
        fetcher._fetch_data_chunk(
            (
                date(2024, 1, 1),
                date(2024, 1, 2),
                "user",
                "minute",
                321,
                {"Authorization": "token"},
            )
        )

    assert calls["count"] == 4


def test_fetch_data_chunk_raises_for_invalid_response_structure(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        data_fetcher_module.requests,
        "get",
        lambda *args, **kwargs: ResponseStub(
            status_code=200, json_data={"unexpected": "shape"}
        ),
    )

    with pytest.raises(DataFetchError, match="Invalid response structure"):
        fetcher._fetch_data_chunk(
            (
                date(2024, 1, 1),
                date(2024, 1, 2),
                "user",
                "minute",
                321,
                {"Authorization": "token"},
            )
        )


def test_fetch_data_chunk_wraps_connection_error(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        data_fetcher_module.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.exceptions.ConnectionError("offline")
        ),
    )

    with pytest.raises(DataFetchError, match="Connection error"):
        fetcher._fetch_data_chunk(
            (
                date(2024, 1, 1),
                date(2024, 1, 2),
                "user",
                "minute",
                321,
                {"Authorization": "token"},
            )
        )


def test_fetch_data_chunk_wraps_timeout_error(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        data_fetcher_module.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.exceptions.Timeout("slow")
        ),
    )

    with pytest.raises(DataFetchError, match="Request timeout"):
        fetcher._fetch_data_chunk(
            (
                date(2024, 1, 1),
                date(2024, 1, 2),
                "user",
                "minute",
                321,
                {"Authorization": "token"},
            )
        )


def test_fetch_data_chunk_wraps_request_exception(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        data_fetcher_module.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.exceptions.RequestException("bad request")
        ),
    )

    with pytest.raises(DataFetchError, match="Request failed"):
        fetcher._fetch_data_chunk(
            (
                date(2024, 1, 1),
                date(2024, 1, 2),
                "user",
                "minute",
                321,
                {"Authorization": "token"},
            )
        )


def test_fetch_data_chunk_wraps_json_decode_error(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        data_fetcher_module.requests,
        "get",
        lambda *args, **kwargs: ResponseStub(
            status_code=200,
            json_data=json.JSONDecodeError("bad json", "doc", 0),
        ),
    )

    with pytest.raises(DataFetchError, match="Invalid JSON response"):
        fetcher._fetch_data_chunk(
            (
                date(2024, 1, 1),
                date(2024, 1, 2),
                "user",
                "minute",
                321,
                {"Authorization": "token"},
            )
        )


def test_validate_date_range_keeps_valid_range_unchanged(fetcher_factory):
    fetcher = fetcher_factory()
    start = date(2024, 1, 1)
    end = date(2024, 1, 5)

    assert fetcher._validate_date_range(start, end) == (start, end)


def test_validate_date_range_caps_future_end_date_to_today(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2024, 1, 10)

    monkeypatch.setattr(data_fetcher_module, "date", FakeDate)

    start, end = fetcher._validate_date_range(
        FakeDate(2024, 1, 1), FakeDate(2024, 1, 20)
    )

    assert start == FakeDate(2024, 1, 1)
    assert end == FakeDate(2024, 1, 10)


def test_validate_date_range_caps_start_date_to_max_historical_window(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2024, 1, 10)

    monkeypatch.setattr(data_fetcher_module, "date", FakeDate)

    start, end = fetcher._validate_date_range(
        FakeDate(2010, 1, 1), FakeDate(2024, 1, 5)
    )

    assert start == FakeDate(2024, 1, 10) - relativedelta(
        years=Config.MAX_HISTORICAL_YEARS
    )
    assert end == FakeDate(2024, 1, 5)


def test_validate_date_range_swaps_dates_when_start_after_end(fetcher_factory):
    fetcher = fetcher_factory()

    start, end = fetcher._validate_date_range(date(2024, 1, 10), date(2024, 1, 5))

    assert start == date(2024, 1, 5)
    assert end == date(2024, 1, 10)


def test_generate_date_ranges_single_chunk_when_range_under_30_days(fetcher_factory):
    fetcher = fetcher_factory()

    ranges = fetcher._generate_date_ranges(
        date(2024, 1, 1),
        date(2024, 1, 20),
        "user",
        "minute",
        123,
        {"Authorization": "token"},
    )

    assert ranges == [
        (
            date(2024, 1, 1),
            date(2024, 1, 20),
            "user",
            "minute",
            123,
            {"Authorization": "token"},
        )
    ]


def test_generate_date_ranges_multiple_chunks_when_range_exceeds_30_days(
    fetcher_factory,
):
    fetcher = fetcher_factory()

    ranges = fetcher._generate_date_ranges(
        date(2024, 1, 1),
        date(2024, 3, 5),
        "user",
        "minute",
        123,
        {"Authorization": "token"},
    )

    assert ranges == [
        (
            date(2024, 1, 1),
            date(2024, 1, 31),
            "user",
            "minute",
            123,
            {"Authorization": "token"},
        ),
        (
            date(2024, 2, 1),
            date(2024, 3, 2),
            "user",
            "minute",
            123,
            {"Authorization": "token"},
        ),
        (
            date(2024, 3, 3),
            date(2024, 3, 5),
            "user",
            "minute",
            123,
            {"Authorization": "token"},
        ),
    ]


def test_generate_date_ranges_returns_empty_when_start_equals_end(fetcher_factory):
    fetcher = fetcher_factory()

    assert (
        fetcher._generate_date_ranges(
            date(2024, 1, 1),
            date(2024, 1, 1),
            "user",
            "minute",
            123,
            {"Authorization": "token"},
        )
        == []
    )


def test_fetch_historical_data_returns_empty_dataframe_when_all_chunks_empty(
    fetcher_factory, monkeypatch
):
    from conftest import FakeExecutor, fake_as_completed

    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(
        fetcher,
        "_generate_date_ranges",
        lambda *args: [
            (
                date(2024, 1, 1),
                date(2024, 1, 2),
                "user",
                "minute",
                111,
                {"Authorization": "token"},
            )
        ],
    )
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda _params: pd.DataFrame())
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", FakeExecutor
    )
    monkeypatch.setattr(data_fetcher_module, "as_completed", fake_as_completed)

    result = fetcher.fetch_historical_data("INFY", date(2024, 1, 1), date(2024, 1, 2))

    assert result.empty is True


def test_fetch_historical_data_combines_sorts_and_formats_chunk_results(
    fetcher_factory, monkeypatch
):
    from conftest import FakeExecutor, FakeFuture, fake_as_completed

    fetcher = fetcher_factory()
    chunk_one = pd.DataFrame(
        [
            {
                "Timestamp": "2024-01-01T09:16:00+0530",
                "Open": 2,
                "High": 3,
                "Low": 1,
                "Close": 2.5,
                "Volume": 20,
            }
        ]
    )
    chunk_two = pd.DataFrame(
        [
            {
                "Timestamp": "2024-01-01T09:15:00+0530",
                "Open": 1,
                "High": 2,
                "Low": 0.5,
                "Close": 1.5,
                "Volume": 10,
            }
        ]
    )
    date_ranges = [
        (
            date(2024, 1, 1),
            date(2024, 1, 2),
            "test_user",
            "minute",
            111,
            {"Authorization": "enctoken auth-token"},
        ),
        (
            date(2024, 1, 3),
            date(2024, 1, 4),
            "test_user",
            "minute",
            111,
            {"Authorization": "enctoken auth-token"},
        ),
    ]
    queued_futures = [
        FakeFuture(result_value=chunk_one),
        FakeFuture(result_value=chunk_two),
    ]

    class ExecutorWithMappedFutures(FakeExecutor):
        def submit(self, fn, params):
            self.submitted_params.append(params)
            return queued_futures.pop(0)

    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(fetcher, "_generate_date_ranges", lambda *args: date_ranges)
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda params: None)
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", ExecutorWithMappedFutures
    )
    monkeypatch.setattr(data_fetcher_module, "as_completed", fake_as_completed)

    result = fetcher.fetch_historical_data("INFY", date(2024, 1, 1), date(2024, 1, 4))

    assert list(result.columns) == [
        "Date",
        "Time",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]
    assert result["Time"].tolist() == ["09:15", "09:16"]
    assert result["Date"].tolist() == ["2024-01-01", "2024-01-01"]
    assert "Timestamp" not in result.columns


def test_fetch_historical_data_strict_mode_raises_if_any_chunk_fails(
    fetcher_factory, monkeypatch
):
    from conftest import FakeExecutor, FakeFuture, fake_as_completed

    fetcher = fetcher_factory()
    chunk_success = pd.DataFrame(
        [
            {
                "Timestamp": "2024-01-01T09:15:00+0530",
                "Open": 1,
                "High": 2,
                "Low": 0.5,
                "Close": 1.5,
                "Volume": 10,
            }
        ]
    )
    params_one = (
        date(2024, 1, 1),
        date(2024, 1, 2),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    params_two = (
        date(2024, 1, 3),
        date(2024, 1, 4),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    failing_future = FakeFuture(exception=RuntimeError("chunk failed"))
    queued_futures = [FakeFuture(result_value=chunk_success), failing_future]

    class ExecutorWithMappedFutures(FakeExecutor):
        def submit(self, fn, params):
            self.submitted_params.append(params)
            return queued_futures.pop(0)

    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(
        fetcher, "_generate_date_ranges", lambda *args: [params_one, params_two]
    )
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda params: chunk_success)
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", ExecutorWithMappedFutures
    )
    monkeypatch.setattr(data_fetcher_module, "as_completed", fake_as_completed)

    with pytest.raises(DataFetchError, match="strict mode"):
        fetcher.fetch_historical_data("INFY", date(2024, 1, 1), date(2024, 1, 4))

    assert failing_future.cancel_called is False


def test_fetch_historical_data_strict_mode_cancels_pending_futures(
    fetcher_factory, monkeypatch
):
    from conftest import FakeExecutor, FakeFuture

    fetcher = fetcher_factory()
    params_one = (
        date(2024, 1, 1),
        date(2024, 1, 2),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    params_two = (
        date(2024, 1, 3),
        date(2024, 1, 4),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    first_future = FakeFuture(exception=RuntimeError("chunk failed"))
    second_future = FakeFuture(result_value=pd.DataFrame())
    queued_futures = [first_future, second_future]

    class ExecutorWithMappedFutures(FakeExecutor):
        def submit(self, fn, params):
            self.submitted_params.append(params)
            return queued_futures.pop(0)

    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(
        fetcher, "_generate_date_ranges", lambda *args: [params_one, params_two]
    )
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda params: pd.DataFrame())
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", ExecutorWithMappedFutures
    )
    monkeypatch.setattr(
        data_fetcher_module, "as_completed", lambda future_map: [first_future]
    )

    with pytest.raises(DataFetchError, match="cancelled 1 pending chunk"):
        fetcher.fetch_historical_data("INFY", date(2024, 1, 1), date(2024, 1, 4))

    assert second_future.cancel_called is True


def test_fetch_historical_data_partial_mode_returns_partial_data_and_logs_one_warning(
    fetcher_factory,
    monkeypatch,
    caplog,
):
    from conftest import FakeExecutor, FakeFuture, fake_as_completed

    fetcher = fetcher_factory()
    chunk_success = pd.DataFrame(
        [
            {
                "Timestamp": "2024-01-01T09:15:00+0530",
                "Open": 1,
                "High": 2,
                "Low": 0.5,
                "Close": 1.5,
                "Volume": 10,
            }
        ]
    )
    params_one = (
        date(2024, 1, 1),
        date(2024, 1, 2),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    params_two = (
        date(2024, 1, 3),
        date(2024, 1, 4),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    queued_futures = [
        FakeFuture(result_value=chunk_success),
        FakeFuture(exception=RuntimeError("chunk failed")),
    ]

    class ExecutorWithMappedFutures(FakeExecutor):
        def submit(self, fn, params):
            self.submitted_params.append(params)
            return queued_futures.pop(0)

    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(
        fetcher, "_generate_date_ranges", lambda *args: [params_one, params_two]
    )
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda params: chunk_success)
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", ExecutorWithMappedFutures
    )
    monkeypatch.setattr(data_fetcher_module, "as_completed", fake_as_completed)

    with caplog.at_level(logging.WARNING):
        result = fetcher.fetch_historical_data(
            "INFY",
            date(2024, 1, 1),
            date(2024, 1, 4),
            chunk_failure_mode="partial",
        )

    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if "Historical fetch completed with partial data" in record.getMessage()
    ]

    assert len(result) == 1
    assert warning_messages == [
        "Historical fetch completed with partial data: 1/2 chunks failed. Failed ranges: 2024-01-03 to 2024-01-04"
    ]


def test_fetch_historical_data_partial_mode_raises_if_all_chunks_fail(
    fetcher_factory, monkeypatch
):
    from conftest import FakeExecutor, FakeFuture, fake_as_completed

    fetcher = fetcher_factory()
    params_one = (
        date(2024, 1, 1),
        date(2024, 1, 2),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    params_two = (
        date(2024, 1, 3),
        date(2024, 1, 4),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    queued_futures = [
        FakeFuture(exception=RuntimeError("chunk failed one")),
        FakeFuture(exception=RuntimeError("chunk failed two")),
    ]

    class ExecutorWithMappedFutures(FakeExecutor):
        def submit(self, fn, params):
            self.submitted_params.append(params)
            return queued_futures.pop(0)

    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(
        fetcher, "_generate_date_ranges", lambda *args: [params_one, params_two]
    )
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda params: pd.DataFrame())
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", ExecutorWithMappedFutures
    )
    monkeypatch.setattr(data_fetcher_module, "as_completed", fake_as_completed)

    with pytest.raises(DataFetchError, match="all 2 chunk\\(s\\) failed"):
        fetcher.fetch_historical_data(
            "INFY",
            date(2024, 1, 1),
            date(2024, 1, 4),
            chunk_failure_mode="partial",
        )


def test_fetch_historical_data_per_call_override_wins_over_constructor_default(
    fetcher_factory, monkeypatch
):
    from conftest import FakeExecutor, FakeFuture, fake_as_completed

    fetcher = fetcher_factory(chunk_failure_mode="partial")
    params_one = (
        date(2024, 1, 1),
        date(2024, 1, 2),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    params_two = (
        date(2024, 1, 3),
        date(2024, 1, 4),
        "test_user",
        "minute",
        111,
        {"Authorization": "enctoken auth-token"},
    )
    queued_futures = [
        FakeFuture(
            result_value=pd.DataFrame(
                [
                    {
                        "Timestamp": "2024-01-01T09:15:00+0530",
                        "Open": 1,
                        "High": 2,
                        "Low": 0.5,
                        "Close": 1.5,
                        "Volume": 10,
                    }
                ]
            )
        ),
        FakeFuture(exception=RuntimeError("chunk failed")),
    ]

    class ExecutorWithMappedFutures(FakeExecutor):
        def submit(self, fn, params):
            self.submitted_params.append(params)
            return queued_futures.pop(0)

    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(
        fetcher, "_generate_date_ranges", lambda *args: [params_one, params_two]
    )
    monkeypatch.setattr(fetcher, "_fetch_data_chunk", lambda params: pd.DataFrame())
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", ExecutorWithMappedFutures
    )
    monkeypatch.setattr(data_fetcher_module, "as_completed", fake_as_completed)

    with pytest.raises(DataFetchError, match="strict mode"):
        fetcher.fetch_historical_data(
            "INFY",
            date(2024, 1, 1),
            date(2024, 1, 4),
            chunk_failure_mode="strict",
        )


def test_fetch_historical_data_raises_invalid_ticker_error_unchanged(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(
        fetcher,
        "_resolve_ticker_token",
        lambda _ticker: (_ for _ in ()).throw(InvalidTickerError("bad ticker")),
    )

    with pytest.raises(InvalidTickerError, match="bad ticker"):
        fetcher.fetch_historical_data("INFY", date(2024, 1, 1), date(2024, 1, 2))


def test_fetch_historical_data_raises_authentication_error_unchanged(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(
        fetcher.auth_manager,
        "get_auth_token",
        lambda: (_ for _ in ()).throw(AuthenticationError("auth failed")),
    )

    with pytest.raises(AuthenticationError, match="auth failed"):
        fetcher.fetch_historical_data("INFY", date(2024, 1, 1), date(2024, 1, 2))


def test_fetch_historical_data_wraps_unexpected_error_as_data_fetch_error(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory()
    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(
        fetcher,
        "_generate_date_ranges",
        lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    with pytest.raises(DataFetchError, match="unexpected"):
        fetcher.fetch_historical_data("INFY", date(2024, 1, 1), date(2024, 1, 2))


def test_fetch_historical_data_passes_resolved_token_and_auth_header_to_range_generation(
    fetcher_factory,
    monkeypatch,
):
    from conftest import FakeExecutor, fake_as_completed

    fetcher = fetcher_factory()
    captured = {}

    def fake_generate(start, end, userid, timeframe, token, headers):
        captured["args"] = (start, end, userid, timeframe, token, headers)
        return []

    monkeypatch.setattr(fetcher, "_resolve_ticker_token", lambda _ticker: 111)
    monkeypatch.setattr(
        fetcher, "_validate_date_range", lambda start, end: (start, end)
    )
    monkeypatch.setattr(fetcher.auth_manager, "get_auth_token", lambda: "auth-token")
    monkeypatch.setattr(fetcher.config, "get_user_id", lambda: "test_user")
    monkeypatch.setattr(fetcher, "_generate_date_ranges", fake_generate)
    monkeypatch.setattr(
        data_fetcher_module, "RateLimitedThreadPoolExecutor", FakeExecutor
    )
    monkeypatch.setattr(data_fetcher_module, "as_completed", fake_as_completed)

    result = fetcher.fetch_historical_data(
        "INFY", date(2024, 1, 1), date(2024, 1, 2), timeframe="day"
    )

    assert result.empty is True
    assert captured["args"] == (
        date(2024, 1, 1),
        date(2024, 1, 2),
        "test_user",
        "day",
        111,
        {"Authorization": "enctoken auth-token"},
    )


def test_get_instrument_info_returns_first_row_as_dict(fetcher_factory):
    class InstrumentManagerStub:
        def search_symbol(self, symbol, limit=1):
            return pd.DataFrame([{"Instrument_Token": 101, "Name": "INFY"}])

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    result = fetcher.get_instrument_info("INFY")

    assert result == {"Instrument_Token": 101, "Name": "INFY"}


def test_get_instrument_info_returns_none_when_no_results(fetcher_factory):
    class InstrumentManagerStub:
        def search_symbol(self, symbol, limit=1):
            return pd.DataFrame()

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    assert fetcher.get_instrument_info("INFY") is None


def test_get_instrument_info_returns_none_on_exception(fetcher_factory):
    class InstrumentManagerStub:
        def search_symbol(self, symbol, limit=1):
            raise RuntimeError("boom")

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    assert fetcher.get_instrument_info("INFY") is None


def test_search_symbols_returns_dataframe_from_manager(fetcher_factory):
    class InstrumentManagerStub:
        def search_symbol(self, symbol, limit=10):
            return pd.DataFrame([{"Name": "INFY"}])

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    result = fetcher.search_symbols("INF")

    assert result.to_dict("records") == [{"Name": "INFY"}]


def test_search_symbols_returns_empty_dataframe_on_exception(fetcher_factory):
    class InstrumentManagerStub:
        def search_symbol(self, symbol, limit=10):
            raise RuntimeError("boom")

    fetcher = fetcher_factory(instrument_manager=InstrumentManagerStub())

    result = fetcher.search_symbols("INF")

    assert result.empty is True


def test_fetchDataZerodha_constructs_fetcher_and_delegates_call(monkeypatch):
    captured = {}

    class FakeFetcher:
        def __init__(self, requests_per_second):
            captured["requests_per_second"] = requests_per_second

        def fetch_historical_data(self, ticker_token, start_date, end_date):
            captured["call"] = (ticker_token, start_date, end_date)
            return "result"

    monkeypatch.setattr(data_fetcher_module, "ZerodhaDataFetcher", FakeFetcher)

    result = data_fetcher_module.fetchDataZerodha(
        ticker_token="INFY",
        startDate=date(2024, 1, 1),
        endDate=date(2024, 1, 2),
        reqPerSec=5,
    )

    assert result == "result"
    assert captured["requests_per_second"] == 5
    assert captured["call"] == ("INFY", date(2024, 1, 1), date(2024, 1, 2))
