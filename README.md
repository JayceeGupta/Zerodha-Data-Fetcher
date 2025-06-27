# Zerodha Data Fetcher

A Python package for fetching historical data from Zerodha API with advanced features like rate limiting, authentication management, and parallel data fetching.

## Features

- 🚀 **Fast Parallel Data Fetching**: Concurrent requests with intelligent rate limiting
- 🔐 **Automatic Authentication**: Handles login, 2FA, and token management
- 📊 **Multiple Data Formats**: Support for minute, daily, and other timeframes
- 🛡️ **Error Handling**: Robust error handling with retry mechanisms
- 🔍 **Symbol Search**: Built-in instrument search and validation
- ⚙️ **Configurable**: Flexible configuration via environment variables or parameters

## Installation

```bash
pip install zerodha-data-fetcher
```

## Quick Start

### 1. Set up environment variables

Create a `.env` file in your project root:

```env
ZERODHA_USER_ID=your_user_id
ZERODHA_PASSWORD=your_password
ZERODHA_USER_TYPE=individual
ZERODHA_TOTP_SECRET=your_totp_secret
```

### 2. Basic Usage

```python
from zerodha_data_fetcher import ZerodhaDataFetcher
from datetime import date, timedelta

# Initialize the fetcher
fetcher = ZerodhaDataFetcher(requests_per_second=2)

# Fetch historical data
end_date = date.today()
start_date = end_date - timedelta(days=30)

# Using symbol (recommended)
data = fetcher.fetch_historical_data(
    ticker_token="RELIANCE",
    start_date=start_date,
    end_date=end_date,
    timeframe="minute"
)

# Using instrument token
data = fetcher.fetch_historical_data(
    ticker_token=408065,  # HDFC Bank
    start_date=start_date,
    end_date=end_date,
    timeframe="minute"
)

print(data.head())
```

### 3. Advanced Usage

```python
# Custom configuration
fetcher = ZerodhaDataFetcher(
    requests_per_second=3,
    token_expiry_hours=6,
    user_id="custom_user_id",  # Override env var
    password="custom_password"  # Override env var
)

# Search for symbols
results = fetcher.search_symbols("HDFC", limit=5)
print(results)

# Get instrument info
info = fetcher.get_instrument_info("RELIANCE")
print(info)
```

## Configuration

### Environment Variables

| Variable                           | Description                         | Required |
| ---------------------------------- | ----------------------------------- | -------- |
| `ZERODHA_USER_ID`                | Your Zerodha user ID                | Yes      |
| `ZERODHA_PASSWORD`               | Your Zerodha password               | Yes      |
| `ZERODHA_USER_TYPE`              | Account type (individual/corporate) | Yes      |
| `ZERODHA_TOTP_SECRET`            | TOTP secret for 2FA                 | Yes      |
| `ZERODHA_KEYRING_TOKEN_KEY`      | Keyring token key                   | No       |
| `ZERODHA_KEYRING_ENCRYPTION_KEY` | Keyring encryption key              | No       |

### Parameters

- `requests_per_second`: API rate limit (1-10, default: 2)
- `token_expiry_hours`: Token validity period (default: 6)
- `timeframe`: Data timeframe ('minute', 'day', etc.)

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

```

```
