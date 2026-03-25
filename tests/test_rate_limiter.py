import pytest

from zerodha_data_fetcher.core.rate_limiter import (
    RateLimitedThreadPoolExecutor,
    RequestRateLimiter,
)


def test_rate_limiter_rejects_zero_or_negative_rate():
    with pytest.raises(ValueError):
        RequestRateLimiter(0)

    with pytest.raises(ValueError):
        RequestRateLimiter(-1)


def test_wait_for_slot_first_call_does_not_sleep(monkeypatch):
    limiter = RequestRateLimiter(2)
    sleep_calls = []

    monkeypatch.setattr("zerodha_data_fetcher.core.rate_limiter.time.monotonic", lambda: 10.0)
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.rate_limiter.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    limiter.wait_for_slot()

    assert sleep_calls == []


def test_wait_for_slot_second_call_sleeps_for_interval(monkeypatch):
    limiter = RequestRateLimiter(2)
    monotonic_values = iter([10.0, 10.0])
    sleep_calls = []

    monkeypatch.setattr(
        "zerodha_data_fetcher.core.rate_limiter.time.monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.rate_limiter.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    limiter.wait_for_slot()
    limiter.wait_for_slot()

    assert sleep_calls == [0.5]


def test_rate_limited_executor_stores_requested_rate():
    executor = RateLimitedThreadPoolExecutor(max_workers=2, requests_per_second=4)
    try:
        assert executor.requests_per_second == 4
    finally:
        executor.shutdown(wait=False)
