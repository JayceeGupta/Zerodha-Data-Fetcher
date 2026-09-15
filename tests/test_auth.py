import logging
import threading
import time as time_module
from datetime import date

import pytest

from zerodha_data_fetcher.core import auth as auth_module
from zerodha_data_fetcher.core.token_generator import ZerodhaTokenGenerator


@pytest.fixture(autouse=True)
def _reset_auth_memory_cache():
    """Keep the process-global in-memory token cache from leaking across tests."""
    auth_module.AuthenticationManager.clear_memory_cache()
    yield
    auth_module.AuthenticationManager.clear_memory_cache()


@pytest.fixture
def memory_keyring(monkeypatch):
    store = {}

    def get_password(service, username):
        return store.get((service, username))

    def set_password(service, username, password):
        store[(service, username)] = password

    def delete_password(service, username):
        store.pop((service, username), None)

    monkeypatch.setattr(auth_module.secret_store, "get_password", get_password)
    monkeypatch.setattr(auth_module.secret_store, "set_password", set_password)
    monkeypatch.setattr(auth_module.secret_store, "delete_password", delete_password)
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


def test_get_auth_token_serves_second_call_from_in_memory_cache(
    auth_manager_factory, memory_keyring, monkeypatch
):
    manager = auth_manager_factory(user_id="mem_user")

    reads = {"count": 0}
    patched_get = auth_module.secret_store.get_password

    def counting_get(service, username):
        reads["count"] += 1
        return patched_get(service, username)

    monkeypatch.setattr(auth_module.secret_store, "get_password", counting_get)
    manager.token_generator.generate_auth_token = lambda: "gen-token"

    first = manager.get_auth_token()
    reads_after_first = reads["count"]
    second = manager.get_auth_token()

    assert first == "gen-token"
    assert second == "gen-token"
    # The second call is served from the in-memory cache without any
    # further keyring reads (the multi-threaded hot-path optimization).
    assert reads_after_first > 0
    assert reads["count"] == reads_after_first


def test_concurrent_expired_auth_generates_token_only_once(
    auth_manager_factory, memory_keyring
):
    manager = auth_manager_factory(user_id="race_user")

    calls = {"count": 0}
    counter_lock = threading.Lock()

    def slow_generate():
        with counter_lock:
            calls["count"] += 1
        # Widen the race window so all threads pile up behind the refresh.
        time_module.sleep(0.05)
        return "race-token"

    manager.token_generator.generate_auth_token = slow_generate

    results = []
    results_lock = threading.Lock()

    def worker():
        token = manager.get_auth_token()
        with results_lock:
            results.append(token)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Exactly one login flow runs even though ten threads asked at once.
    assert calls["count"] == 1
    assert results == ["race-token"] * 10


def test_invalidate_token_clears_in_memory_cache(auth_manager_factory, memory_keyring):
    manager = auth_manager_factory(user_id="inv_user")

    gen_calls = {"count": 0}

    def generate():
        gen_calls["count"] += 1
        return f"token-{gen_calls['count']}"

    manager.token_generator.generate_auth_token = generate

    first = manager.get_auth_token()
    manager.invalidate_token()
    second = manager.get_auth_token()

    assert first == "token-1"
    # After invalidation the cached token must not be reused.
    assert second == "token-2"
    assert gen_calls["count"] == 2


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
