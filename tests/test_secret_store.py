"""Tests for the keyring-with-file-fallback secret store.

Nothing here touches a real OS keyring: the ``keyring`` calls inside
``secret_store`` are monkeypatched, and the file store is redirected to a
temporary path via ``ZERODHA_TOKEN_STORE_PATH``.
"""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest
from keyring.errors import NoKeyringError, PasswordSetError

from zerodha_data_fetcher.utils import secret_store


@pytest.fixture
def file_store(tmp_path, monkeypatch):
    """Point the file store at a temp file and default to ``auto`` mode."""
    path = tmp_path / "credentials.json"
    monkeypatch.setenv("ZERODHA_TOKEN_STORE_PATH", str(path))
    monkeypatch.delenv("ZERODHA_TOKEN_STORE", raising=False)
    monkeypatch.setattr(secret_store, "_warned_fallback", False)
    return path


@pytest.fixture
def working_keyring(monkeypatch):
    """A fully functional in-memory keyring backend."""
    store = {}
    monkeypatch.setattr(
        secret_store.keyring,
        "get_password",
        lambda service, user: store.get((service, user)),
    )
    monkeypatch.setattr(
        secret_store.keyring,
        "set_password",
        lambda service, user, pw: store.__setitem__((service, user), pw),
    )
    monkeypatch.setattr(
        secret_store.keyring,
        "delete_password",
        lambda service, user: store.pop((service, user), None),
    )
    return store


@pytest.fixture
def no_keyring(monkeypatch):
    """A keyring that behaves like a headless box with no backend."""

    def _raise(*_args, **_kwargs):
        raise NoKeyringError("No recommended backend was available")

    monkeypatch.setattr(secret_store.keyring, "get_password", _raise)
    monkeypatch.setattr(secret_store.keyring, "set_password", _raise)
    monkeypatch.setattr(secret_store.keyring, "delete_password", _raise)


def test_auto_uses_keyring_when_available(file_store, working_keyring):
    secret_store.set_password("svc", "user", "secret")
    assert working_keyring[("svc", "user")] == "secret"
    assert secret_store.get_password("svc", "user") == "secret"
    # Keyring worked, so nothing should have been written to disk.
    assert not file_store.exists()


def test_auto_falls_back_to_file_when_no_backend(file_store, no_keyring):
    secret_store.set_password("svc", "user", "secret")
    assert file_store.exists()
    assert secret_store.get_password("svc", "user") == "secret"

    secret_store.delete_password("svc", "user")
    assert secret_store.get_password("svc", "user") is None


def test_keyring_mode_does_not_fall_back(file_store, no_keyring, monkeypatch):
    monkeypatch.setenv("ZERODHA_TOKEN_STORE", "keyring")
    with pytest.raises(NoKeyringError):
        secret_store.set_password("svc", "user", "secret")
    assert not file_store.exists()


def test_file_mode_skips_keyring(file_store, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("keyring must not be touched in file mode")

    monkeypatch.setenv("ZERODHA_TOKEN_STORE", "file")
    monkeypatch.setattr(secret_store.keyring, "get_password", _boom)
    monkeypatch.setattr(secret_store.keyring, "set_password", _boom)

    secret_store.set_password("svc", "user", "secret")
    assert secret_store.get_password("svc", "user") == "secret"


def test_corrupt_file_is_ignored(file_store, no_keyring):
    file_store.write_text("this is not json", encoding="utf-8")
    assert secret_store.get_password("svc", "user") is None
    # A subsequent write should recover the store rather than crash.
    secret_store.set_password("svc", "user", "secret")
    assert secret_store.get_password("svc", "user") == "secret"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions only")
def test_file_store_is_owner_only(file_store, no_keyring):
    secret_store.set_password("svc", "user", "secret")
    mode = stat.S_IMODE(os.stat(file_store).st_mode)
    assert mode == 0o600


def test_file_store_round_trips_via_json(file_store, no_keyring):
    secret_store.set_password("svc", "user", "secret")
    data = json.loads(file_store.read_text(encoding="utf-8"))
    assert data == {f"svc{secret_store._KEY_SEPARATOR}user": "secret"}


def test_operational_keyring_error_does_not_fall_back(file_store, monkeypatch):
    """A working-but-failing keyring must not silently downgrade to disk."""

    def _raise(*_args, **_kwargs):
        raise PasswordSetError("keyring is present but locked")

    monkeypatch.setattr(secret_store.keyring, "set_password", _raise)
    with pytest.raises(PasswordSetError):
        secret_store.set_password("svc", "user", "secret")
    # The secret must not have leaked to the plaintext file store.
    assert not file_store.exists()


@pytest.mark.parametrize("bad_mode", ["keyring-only", "disk", "yes"])
def test_invalid_mode_raises(file_store, monkeypatch, bad_mode):
    monkeypatch.setenv("ZERODHA_TOKEN_STORE", bad_mode)
    with pytest.raises(ValueError):
        secret_store.get_password("svc", "user")


def test_mode_is_whitespace_and_case_insensitive(
    file_store, working_keyring, monkeypatch
):
    """`_mode()` normalises casing/whitespace before validating."""
    monkeypatch.setenv("ZERODHA_TOKEN_STORE", "  KEYRING  ")
    secret_store.set_password("svc", "user", "secret")
    assert working_keyring[("svc", "user")] == "secret"
