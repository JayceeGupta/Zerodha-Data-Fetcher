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


def test_rate_limited_executor_rejects_invalid_rate():
    with pytest.raises(ValueError):
        RateLimitedThreadPoolExecutor(max_workers=2, requests_per_second=0)


def test_rate_limited_executor_waits_before_each_submitted_task(monkeypatch):
    wait_calls = []

    def fake_wait(self):
        wait_calls.append(id(self))

    monkeypatch.setattr(RequestRateLimiter, "wait_for_slot", fake_wait)

    with RateLimitedThreadPoolExecutor(max_workers=2, requests_per_second=4) as executor:
        future_one = executor.submit(lambda value, suffix=None: f"{value}-{suffix}", "a", suffix="1")
        future_two = executor.submit(lambda value: value.upper(), "b")

        assert future_one.result() == "a-1"
        assert future_two.result() == "B"

    assert len(wait_calls) == 2
    assert len(set(wait_calls)) == 1
