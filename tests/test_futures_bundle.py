"""Phase 4 — injectable shared limiter + fetch_futures_bundle."""

from datetime import date

import pandas as pd

from zerodha_data_fetcher.core.contract_selector import ResolvedContract
from zerodha_data_fetcher.core.rate_limiter import (
    RateLimitedThreadPoolExecutor,
    RequestRateLimiter,
)


def _contract(selector: str, token: int) -> ResolvedContract:
    return ResolvedContract(
        underlying="GOLD",
        tradingsymbol="GOLD%dFUT" % token,
        instrument_token=token,
        expiry=date(2024, 12, 5),
        segment="MCX-FUT",
        exchange="MCX",
        selector=selector,
    )


def test_executor_uses_injected_rate_limiter():
    limiter = RequestRateLimiter(5)
    executor = RateLimitedThreadPoolExecutor(max_workers=2, rate_limiter=limiter)
    try:
        assert executor._rate_limiter is limiter
        assert executor.requests_per_second == 5
    finally:
        executor.shutdown()


def test_executor_constructs_own_limiter_when_none_injected():
    executor = RateLimitedThreadPoolExecutor(max_workers=2, requests_per_second=3)
    try:
        assert isinstance(executor._rate_limiter, RequestRateLimiter)
        assert executor._rate_limiter.requests_per_second == 3
    finally:
        executor.shutdown()


def test_bundle_returns_dict_keyed_by_selector_with_tokens(
    fetcher_factory, monkeypatch
):
    fetcher = fetcher_factory(requests_per_second=4)

    resolved = {
        "near_prev": _contract("near_prev", 111),
        "near": _contract("near", 112),
        "near_next": _contract("near_next", 113),
    }
    monkeypatch.setattr(
        fetcher.instrument_manager,
        "resolve_futures_contract",
        lambda underlying, selector, **k: resolved[selector],
    )

    def fake_fetch(ticker_token, *a, **k):
        return pd.DataFrame({"token": [ticker_token]})

    monkeypatch.setattr(fetcher, "fetch_historical_data", fake_fetch)

    bundle = fetcher.fetch_futures_bundle(
        "GOLD",
        date(2024, 1, 1),
        date(2024, 12, 1),
        selectors=("near_prev", "near", "near_next"),
    )

    assert set(bundle.keys()) == {"near_prev", "near", "near_next"}
    assert bundle["near"]["token"].iloc[0] == 112
    assert bundle["near_prev"]["token"].iloc[0] == 111


def test_bundle_uses_one_shared_limiter_for_all_contracts(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory(requests_per_second=4)

    resolved = {
        "near": _contract("near", 112),
        "near_next": _contract("near_next", 113),
    }
    monkeypatch.setattr(
        fetcher.instrument_manager,
        "resolve_futures_contract",
        lambda underlying, selector, **k: resolved[selector],
    )

    # Count how many RequestRateLimiter objects get constructed during the call.
    import zerodha_data_fetcher.core.data_fetcher as df_mod

    constructed = []
    real_init = RequestRateLimiter.__init__

    def counting_init(self, rps):
        constructed.append(self)
        real_init(self, rps)

    monkeypatch.setattr(df_mod.RequestRateLimiter, "__init__", counting_init)

    seen_limiters = []

    def fake_fetch(ticker_token, *a, **k):
        seen_limiters.append(k.get("rate_limiter"))
        return pd.DataFrame({"token": [ticker_token]})

    monkeypatch.setattr(fetcher, "fetch_historical_data", fake_fetch)

    fetcher.fetch_futures_bundle(
        "GOLD",
        date(2024, 1, 1),
        date(2024, 12, 1),
        selectors=("near", "near_next"),
    )

    # Exactly one limiter built, and every contract fetch received that same one.
    assert len(constructed) == 1
    assert all(lim is constructed[0] for lim in seen_limiters)
    assert len(seen_limiters) == 2


def test_bundle_dedups_identical_tokens(fetcher_factory, monkeypatch):
    fetcher = fetcher_factory(requests_per_second=4)

    # near and near_next resolve to the same contract/token.
    same = _contract("near", 200)
    monkeypatch.setattr(
        fetcher.instrument_manager,
        "resolve_futures_contract",
        lambda underlying, selector, **k: same,
    )

    calls = {"n": 0}

    def fake_fetch(ticker_token, *a, **k):
        calls["n"] += 1
        return pd.DataFrame({"token": [ticker_token]})

    monkeypatch.setattr(fetcher, "fetch_historical_data", fake_fetch)

    bundle = fetcher.fetch_futures_bundle(
        "GOLD", date(2024, 1, 1), date(2024, 12, 1), selectors=("near", "near_next")
    )

    assert calls["n"] == 1  # fetched once for the shared token
    assert bundle["near"]["token"].iloc[0] == 200
    assert bundle["near_next"]["token"].iloc[0] == 200
