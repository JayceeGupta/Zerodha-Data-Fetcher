from zerodha_data_fetcher.utils.config import Config


def test_defaults_used_when_env_missing(clear_zerodha_env):
    config = Config()

    assert config.ZERODHA_USER_ID == ""
    assert config.ZERODHA_PASSWORD == ""
    assert config.ZERODHA_TYPE == "user_id"
    assert config.ZERODHA_BASE_URL == "https://kite.zerodha.com/"
    assert config.ZERODHA_LOGIN_URL == "https://kite.zerodha.com/api/login"


def test_kwargs_override_env_vars(monkeypatch, clear_zerodha_env):
    monkeypatch.setenv("ZERODHA_USER_ID", "env_user")
    monkeypatch.setenv("ZERODHA_PASSWORD", "env_pass")
    monkeypatch.setenv("ZERODHA_BASE_URL", "https://env.test")

    config = Config(
        user_id="override_user",
        password="override_pass",
        base_url="https://override.test",
    )

    assert config.ZERODHA_USER_ID == "override_user"
    assert config.ZERODHA_PASSWORD == "override_pass"
    assert config.ZERODHA_BASE_URL == "https://override.test"


def test_validate_config_false_when_required_values_missing(clear_zerodha_env):
    config = Config()

    assert config.validate_config() is False


def test_validate_config_true_when_all_required_values_present(fake_config_kwargs, clear_zerodha_env):
    config = Config(**fake_config_kwargs)

    assert config.validate_config() is True


def test_get_missing_config_reports_only_missing_keys(clear_zerodha_env):
    config = Config(
        user_id="user",
        password="pass",
        user_type="user_id",
        base_url="https://example.test",
        login_url="https://example.test/login",
        two_fa_url="https://example.test/twofa",
        historical_url="https://example.test/history",
        keyring_token_key="token-key",
        keyring_encryption_key="enc-key",
    )

    assert config.get_missing_config() == ["ZERODHA_TOTP_SECRET"]


def test_to_dict_returns_expected_keys_and_values(fake_config_kwargs, clear_zerodha_env):
    config = Config(**fake_config_kwargs)

    assert config.to_dict() == {
        "user_id": "test_user",
        "password": "test_pass",
        "user_type": "user_id",
        "totp_secret": "test_totp",
        "base_url": "https://example.test",
        "login_url": "https://example.test/login",
        "two_fa_url": "https://example.test/twofa",
        "historical_url": "https://example.test/{token}/{timeframe}?user_id={userid}&from={current_date}&to={next_date}",
        "keyring_token_key": "test_token_key",
        "keyring_encryption_key": "test_encryption_key",
    }


def test_resolve_instrument_cache_ttl_uses_default_when_env_missing(clear_zerodha_env):
    assert Config.resolve_instrument_cache_ttl_minutes() == Config.DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES


def test_resolve_instrument_cache_ttl_falls_back_on_invalid_env(monkeypatch, caplog):
    monkeypatch.setenv("ZERODHA_INSTRUMENT_CACHE_TTL", "not-a-number")

    with caplog.at_level("WARNING"):
        ttl = Config.resolve_instrument_cache_ttl_minutes()

    assert ttl == Config.DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES
    assert "Invalid ZERODHA_INSTRUMENT_CACHE_TTL" in caplog.text
