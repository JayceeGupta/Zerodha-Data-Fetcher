import logging
from datetime import date

import pytest

from zerodha_data_fetcher.core import auth as auth_module
from zerodha_data_fetcher.core.token_generator import ZerodhaTokenGenerator


@pytest.fixture
def memory_keyring(monkeypatch):
    store = {}

    def get_password(service, username):
        return store.get((service, username))

    def set_password(service, username, password):
        store[(service, username)] = password

    def delete_password(service, username):
        store.pop((service, username), None)

    monkeypatch.setattr(auth_module.keyring, "get_password", get_password)
    monkeypatch.setattr(auth_module.keyring, "set_password", set_password)
    monkeypatch.setattr(auth_module.keyring, "delete_password", delete_password)
    return store


@pytest.fixture
def auth_manager_factory(monkeypatch, fake_config_kwargs):
    class FakeTokenGenerator:
        def __init__(self, config):
            self.config = config

        def generate_auth_token(self):
            return "generated-token"

    class FakeTokenEncryption:
        def __init__(self, encryption_key):
            self.encryption_key = encryption_key

        def encrypt_token(self, token):
            return f"enc:{token}"

        def decrypt_token(self, encrypted_token):
            return encrypted_token.replace("enc:", "", 1)

    monkeypatch.setattr(auth_module, "ZerodhaTokenGenerator", FakeTokenGenerator)
    monkeypatch.setattr(auth_module, "TokenEncryption", FakeTokenEncryption)

    def factory(**overrides):
        config = auth_module.Config(**{**fake_config_kwargs, **overrides})
        return auth_module.AuthenticationManager(config=config)

    return factory


def test_get_auth_token_uses_user_scoped_cache(
    auth_manager_factory, memory_keyring, monkeypatch
):
    manager = auth_manager_factory(user_id="user_one")

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2024, 1, 2)

    monkeypatch.setattr(auth_module, "date", FakeDate)
    today = FakeDate.today().strftime("%Y-%m-%d")

    memory_keyring[(manager.token_key, "token:user_one")] = "enc:cached-token"
    memory_keyring[(manager.token_key, "date:user_one")] = today
    memory_keyring[(manager.token_key, "timestamp:user_one")] = "100"
    monkeypatch.setattr(auth_module.time, "time", lambda: 101)

    assert manager.get_auth_token() == "cached-token"


def test_get_auth_token_does_not_reuse_other_users_scoped_cache(
    auth_manager_factory, memory_keyring
):
    manager = auth_manager_factory(user_id="user_two")
    today = date.today().strftime("%Y-%m-%d")

    memory_keyring[(manager.token_key, "token:user_one")] = "enc:wrong-user-token"
    memory_keyring[(manager.token_key, "date:user_one")] = today
    memory_keyring[(manager.token_key, "timestamp:user_one")] = "100"
    manager._generate_new_token = lambda: "fresh-token"

    assert manager.get_auth_token() == "fresh-token"


def test_get_auth_token_migrates_matching_legacy_entries(
    auth_manager_factory, memory_keyring, monkeypatch
):
    manager = auth_manager_factory(user_id="legacy_user")

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2024, 1, 2)

    monkeypatch.setattr(auth_module, "date", FakeDate)
    today = FakeDate.today().strftime("%Y-%m-%d")

    memory_keyring[(manager.token_key, "token")] = "enc:legacy-token"
    memory_keyring[(manager.token_key, "date")] = today
    memory_keyring[(manager.token_key, "timestamp")] = "100"
    memory_keyring[(manager.token_key, "userid")] = "legacy_user"
    monkeypatch.setattr(auth_module.time, "time", lambda: 101)

    assert manager.get_auth_token() == "legacy-token"
    assert (
        memory_keyring[(manager.token_key, "token:legacy_user")] == "enc:legacy-token"
    )
    assert (manager.token_key, "token") not in memory_keyring


def test_invalidate_token_deletes_current_user_and_legacy_entries(
    auth_manager_factory, memory_keyring
):
    manager = auth_manager_factory(user_id="cleanup_user")

    memory_keyring[(manager.token_key, "token:cleanup_user")] = "enc:token"
    memory_keyring[(manager.token_key, "date:cleanup_user")] = "2024-01-01"
    memory_keyring[(manager.token_key, "timestamp:cleanup_user")] = "1"
    memory_keyring[(manager.token_key, "token")] = "enc:legacy"
    memory_keyring[(manager.token_key, "date")] = "2024-01-01"
    memory_keyring[(manager.token_key, "timestamp")] = "1"
    memory_keyring[(manager.token_key, "userid")] = "cleanup_user"

    manager.invalidate_token()

    assert memory_keyring == {}


def test_generate_auth_token_does_not_log_sensitive_values(
    monkeypatch, fake_config_kwargs, caplog
):
    class ConfigStub:
        def __init__(self):
            self.ZERODHA_USER_ID = fake_config_kwargs["user_id"]
            self.ZERODHA_PASSWORD = fake_config_kwargs["password"]
            self.ZERODHA_TYPE = fake_config_kwargs["user_type"]
            self.ZERODHA_TOTP_SECRET = fake_config_kwargs["totp_secret"]
            self.ZERODHA_BASE_URL = fake_config_kwargs["base_url"]
            self.ZERODHA_LOGIN_URL = fake_config_kwargs["login_url"]
            self.ZERODHA_2FA_URL = fake_config_kwargs["two_fa_url"]

        def validate_config(self):
            return True

    class ResponseStub:
        def __init__(self, content=b"{}", status_code=200, text="RAW_LOGIN_RESPONSE"):
            self.content = content
            self.status_code = status_code
            self.text = text
            self.headers = {"Set-Cookie": "cookie-secret"}

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.cookies = {"enctoken": "secret-cookie-value"}

        def get(self, _url):
            return ResponseStub()

        def post(self, url, data, headers):
            if "login" in url:
                return ResponseStub(content=b'{"data":{"request_id":"req-1"}}')
            return ResponseStub(content=b'{"status":"ok"}')

    generator = ZerodhaTokenGenerator(config=ConfigStub())
    monkeypatch.setattr(
        "zerodha_data_fetcher.core.token_generator.Session", FakeSession
    )
    monkeypatch.setattr(generator, "get_totp", lambda _secret="": "654321")

    with caplog.at_level(logging.DEBUG):
        token = generator.generate_auth_token()

    assert token == "secret-cookie-value"
    assert "654321" not in caplog.text
    assert "RAW_LOGIN_RESPONSE" not in caplog.text
    assert "cookie-secret" not in caplog.text
    assert "secret-cookie-value" not in caplog.text
