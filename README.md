# Zerodha Data Fetcher

[![PyPI version](https://img.shields.io/pypi/v/zerodha-data-fetcher)](https://pypi.org/project/zerodha-data-fetcher/)
[![Python versions](https://img.shields.io/pypi/pyversions/zerodha-data-fetcher)](https://pypi.org/project/zerodha-data-fetcher/)
[![Tests](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/actions/workflows/test.yml/badge.svg)](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/JayceeGupta/Zerodha-Data-Fetcher)](LICENSE)

Python package for fetching historical market data from Zerodha's Kite web APIs with built-in authentication, rate limiting, instrument lookup, caching, and multi-account workflows.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [TOTP Setup](#totp-setup)
- [Configuration](#configuration)
- [Runtime Configuration Override](#runtime-configuration-override)
- [Historical Fetch Failure Modes](#historical-fetch-failure-modes)
- [Logging](#logging)
- [Multi-Account Parallel Processing](#multi-account-parallel-processing)
- [Instrument Data Caching](#instrument-data-caching)
- [API Reference](#api-reference)
- [Error Handling](#error-handling)
- [Development](#development)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)
- [Disclaimer](#disclaimer)
- [Support](#support)

## Features

- Fast parallel historical data fetching with request pacing
- Automatic authentication flow with password, TOTP, and token handling
- Support for instrument tokens and symbol-based lookups
- Strict-by-default chunk failure handling for correctness-sensitive workloads
- Runtime overrides for environment-based configuration
- Instrument metadata search and caching
- Multi-account patterns for high-volume retrieval
- Structured logging with separate console and file formats

## Prerequisites

Before using the package, make sure you have:

- Python 3.8 or newer
- A Zerodha account with Kite access
- TOTP enabled on that account
- `pip` or `uv` available in your environment

## Installation

```bash
pip install zerodha-data-fetcher
```

For development:

```bash
uv sync --all-extras
```

## Quick Start

### TOTP Setup

Set up TOTP for your Zerodha account before using the package:

[Zerodha TOTP Setup Guide](https://support.zerodha.com/category/trading-and-markets/general-kite/login-credentials-of-trading-platforms/articles/time-based-otp-setup)

### Environment Variables

Create a `.env` file in your project root:

```env
# Required credentials
ZERODHA_USER_ID=your_user_id
ZERODHA_PASSWORD=your_password
ZERODHA_TOTP_SECRET=your_totp_secret

# Optional configurations
ZERODHA_TYPE=user_id
ZERODHA_BASE_URL=https://kite.zerodha.com
ZERODHA_LOGIN_URL=https://kite.zerodha.com/api/login
ZERODHA_2FA_URL=https://kite.zerodha.com/api/twofa
ZERODHA_HISTORICAL_URL=https://kite.zerodha.com/oms/instruments/historical/{token}/{timeframe}?user_id={userid}&oi=1&from={current_date}&to={next_date}
ZERODHA_KEYRING_TOKEN_KEY=zerodha_auth_token
ZERODHA_KEYRING_ENCRYPTION_KEY=zerodha_encryption_key
ZERODHA_INSTRUMENT_CACHE_TTL=1440
```

### Basic Usage

```python
from datetime import date, timedelta

from zerodha_data_fetcher import ZerodhaDataFetcher, setup_logging

setup_logging(log_level="INFO", log_file="logs/zerodha_fetcher.log")

fetcher = ZerodhaDataFetcher(
    requests_per_second=3,
    chunk_failure_mode="strict",
)

end_date = date.today()
start_date = end_date - timedelta(days=30)

data = fetcher.fetch_historical_data(
    ticker_token=408065,
    start_date=start_date,
    end_date=end_date,
    timeframe="minute",
)

print(f"Retrieved {len(data)} records")
print(data.head())

reliance_data = fetcher.fetch_historical_data(
    ticker_token="RELIANCE",
    start_date=start_date,
    end_date=end_date,
    timeframe="minute",
)

print(f"Retrieved {len(reliance_data)} records for RELIANCE")
print(reliance_data.head())

search_results = fetcher.search_symbols("TATA", limit=5)
print(search_results[["Instrument_Token", "Name", "Exchange"]])

instrument_info = fetcher.get_instrument_info("INFY")
print(instrument_info)
```

Authentication logs are sanitized by default. TOTP values, raw auth response bodies, headers, cookies, and encrypted token material are never written to the logs.

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
| -------- | ----------- | -------- | ------- |
| `ZERODHA_USER_ID` | Zerodha user ID | Yes | - |
| `ZERODHA_PASSWORD` | Zerodha password | Yes | - |
| `ZERODHA_TOTP_SECRET` | TOTP secret for 2FA | Yes | - |
| `ZERODHA_TYPE` | Account type (`user_id` or `corporate`) | No | `user_id` |
| `ZERODHA_BASE_URL` | Zerodha base URL | No | `https://kite.zerodha.com` |
| `ZERODHA_LOGIN_URL` | Login endpoint URL | No | `https://kite.zerodha.com/api/login` |
| `ZERODHA_2FA_URL` | 2FA endpoint URL | No | `https://kite.zerodha.com/api/twofa` |
| `ZERODHA_HISTORICAL_URL` | Historical API URL template | No | Built-in template |
| `ZERODHA_KEYRING_TOKEN_KEY` | Keyring token storage key | No | `zerodha_auth_token` |
| `ZERODHA_KEYRING_ENCRYPTION_KEY` | Keyring encryption key | No | `zerodha_encryption_key` |
| `ZERODHA_INSTRUMENT_CACHE_TTL` | Instrument cache TTL in minutes | No | `1440` |

Only `ZERODHA_USER_ID`, `ZERODHA_PASSWORD`, and `ZERODHA_TOTP_SECRET` are required for normal use.

### Class Parameters

- `requests_per_second`: API rate limit, clamped to the library's supported range
- `token_expiry_hours`: Token validity period
- `cache_ttl_minutes`: Instrument cache TTL in minutes
- `chunk_failure_mode`: `"strict"` or `"partial"`
- `user_id`: Runtime override for `ZERODHA_USER_ID`
- `password`: Runtime override for `ZERODHA_PASSWORD`
- `totp_secret`: Runtime override for `ZERODHA_TOTP_SECRET`
- `user_type`: Runtime override for `ZERODHA_TYPE`

## Runtime Configuration Override

You can override environment variables during class instantiation:

```python
fetcher = ZerodhaDataFetcher(
    requests_per_second=3,
    chunk_failure_mode="strict",
    user_id="override_user_id",
    password="override_password",
    totp_secret="override_totp_secret",
    user_type="user_id",
)
```

This is useful when credentials or account context need to be supplied at runtime instead of through a local `.env` file.

## Historical Fetch Failure Modes

Historical data fetching defaults to strict correctness.

- `chunk_failure_mode="strict"`: any failed chunk raises `DataFetchError` and no partial data is returned.
- `chunk_failure_mode="partial"`: successful chunks are returned, failed ranges are summarized in a warning log, and an exception is raised only if all chunks fail.

You can set the default on the fetcher instance or override it per call:

```python
fetcher = ZerodhaDataFetcher(chunk_failure_mode="strict")

strict_data = fetcher.fetch_historical_data(
    "INFY",
    start_date=start_date,
    end_date=end_date,
)

partial_data = fetcher.fetch_historical_data(
    "INFY",
    start_date=start_date,
    end_date=end_date,
    chunk_failure_mode="partial",
)
```

## Logging

`setup_logging()` uses separate defaults for console and file output.

- Console output is compact and human-readable, for example:

```text
(20:30:29) - [INFO] - zerodha_data_fetcher.core.data_fetcher fetch_historical_data: Data fetch completed successfully
```

- File output includes timestamp, logger, function, line number, and thread name.

Customize each handler independently:

```python
setup_logging(
    log_level="INFO",
    log_file="logs/zerodha_fetcher.log",
    console_format="%(asctime)s %(levelname)s %(message)s",
    file_format="%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(threadName)s | %(message)s",
)
```

Behavior notes:

- `log_format=...` still overrides both handlers
- `console_format` and `file_format` can be set independently when `log_format` is not provided
- Default console dates use `%H:%M:%S`
- Default file dates use `%Y-%m-%d %H:%M:%S`

## Multi-Account Parallel Processing

For large data retrieval jobs, you can create multiple fetcher instances with different credentials to spread work across accounts.

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from zerodha_data_fetcher import ZerodhaDataFetcher

accounts = [
    {
        "user_id": "account1_id",
        "password": "account1_password",
        "totp_secret": "account1_totp_secret",
    },
    {
        "user_id": "account2_id",
        "password": "account2_password",
        "totp_secret": "account2_totp_secret",
    },
    {
        "user_id": "account3_id",
        "password": "account3_password",
        "totp_secret": "account3_totp_secret",
    },
]


def fetch_data_with_account(account_config, symbols_batch):
    fetcher = ZerodhaDataFetcher(
        requests_per_second=3,
        user_id=account_config["user_id"],
        password=account_config["password"],
        totp_secret=account_config["totp_secret"],
    )

    results = {}
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    for symbol in symbols_batch:
        try:
            data = fetcher.fetch_historical_data(
                ticker_token=symbol,
                start_date=start_date,
                end_date=end_date,
                timeframe="minute",
            )
            results[symbol] = data
            print(f"Fetched {len(data)} records for {symbol} on {account_config['user_id']}")
        except Exception as exc:
            print(f"Failed to fetch {symbol} on {account_config['user_id']}: {exc}")
            results[symbol] = None

    return results


all_symbols = [
    "RELIANCE",
    "HDFC",
    "INFY",
    "TCS",
    "ICICIBANK",
    "SBIN",
    "BAJFINANCE",
    "BHARTIARTL",
    "HDFCBANK",
]

symbols_per_account = len(all_symbols) // len(accounts)
symbol_batches = [
    all_symbols[i:i + symbols_per_account]
    for i in range(0, len(all_symbols), symbols_per_account)
]

if len(symbol_batches) > len(accounts):
    symbol_batches[-2].extend(symbol_batches[-1])
    symbol_batches.pop()

with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
    futures = []
    for i, account in enumerate(accounts):
        if i < len(symbol_batches):
            futures.append(executor.submit(fetch_data_with_account, account, symbol_batches[i]))

    all_results = {}
    for future in futures:
        all_results.update(future.result())

print(f"Completed fetching data for {len(all_results)} symbols across {len(accounts)} accounts")
```

## Instrument Data Caching

The package bundles a snapshot of Zerodha's instrument list and keeps a fresh copy in your local cache directory.

### How It Works

- On first use, the package attempts to download the latest instrument data from `https://api.kite.trade/instruments`.
- If the cached file is younger than the TTL, no download is attempted.
- If the download fails, the bundled snapshot is used as a fallback and a warning is logged.

### Configuration

| Method | Example |
| ------ | ------- |
| Environment variable | `ZERODHA_INSTRUMENT_CACHE_TTL=60` |
| Constructor | `ZerodhaDataFetcher(cache_ttl_minutes=60)` |
| Constructor | `ZerodhaInstrumentManager(cache_ttl_minutes=60)` |

If `ZERODHA_INSTRUMENT_CACHE_TTL` is invalid, the library logs one warning and falls back to `1440` minutes instead of crashing.

### Manual Refresh

```python
from zerodha_data_fetcher import refresh_instruments

refresh_instruments()
```

Cache location:

- Windows: `%LOCALAPPDATA%\zerodha_data_fetcher\Cache\`
- Linux/macOS: `~/.cache/zerodha_data_fetcher/`

## API Reference

### `ZerodhaDataFetcher`

Main class for fetching historical data.

Methods:

- `fetch_historical_data(ticker_token, start_date, end_date, timeframe="minute", chunk_failure_mode=None)`: fetch historical data with strict-by-default chunk failure handling
- `search_symbols(partial_name, limit=10)`: search the instrument data for matching trading symbols
- `get_instrument_info(symbol)`: return instrument metadata for a symbol when available

### Package Helpers

- `setup_logging(...)`: configure console and optional rotating file logging
- `refresh_instruments()`: force-refresh the instrument cache, ignoring TTL

## Error Handling

The package exposes dedicated exception types for common failure modes:

```python
from zerodha_data_fetcher.utils.exceptions import (
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
except ZerodhaAPIError as exc:
    print(f"Unexpected Zerodha API error: {exc}")
```

## Development

Contributor setup and workflow guidance live in [CONTRIBUTING.md](CONTRIBUTING.md).

Typical local workflow:

```bash
uv sync --all-extras
uv run pytest
uv run black .
uv run flake8
uv run mypy src/
```

## Contributing

Contributions are welcome across bug fixes, docs, tests, and new features.

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request
- Follow the expectations in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Never include real Zerodha credentials in code, issues, or examples

## Security

Please review [SECURITY.md](SECURITY.md) for supported versions, private vulnerability reporting, and credential exposure guidance.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Disclaimer

This package is for educational and research purposes. Make sure your usage complies with Zerodha's terms of service and any applicable laws or regulations.

## Support

- Documentation: https://github.com/JayceeGupta/Zerodha-Data-Fetcher#readme
- Bug reports: https://github.com/JayceeGupta/Zerodha-Data-Fetcher/issues
- Discussions: https://github.com/JayceeGupta/Zerodha-Data-Fetcher/discussions
