# Risk Mitigation Plan For Zerodha Data Fetcher

## Summary

This plan hardens the package in four areas:

1. Stop credential and MFA leakage in logs.
2. Replace the current submission-based throttling with execution-time request limiting that actually enforces the configured rate.
3. Fix correctness bugs in date chunk generation and token-validation retry behavior.
4. Add a focused automated test suite around the highest-risk flows so regressions are caught before release.

The plan preserves the current public entry points by default. The only behavioral changes are deliberate fixes: stricter log redaction, correct rate limiting, correct single-day fetch behavior, bounded retry behavior, and broader/clearer instrument lookup rules.

## Scope

In scope:

- Authentication and token-generation logging
- Runtime rate limiting for historical fetch requests
- Historical date chunk generation
- Token refresh / invalidation control flow
- Instrument lookup behavior for symbols and exchanges
- Regression tests for the above
- Minor metadata/documentation cleanup where it directly affects correctness expectations

Out of scope:

- Rewriting the package architecture
- Adding async APIs
- Replacing `requests` with another HTTP client
- Live integration tests against Zerodha in CI
- Large README redesign beyond targeted accuracy fixes

## Implementation Plan

### 1. Remove sensitive data from logs

Target files:

- [token_generator.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\token_generator.py)
- [logging_config.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\utils\logging_config.py) if needed for redaction filters

Changes:

- Delete any log statements that print:
  - TOTP values
  - Raw login response bodies
  - Raw response headers/cookies
  - Full auth response content
- Replace them with low-sensitivity status logs:
  - "TOTP generated successfully"
  - "Login request completed"
  - "2FA request completed"
  - "Authentication token retrieved"
- Where error diagnostics are needed, log:
  - HTTP status code
  - top-level error message from parsed JSON if present
  - exception class name
- Do not log full `response.text` for authentication endpoints.
- Keep debug logging for flow milestones only, not payloads or secrets.

Acceptance criteria:

- No code path logs OTPs, passwords, tokens, cookies, or full auth payloads.
- Failed login still provides enough information to distinguish config errors vs upstream auth errors.

### 2. Replace the current rate limiter with true request-time throttling

Target files:

- [rate_limiter.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\rate_limiter.py)
- [data_fetcher.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\data_fetcher.py)

Problem being fixed:

- Current logic throttles `executor.submit()` calls, not the actual HTTP request execution. With multiple workers, requests can still burst above the configured rate.

Approach:

- Stop relying on `ThreadPoolExecutor.submit()` as the throttle point.
- Introduce a thread-safe execution-time limiter with a `wait_for_slot()` method.
- Use a monotonic clock and a `threading.Lock`.
- Enforce a minimum interval of `1 / requests_per_second` between actual outgoing HTTP requests across all workers.
- Call the limiter immediately before `requests.get(...)` inside `_fetch_data_chunk()`.

Recommended design:

- `RequestRateLimiter` class with:
  - `requests_per_second: int`
  - private `lock`
  - private `next_allowed_time`
  - `wait_for_slot()` method
- Keep `RateLimitedThreadPoolExecutor` only if needed for backward compatibility, but remove rate-enforcement responsibility from it.
- In `ZerodhaDataFetcher.__init__`, create one limiter instance and store it on `self`.
- In `_fetch_data_chunk`, call `self.rate_limiter.wait_for_slot()` before the HTTP call.

Behavioral defaults:

- Rate limit remains global per `ZerodhaDataFetcher` instance.
- `MAX_WORKERS` can stay at current value unless later performance testing shows it should be reduced.
- This preserves concurrency for parsing/aggregation while serializing only the outbound request pacing.

Acceptance criteria:

- Actual request timestamps are spaced according to configured RPS.
- Parallel fetches no longer burst past the cap under high worker counts.

### 3. Fix date range chunking edge cases

Target file:

- [data_fetcher.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\data_fetcher.py)

Problems being fixed:

- `start_date == end_date` currently generates zero chunks.
- Chunk boundaries should be deterministic and inclusive enough for single-day fetches.

Approach:

- Rework `_generate_date_ranges()` to guarantee at least one chunk when `start_date <= end_date`.
- Use an inclusive chunking rule:
  - each chunk covers `current_date` through `next_date`
  - next chunk starts at `previous_next_date + 1 day`
- Loop condition should be `while current_date <= end_date`.

Default chunk algorithm:

- `interval_days = Config.DEFAULT_CHUNK_DAYS`
- `next_date = min(current_date + timedelta(days=interval_days - 1), end_date)` if the API treats both bounds as inclusive.
- Keep advancing by `next_date + 1 day`.

Reason for this specific default:

- It avoids overlap and avoids accidental 31-day windows when the intended chunk size is 30 days.

Additional guard:

- If validated `start_date > end_date`, `_validate_date_range()` already swaps them; keep that behavior.

Acceptance criteria:

- A single-day request produces exactly one chunk.
- Multi-chunk ranges cover the full period without gaps or overlaps.
- Returned data is still sorted chronologically.

### 4. Bound token refresh retries and separate token errors cleanly

Target files:

- [data_fetcher.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\data_fetcher.py)
- [auth.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\auth.py)

Problems being fixed:

- `_validate_ticker_token()` recursively retries on token expiration with no bound.
- Fetch paths do not clearly distinguish token expiry from invalid instrument failures.

Approach:

- Replace recursive retry in `_validate_ticker_token()` with a bounded loop.
- Allow exactly one forced token refresh during validation.
- If a second token-related failure occurs, raise `AuthenticationError` or return `False` based on context, but do not recurse.

Detailed control flow:

- Attempt validation with current token.
- If API error indicates token expiry / `TokenException`:
  - invalidate stored token
  - fetch a fresh token once
  - retry validation once
- If the retry also yields token-expiry semantics:
  - raise `AuthenticationError("Authentication token refresh failed")`
- If API error indicates invalid instrument/token identifier:
  - return `False`
- Any other transport/parsing errors:
  - raise `DataFetchError` rather than silently converting everything to "invalid ticker"

Why this matters:

- Today, network failures and auth failures can be misclassified as invalid tickers, which hides root cause.

Acceptance criteria:

- No recursive validation path remains.
- Auth failures are surfaced distinctly from invalid ticker failures.
- Validation never loops indefinitely.

### 5. Make instrument resolution behavior explicit and safer

Target file:

- [instrument_manager.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\instrument_manager.py)

Problems being fixed:

- Equity resolution is hardcoded to `NSE`.
- Search is broader than resolution, which leads to user-visible inconsistency.
- Commodity parsing assumes space-delimited input and can fail on unexpected formats.

Approach:

- Preserve current API shape but tighten lookup rules.
- Add explicit exchange preference logic for equity symbols.

Recommended lookup behavior:

- For `get_instrument_token(symbol, is_stock=True)`:
  - normalize input with `strip().upper()`
  - search exact `Name` match across supported exchanges
  - prefer `NSE`, then `BSE`, then first exact match
- For `search_symbol()`:
  - continue case-insensitive search
  - optionally sort exact matches ahead of partial matches
- For commodity parsing:
  - guard against malformed strings before `split(" ")[0]` / `[-1]`
  - if normalization fails, return `None` instead of swallowing ambiguous exceptions

Optional API enhancement:

- Add an optional `exchange: Optional[str] = None` parameter to `get_instrument_token()`.
- If provided, constrain exact-match lookup to that exchange.
- If omitted, use default preference order `NSE -> BSE -> first exact match`.

Public API impact:

- This is backward compatible if `exchange` is optional.
- It improves determinism without breaking existing callers.

Acceptance criteria:

- Common equity symbols resolve even when only available on `BSE`.
- Lookup behavior is deterministic and documented.
- Malformed commodity inputs do not trigger broad exception swallowing.

### 6. Tighten error classification in data fetching

Target file:

- [data_fetcher.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\core\data_fetcher.py)

Changes:

- Stop wrapping every unexpected exception into a generic `DataFetchError` too early when more specific exceptions are available.
- Parse API error payloads centrally where possible.
- Distinguish:
  - authentication/token failure
  - invalid ticker / instrument
  - transient network failure
  - upstream malformed response
- When aggregating chunk futures:
  - track failed chunk count
  - if all chunks fail, raise `DataFetchError` with summary instead of returning an empty frame indistinguishable from "no market data"
  - if some chunks fail, log a warning and continue, but include failure count in final logs

Acceptance criteria:

- "No data exists" and "all requests failed" are distinguishable outcomes.
- Users get actionable exceptions instead of generic failures.

### 7. Add a focused regression test suite

Target path:

- `tests/`

Add at minimum:

- `tests/test_rate_limiter.py`
- `tests/test_data_fetcher_dates.py`
- `tests/test_data_fetcher_validation.py`
- `tests/test_instrument_manager.py`
- `tests/test_token_generator_logging.py`

Test strategy:

- Use `pytest`.
- Use `unittest.mock` / `monkeypatch` to avoid live network and live keyring dependence.
- Mock `requests.get`, `Session.get`, `Session.post`, `session.cookies`, `keyring.*`, and `load_instrument_data()` as needed.

Required test cases:

1. Rate limiter
- Multiple concurrent chunk fetches do not call the HTTP layer faster than configured interval.
- Limiter remains correct under more workers than RPS.

2. Date chunking
- `start_date == end_date` yields one chunk.
- A 30-day exact span yields correct non-overlapping chunk count.
- Start/end swap still results in covered range after validation.

3. Token validation
- Token-expiry response triggers exactly one invalidate-and-retry.
- Repeated token-expiry response raises `AuthenticationError`.
- Invalid instrument response returns `False`.
- Non-auth transport exception is not mislabeled as invalid ticker.

4. Instrument resolution
- Exact symbol on `NSE` resolves correctly.
- Exact symbol absent on `NSE` but present on `BSE` resolves correctly.
- Optional `exchange` parameter, if added, constrains lookup.
- Malformed commodity symbol input fails safely.

5. Logging hygiene
- TOTP value is never emitted to logs.
- Raw auth payload/response content is never emitted to logs.

6. Partial failure aggregation
- Some empty chunks + some valid chunks still return combined data.
- All failed chunks raise an error, not an empty frame.

### 8. Align package metadata and documentation with actual behavior

Target files:

- [__init__.py](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\src\zerodha_data_fetcher\__init__.py)
- [pyproject.toml](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\pyproject.toml)
- [README.md](D:\Coding\Zerodha Data Fetcher\Zerodha-Data-Fetcher\README.md)

Changes:

- Sync `__version__` with package metadata version in `pyproject.toml`.
- Update README to document:
  - exchange preference behavior
  - bounded token refresh semantics
  - accurate logging/security posture
  - meaning of empty DataFrame vs raised exception
- Fix broken/garbled emoji encoding in README if desired, but only as a secondary cleanup.
- Document the new optional `exchange` parameter if added.

Acceptance criteria:

- Installed version metadata and imported version match.
- README examples match the implemented resolution behavior.

## Public API / Interface Changes

Recommended public API changes:

- Keep `ZerodhaDataFetcher.fetch_historical_data(...)` signature unchanged.
- Keep existing constructor parameters unchanged.
- Add optional `exchange: Optional[str] = None` to `ZerodhaInstrumentManager.get_instrument_token(...)`.
- If helpful for consistency, add optional `exchange: Optional[str] = None` to:
  - `ZerodhaDataFetcher.get_instrument_info(...)`
  - `ZerodhaDataFetcher.search_symbols(...)`
  This is optional, not required for the first mitigation pass.

Internal interface changes:

- Introduce `RequestRateLimiter.wait_for_slot()`.
- Replace recursive token validation with bounded iterative logic.
- Standardize API error parsing helper(s) inside `data_fetcher.py` or a small internal utility.

## Rollout Order

1. Remove sensitive logs.
2. Implement request-time limiter.
3. Fix date chunking and token-validation retry semantics.
4. Tighten instrument resolution.
5. Add tests.
6. Update docs/version metadata.
7. Run local test suite and one manual smoke test with mocked network.
8. Release as a patch version if no public API is added, or minor version if `exchange` parameter is introduced publicly.

## Test And Verification Checklist

- Run `pytest` for the new `tests/` suite.
- Verify import surface still works from package root.
- Verify no secret values appear in captured logs.
- Verify single-day historical fetch path creates one request chunk.
- Verify concurrent chunk submission still produces paced outbound requests.
- Verify auth retry invalidates token once and stops deterministically.
- Verify `BSE`-only symbol resolution works.
- Verify all-chunks-failed case raises, while genuine no-candle responses still return empty data.

## Assumptions And Defaults

- Default requirement is backward compatibility for existing consumers.
- No live Zerodha credentials will be used in automated tests.
- `requests_per_second` remains per-instance, not process-wide.
- Preferred exchange order is `NSE`, then `BSE`, then first exact match.
- A single token refresh retry is sufficient; more retries would hide real auth problems.
- Empty DataFrame should mean "request succeeded but no candle data exists," not "system failed."
- Rate limiting should be enforced at HTTP execution time, not task submission time.
