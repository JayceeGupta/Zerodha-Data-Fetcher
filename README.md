# Zerodha Data Fetcher

A Python package for fetching historical data from Zerodha API with advanced features like rate limiting, authentication management, parallel data fetching, and multi-account support for massive data retrieval.

## Features

- 🚀 **Fast Parallel Data Fetching**: Concurrent requests with intelligent rate limiting
- 🔐 **Automatic Authentication**: Handles login, 2FA, and token management
- 📊 **Multiple Data Formats**: Support for minute, daily, and other timeframes
- 🛡️ **Error Handling**: Robust error handling with retry mechanisms
- 🔍 **Symbol Search**: Built-in instrument search and validation
- ⚙️ **Configurable**: Flexible configuration via environment variables or parameters
- 🏭 **Multi-Account Support**: Create multiple instances for massive parallel data retrieval
- 🔧 **Runtime Configuration Override**: Override environment variables at runtime

## Installation

```bash
pip install zerodha-data-fetcher
```

## Quick Start

### 1. Set up TOTP (Time-based OTP)

First, you need to set up TOTP for your Zerodha account. Follow this tutorial: [Zerodha TOTP Setup Guide](https://support.zerodha.com/category/trading-and-markets/general-kite/login-credentials-of-trading-platforms/articles/time-based-otp-setup)

### 2. Set up environment variables

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
```

### 3. Basic Usage

```python
from zerodha_data_fetcher import ZerodhaDataFetcher, setup_logging
from datetime import date, timedelta

# Setup logging (optional)
setup_logging(log_level="INFO", log_file="logs/zerodha_fetcher.log")

# Initialize the fetcher
fetcher = ZerodhaDataFetcher(requests_per_second=3)

# Define date range
end_date = date.today()
start_date = end_date - timedelta(days=30)

# Example 1: Fetch data using instrument token
data = fetcher.fetch_historical_data(
    ticker_token=408065,  # HDFC Bank instrument token
    start_date=start_date,
    end_date=end_date,
    timeframe="minute"
)

print(f"Retrieved {len(data)} records")
print(data.head())

# Example 2: Fetch data using symbol name
data = fetcher.fetch_historical_data(
    ticker_token="RELIANCE",
    start_date=start_date,
    end_date=end_date,
    timeframe="minute"
)

print(f"Retrieved {len(data)} records for RELIANCE")
print(data.head())

# Example 3: Search for symbols
search_results = fetcher.search_symbols("TATA", limit=5)
print("Found symbols:", search_results[['Instrument_Token', 'Name', 'Exchange']])

# Example 4: Get instrument information
instrument_info = fetcher.get_instrument_info("INFY")
print("Instrument info:", instrument_info)
```

### 4. Runtime Configuration Override

You can override environment variables during class instantiation:

```python
# Override credentials at runtime (useful when env vars become obsolete)
fetcher = ZerodhaDataFetcher(
    requests_per_second=3,
    user_id="override_user_id",
    password="override_password", 
    totp_secret="override_totp_secret",
    user_type="user_id"  # or "corporate"
)
```

## Multi-Account Parallel Processing

For massive data retrieval, you can create multiple instances with different credentials to bypass individual account rate limits:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

# Account configurations
accounts = [
    {
        "user_id": "account1_id",
        "password": "account1_password", 
        "totp_secret": "account1_totp_secret"
    },
    {
        "user_id": "account2_id",
        "password": "account2_password",
        "totp_secret": "account2_totp_secret" 
    },
    {
        "user_id": "account3_id",
        "password": "account3_password",
        "totp_secret": "account3_totp_secret"
    }
]

def fetch_data_with_account(account_config, symbols_batch):
    """Fetch data using a specific account for a batch of symbols."""
    
    fetcher = ZerodhaDataFetcher(
        requests_per_second=3,
        user_id=account_config["user_id"],
        password=account_config["password"],
        totp_secret=account_config["totp_secret"]
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
                timeframe="minute"
            )
            results[symbol] = data
            print(f"✅ Account {account_config['user_id']}: Fetched {len(data)} records for {symbol}")
        except Exception as e:
            print(f"❌ Account {account_config['user_id']}: Failed to fetch {symbol}: {e}")
            results[symbol] = None
    
    return results

# Symbols to fetch (split into batches for each account)
all_symbols = ["RELIANCE", "HDFC", "INFY", "TCS", "ICICIBANK", "SBIN", "BAJFINANCE", "BHARTIARTL", "HDFCBANK"]

# Split symbols across accounts
symbols_per_account = len(all_symbols) // len(accounts)
symbol_batches = [
    all_symbols[i:i + symbols_per_account] 
    for i in range(0, len(all_symbols), symbols_per_account)
]

# Ensure any remaining symbols are included
if len(symbol_batches) > len(accounts):
    symbol_batches[-2].extend(symbol_batches[-1])
    symbol_batches.pop()

# Execute parallel fetching
with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
    futures = []
    for i, account in enumerate(accounts):
        if i < len(symbol_batches):
            future = executor.submit(fetch_data_with_account, account, symbol_batches[i])
            futures.append(future)
    
    # Collect results
    all_results = {}
    for future in futures:
        batch_results = future.result()
        all_results.update(batch_results)

print(f"\n🎉 Completed fetching data for {len(all_results)} symbols across {len(accounts)} accounts")
```

## Instrument Data Caching

The package bundles a snapshot of Zerodha's instrument list and keeps a
fresh copy in your local cache directory.

### How it works
- On first use, the package attempts to download the latest instrument data
  from `https://api.kite.trade/instruments`.
- If the cached file is younger than the TTL (default: 1440 minutes / 24 h),
  no download is attempted.
- If the download fails (no internet, API unavailable), the bundled snapshot
  is used as a fallback and a warning is logged.

### Configuration
| Method | Example |
|--------|---------|
| Env var | `ZERODHA_INSTRUMENT_CACHE_TTL=60` (minutes) |
| Constructor | `ZerodhaDataFetcher(cache_ttl_minutes=60)` |
| Constructor | `ZerodhaInstrumentManager(cache_ttl_minutes=60)` |

### Manual refresh
```python
from zerodha_data_fetcher import refresh_instruments
refresh_instruments()  # ignores TTL, always downloads
```

Cache location:
- **Windows**: `%LOCALAPPDATA%\zerodha_data_fetcher\Cache\`
- **Linux/macOS**: `~/.cache/zerodha_data_fetcher/`

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `ZERODHA_USER_ID` | Your Zerodha user ID | **Yes** | - |
| `ZERODHA_PASSWORD` | Your Zerodha password | **Yes** | - |
| `ZERODHA_TOTP_SECRET` | TOTP secret for 2FA ([Setup Guide](https://support.zerodha.com/category/trading-and-markets/general-kite/login-credentials-of-trading-platforms/articles/time-based-otp-setup)) | **Yes** | - |
| `ZERODHA_TYPE` | Account type (user_id/corporate) | No | `user_id` |
| `ZERODHA_BASE_URL` | Zerodha base URL | No | `https://kite.zerodha.com` |
| `ZERODHA_LOGIN_URL` | Login endpoint URL | No | `https://kite.zerodha.com/api/login` |
| `ZERODHA_2FA_URL` | 2FA endpoint URL | No | `https://kite.zerodha.com/api/twofa` |
| `ZERODHA_HISTORICAL_URL` | Historical data endpoint template | No | [Default template] |
| `ZERODHA_KEYRING_TOKEN_KEY` | Keyring token storage key | No | `zerodha_auth_token` |
| `ZERODHA_KEYRING_ENCRYPTION_KEY` | Keyring encryption key | No | `zerodha_encryption_key` |
| `ZERODHA_INSTRUMENT_CACHE_TTL` | Instrument cache TTL in minutes | No | `1440` (24 h) |

**Note**: Only `ZERODHA_USER_ID`, `ZERODHA_PASSWORD`, and `ZERODHA_TOTP_SECRET` are required to work. All other variables have sensible defaults and can be overridden during class instantiation if needed.

### Class Parameters

- `requests_per_second`: API rate limit (1-10, default: 2)
- `token_expiry_hours`: Token validity period (default: 6)
- `user_id`: Override environment variable
- `password`: Override environment variable  
- `totp_secret`: Override environment variable
- `user_type`: Override environment variable
- `timeframe`: Data timeframe ('minute', 'day', etc.)

## Sample Output

When you run the basic usage example, you'll see output similar to:

```
🚀 Zerodha Data Fetcher - Basic Usage Example
==================================================

📊 Example 1: Fetching data using instrument token
----------------------------------------
Fetching data for token 408065 from 2025-08-07 to 2025-09-06
✅ Success! Retrieved 7500 records
📅 Date range: 2025-08-07 to 2025-09-05
🕐 Time range: 09:15 to 15:29

📋 Sample data:
         Date   Time    Open    High     Low   Close  Volume
0  2025-08-07  09:15  1430.0  1434.8  1429.0  1434.1   67617
1  2025-08-07  09:16  1433.3  1434.5  1432.0  1433.3   12890
2  2025-08-07  09:17  1433.4  1433.5  1432.5  1433.0   15283
3  2025-08-07  09:18  1433.5  1433.6  1430.7  1430.7   23382
4  2025-08-07  09:19  1430.9  1431.3  1430.0  1431.0   16791

📊 Example 2: Fetching data using symbol
----------------------------------------
✅ Success! Retrieved 7500 records for RELIANCE

🔍 Example 3: Searching for symbols
---------------------------------------- 
✅ Found 5 matching symbols:
      Instrument_Token        Name Exchange
9472         128102404   TATAPOWER      BSE
9478         128104452   TATAELXSI      BSE

📋 Example 4: Getting instrument information
----------------------------------------
✅ Instrument information:
  Instrument_Token: 128053508
  Name: INFY
  FullName: INFOSYS
```

## API Reference

### ZerodhaDataFetcher

Main class for fetching historical data.

#### Methods

- `fetch_historical_data(ticker_token, start_date, end_date, timeframe='minute')`: Fetch historical data
- `search_symbols(partial_name, limit=10)`: Search for trading symbols  
- `get_instrument_info(symbol)`: Get instrument information

## Error Handling

The package includes comprehensive error handling:

```python
from zerodha_data_fetcher.utils.exceptions import (
    ZerodhaAPIError,
    AuthenticationError, 
    InvalidTickerError,
    DataFetchError
)

try:
    data = fetcher.fetch_historical_data("INVALID", start_date, end_date)
except InvalidTickerError as e:
    print(f"Invalid ticker: {e}")
except AuthenticationError as e:
    print(f"Auth failed: {e}")
except DataFetchError as e:
    print(f"Data fetch failed: {e}")
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This package is for educational and research purposes. Please ensure compliance with Zerodha's terms of service and applicable regulations when using this package.

## Support

- 📖 [Documentation](https://github.com/JayceeGupta/Zerodha-Data-Fetcher#readme)
- 🐛 [Bug Reports](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/issues)
- 💬 [Discussions](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/discussions)