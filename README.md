# Zerodha Data Fetcher

[![PyPI version](https://img.shields.io/pypi/v/zerodha-data-fetcher)](https://pypi.org/project/zerodha-data-fetcher/)
[![Python versions](https://img.shields.io/pypi/pyversions/zerodha-data-fetcher)](https://pypi.org/project/zerodha-data-fetcher/)
[![Tests](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/actions/workflows/test.yml/badge.svg)](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/JayceeGupta/Zerodha-Data-Fetcher)](LICENSE)

Fetch historical OHLC data from Zerodha Kite using your normal account login. It logs in the way the Kite web app does (user ID, password, TOTP), so it does **not** require a paid Kite Connect API subscription.

It returns a pandas DataFrame, resolves trading symbols to instrument tokens for you, splits long date ranges into chunks fetched in parallel, paces requests to stay within rate limits, and caches the auth token (encrypted) in your OS keyring between runs.

## How it works (and what to know before you rely on it)

This library automates the **web** login flow at `kite.zerodha.com` and reads historical data from the same internal endpoint the web app uses. That has two consequences worth understanding up front:

- **It is unofficial.** It does not use the supported Kite Connect API. Zerodha can change these endpoints or the login flow at any time, and a change can break the library until it is updated.
- **It is your responsibility to use it within Zerodha's terms of service** and any applicable regulations. Keep request rates reasonable; the defaults here are deliberately conservative.

If you need a supported, contractual API, use [Kite Connect](https://kite.trade/). This library exists for the case where you have an account and want your own historical data without a separate subscription.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Historical Fetch Failure Modes](#historical-fetch-failure-modes)
- [Logging](#logging)
- [Multiple Accounts](#multiple-accounts)
- [Instrument Data Caching](#instrument-data-caching)
- [API Reference](#api-reference)
- [Error Handling](#error-handling)
- [Development](#development)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)
- [Disclaimer](#disclaimer)

## Prerequisites

- Python 3.8 or newer
- A Zerodha account with Kite access
- TOTP-based 2FA enabled on that account ([Zerodha's setup guide](https://support.zerodha.com/category/trading-and-markets/general-kite/login-credentials-of-trading-platforms/articles/time-based-otp-setup))
- `pip` or `uv`

## Installation

```bash
pip install zerodha-data-fetcher
```

## Quick Start

Provide your credentials through environment variables (a `.env` file in your project root is read automatically):

```env
ZERODHA_USER_ID=your_user_id
ZERODHA_PASSWORD=your_password
ZERODHA_TOTP_SECRET=your_totp_secret
```

`ZERODHA_TOTP_SECRET` is the base32 secret shown when you set up TOTP, not a 6-digit code. The library generates the current code from it at login time.

```python
from datetime import date, timedelta

from zerodha_data_fetcher import ZerodhaDataFetcher, setup_logging

setup_logging(log_level="INFO", log_file="logs/zerodha_fetcher.log")

fetcher = ZerodhaDataFetcher(requests_per_second=3)

end_date = date.today()
start_date = end_date - timedelta(days=30)

# By trading symbol — resolved to an instrument token automatically (NSE preferred)
data = fetcher.fetch_historical_data(
    ticker_token="RELIANCE",
    start_date=start_date,
    end_date=end_date,
    timeframe="minute",
)
print(f"Retrieved {len(data)} records")
print(data.head())

# Or by instrument token directly
data = fetcher.fetch_historical_data(
    ticker_token=408065,
    start_date=start_date,
    end_date=end_date,
    timeframe="day",
)

# Look up instruments
print(fetcher.search_symbols("TATA", limit=5))
print(fetcher.get_instrument_info("INFY"))
```

`timeframe` accepts the same values as the Kite web app — `minute`, `3minute`, `5minute`, `15minute`, `30minute`, `60minute`, `day`, `week`. The library passes the value through to the API rather than validating it, so an unsupported value fails at request time.

Authentication logs are sanitized by default: TOTP values, raw auth response bodies, headers, cookies, and encrypted token material are never written to the logs.

## Configuration

Only the three credential variables are required. Everything else has a working default and rarely needs changing.

| Variable | Description | Required | Default |
| -------- | ----------- | -------- | ------- |
| `ZERODHA_USER_ID` | Zerodha user ID | Yes | – |
| `ZERODHA_PASSWORD` | Zerodha password | Yes | – |
| `ZERODHA_TOTP_SECRET` | Base32 TOTP secret for 2FA | Yes | – |
| `ZERODHA_TYPE` | Account type (`user_id` or `corporate`) | No | `user_id` |
| `ZERODHA_BASE_URL` | Kite base URL | No | `https://kite.zerodha.com` |
| `ZERODHA_LOGIN_URL` | Login endpoint | No | `…/api/login` |
| `ZERODHA_2FA_URL` | 2FA endpoint | No | `…/api/twofa` |
| `ZERODHA_HISTORICAL_URL` | Historical data URL template | No | Built-in template |
| `ZERODHA_KEYRING_TOKEN_KEY` | Keyring key for the auth token | No | `zerodha_auth_token` |
| `ZERODHA_KEYRING_ENCRYPTION_KEY` | Keyring key for the encryption key | No | `zerodha_encryption_key` |
| `ZERODHA_INSTRUMENT_CACHE_TTL` | Instrument cache TTL, in minutes | No | `1440` |

### Constructor arguments

Anything you can set by environment variable for credentials can also be passed to `ZerodhaDataFetcher(...)`, which takes precedence. This is useful when credentials come from somewhere other than a local `.env` file (a secrets manager, multiple accounts in one process, etc.):

```python
fetcher = ZerodhaDataFetcher(
    requests_per_second=3,        # clamped to the supported 1–10 range
    chunk_failure_mode="strict",  # "strict" (default) or "partial"
    user_id="…",
    password="…",
    totp_secret="…",
    user_type="user_id",
)
```

Other constructor arguments: `token_expiry_hours` (auth token validity, default 3) and `cache_ttl_minutes` (instrument cache TTL).

## Historical Fetch Failure Modes

A request for a long date range is split into chunks fetched in parallel. `chunk_failure_mode` controls what happens when one of those chunks fails:

- **`"strict"`** (default) — any failed chunk raises `DataFetchError` and no data is returned. Use this when gaps in the data would be a correctness problem.
- **`"partial"`** — successful chunks are returned, failed ranges are summarized in a warning log, and an exception is raised only if *every* chunk fails.

Set it on the instance or override it per call:

```python
fetcher = ZerodhaDataFetcher(chunk_failure_mode="strict")

# Override for a single call
data = fetcher.fetch_historical_data(
    "INFY", start_date, end_date, chunk_failure_mode="partial",
)
```

## Logging

`setup_logging()` configures console and (optionally) rotating file output, with independent formats for each:

```python
setup_logging(
    log_level="INFO",
    log_file="logs/zerodha_fetcher.log",
    console_format="%(asctime)s %(levelname)s %(message)s",
    file_format="%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(threadName)s | %(message)s",
)
```

- The console default is compact; the file default adds logger, function, line number, and thread name.
- Passing `log_format=...` overrides both handlers at once.
- Default date formats: `%H:%M:%S` for console, `%Y-%m-%d %H:%M:%S` for file.

## Multiple Accounts

Each `ZerodhaDataFetcher` instance authenticates independently, so you can spread a large job across several accounts by giving each fetcher its own credentials and running them on separate threads:

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from zerodha_data_fetcher import ZerodhaDataFetcher

accounts = [
    {"user_id": "…", "password": "…", "totp_secret": "…"},
    {"user_id": "…", "password": "…", "totp_secret": "…"},
]
symbols = [["RELIANCE", "INFY", "TCS"], ["SBIN", "HDFCBANK", "ICICIBANK"]]

end_date = date.today()
start_date = end_date - timedelta(days=30)

def fetch_batch(account, batch):
    fetcher = ZerodhaDataFetcher(requests_per_second=3, **account)
    return {s: fetcher.fetch_historical_data(s, start_date, end_date) for s in batch}

with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
    results = {}
    for future in [executor.submit(fetch_batch, a, b) for a, b in zip(accounts, symbols)]:
        results.update(future.result())
```

Each account is still rate-limited individually, so this raises throughput, not the per-account request rate.

## Instrument Data Caching

The package bundles a snapshot of Zerodha's instrument list and keeps a fresh copy in your local cache directory.

- On use, if the cached file is older than the TTL, the package downloads the latest list from `https://api.kite.trade/instruments`.
- If the cached file is younger than the TTL, no download is attempted.
- If a download fails, the bundled snapshot is used as a fallback and a warning is logged.
- If `ZERODHA_INSTRUMENT_CACHE_TTL` is invalid, the library logs one warning and falls back to `1440` minutes instead of crashing.

Set the TTL by environment variable (`ZERODHA_INSTRUMENT_CACHE_TTL=60`) or constructor (`ZerodhaDataFetcher(cache_ttl_minutes=60)`). Force a refresh regardless of TTL:

```python
from zerodha_data_fetcher import refresh_instruments

refresh_instruments()
```

Cache location:

- Windows: `%LOCALAPPDATA%\zerodha_data_fetcher\Cache\`
- Linux/macOS: `~/.cache/zerodha_data_fetcher/`

## API Reference

### `ZerodhaDataFetcher`

- `fetch_historical_data(ticker_token, start_date, end_date, timeframe="minute", chunk_failure_mode=None)` — fetch historical data as a DataFrame. `ticker_token` accepts an instrument token (int) or a trading symbol (str). `chunk_failure_mode` overrides the instance default for this call.
- `search_symbols(partial_name, limit=10)` — search instruments by partial name; returns a DataFrame.
- `get_instrument_info(symbol)` — instrument metadata for a symbol, when available.

### Package helpers

- `setup_logging(...)` — configure console and optional rotating file logging.
- `refresh_instruments()` — force-refresh the instrument cache, ignoring TTL.

## Error Handling

The package raises dedicated exceptions for common failure modes:

```python
from zerodha_data_fetcher import (
    AuthenticationError,
    DataFetchError,
    InvalidTickerError,
    ZerodhaAPIError,
)

try:
    data = fetcher.fetch_historical_data("INVALID", start_date, end_date)
except InvalidTickerError as exc:
    print(f"Invalid ticker: {exc}")
except AuthenticationError as exc:
    print(f"Authentication failed: {exc}")
except DataFetchError as exc:
    print(f"Data fetch failed: {exc}")
except ZerodhaAPIError as exc:           # base class for the above
    print(f"Zerodha API error: {exc}")
```

`TokenExpiredError` is also exported for callers that manage tokens directly.

## Development

Contributor setup and workflow live in [CONTRIBUTING.md](CONTRIBUTING.md); repository internals for agents and new contributors are in [AGENTS.md](AGENTS.md). Typical local workflow:

```bash
uv sync --all-extras
uv run pytest
uv run black .
uv run flake8
uv run mypy src/
```

The test suite is fully mocked — no Zerodha account or network access is needed to run it.

## Contributing

Contributions are welcome — bug fixes, docs, tests, and features. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) first, and never include real Zerodha credentials in code, issues, or examples.

## Security

See [SECURITY.md](SECURITY.md) for supported versions, private vulnerability reporting, and credential-exposure guidance.

## License

MIT. See [LICENSE](LICENSE).

## Disclaimer

This package is provided for educational and research purposes. It uses Zerodha's unofficial web endpoints; ensure your usage complies with Zerodha's terms of service and any applicable laws or regulations. The maintainers are not affiliated with Zerodha.
