import zerodha_data_fetcher


def test_package_imports_core_public_api():
    assert hasattr(zerodha_data_fetcher, "ZerodhaDataFetcher")
    assert hasattr(zerodha_data_fetcher, "Config")
    assert hasattr(zerodha_data_fetcher, "InvalidTickerError")
