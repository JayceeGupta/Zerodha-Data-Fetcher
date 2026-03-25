import pytest

from zerodha_data_fetcher.utils import helpers


def test_validate_date_format_accepts_valid_date():
    assert helpers.validate_date_format("2024-01-31") is True


def test_validate_date_format_rejects_invalid_date():
    assert helpers.validate_date_format("2024-02-31") is False


def test_safe_int_conversion_returns_int_on_valid_input():
    assert helpers.safe_int_conversion("42") == 42


def test_safe_int_conversion_falls_back_to_default_on_invalid_input():
    assert helpers.safe_int_conversion("bad-value", default=7) == 7


def test_safe_float_conversion_returns_float_on_valid_input():
    assert helpers.safe_float_conversion("3.14") == 3.14


def test_safe_float_conversion_falls_back_to_default_on_invalid_input():
    assert helpers.safe_float_conversion(None, default=2.5) == 2.5


def test_execution_timer_returns_wrapped_result(caplog):
    caplog.set_level("INFO", logger=helpers.logger.name)

    @helpers.execution_timer
    def sample_function():
        return "ok"

    result = sample_function()

    assert result == "ok"
    assert "sample_function" in caplog.text


def test_retry_on_failure_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(helpers.time, "sleep", lambda _seconds: None)
    attempts = {"count": 0}

    @helpers.retry_on_failure(max_retries=3, delay=1.0, backoff=2.0)
    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("not yet")
        return "done"

    assert flaky() == "done"
    assert attempts["count"] == 3


def test_retry_on_failure_raises_after_last_attempt(monkeypatch):
    monkeypatch.setattr(helpers.time, "sleep", lambda _seconds: None)
    attempts = {"count": 0}

    @helpers.retry_on_failure(max_retries=2, delay=1.0, backoff=2.0)
    def always_fails():
        attempts["count"] += 1
        raise RuntimeError("still failing")

    with pytest.raises(RuntimeError, match="still failing"):
        always_fails()

    assert attempts["count"] == 3
