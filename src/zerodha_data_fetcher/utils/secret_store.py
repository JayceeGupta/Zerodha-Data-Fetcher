"""Credential persistence with a headless-safe fallback.

Primary storage is the OS keyring (the same behaviour the library has always
had on desktop machines). On systems without an available keyring backend —
headless Linux servers, minimal Docker images, CI runners — ``keyring`` raises
:class:`keyring.errors.NoKeyringError`. Rather than crash the first login, this
module transparently falls back to a JSON file under the user data directory,
created with owner-only permissions (``0600``).

The fallback trades keyring-grade protection for availability: in file mode,
secrets are protected only by filesystem permissions, not by an OS secret
service. Control the behaviour with the ``ZERODHA_TOKEN_STORE`` environment
variable:

* ``auto`` (default) — try the keyring, fall back to the file store if no
  backend is available.
* ``keyring`` — use the keyring only; raise if no backend is present (never
  writes secrets to disk).
* ``file`` — always use the file store, skipping the keyring entirely.

Override the file location with ``ZERODHA_TOKEN_STORE_PATH``.

All three functions mirror the ``keyring`` API used by the rest of the package
(:func:`get_password`, :func:`set_password`, :func:`delete_password`), so call
sites treat this module as a drop-in replacement for ``keyring``.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

import keyring
from keyring.errors import KeyringError
from platformdirs import user_data_path

logger = logging.getLogger(__name__)

_MODE_ENV = "ZERODHA_TOKEN_STORE"
_PATH_ENV = "ZERODHA_TOKEN_STORE_PATH"
_CREDENTIALS_FILENAME = "credentials.json"
_KEY_SEPARATOR = "\x00"

# Guard file reads/writes; keyring is expected to be thread-safe itself.
_file_lock = Lock()
# Emit the "falling back to file store" warning only once per process.
_warned_fallback = False


def _mode() -> str:
    """Return the configured storage mode (``auto`` / ``keyring`` / ``file``)."""
    return (os.getenv(_MODE_ENV) or "auto").strip().lower() or "auto"


def _file_path() -> Path:
    """Resolve the file-store path, honouring the override env var."""
    override = os.getenv(_PATH_ENV)
    if override:
        return Path(override)
    return user_data_path("zerodha_data_fetcher") / _CREDENTIALS_FILENAME


def _entry_key(service: str, username: str) -> str:
    """Build the flat dict key for a ``(service, username)`` pair."""
    return f"{service}{_KEY_SEPARATOR}{username}"


def _warn_fallback(exc: BaseException) -> None:
    """Warn once that the keyring is unavailable and the file store is in use."""
    global _warned_fallback
    if not _warned_fallback:
        logger.warning(
            "No OS keyring backend available (%s); falling back to the file "
            "token store at %s. Secrets there are protected only by file "
            "permissions. Set ZERODHA_TOKEN_STORE=keyring to require a keyring "
            "instead.",
            exc,
            _file_path(),
        )
        _warned_fallback = True


def _read_store() -> Dict[str, str]:
    """Load the file store, returning an empty mapping if absent/unreadable."""
    path = _file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupt/partial file: treat as empty, don't crash
        logger.warning("Token store %s is unreadable (%s); ignoring it.", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _write_store(data: Dict[str, str]) -> None:
    """Atomically write the file store with owner-only permissions."""
    path = _file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, stat.S_IRWXU)  # 0700; best effort (no-op on Windows)
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    tmp.replace(path)  # atomic; inherits the tmp file's permissions


def _file_get(service: str, username: str) -> Optional[str]:
    with _file_lock:
        return _read_store().get(_entry_key(service, username))


def _file_set(service: str, username: str, password: str) -> None:
    with _file_lock:
        data = _read_store()
        data[_entry_key(service, username)] = password
        _write_store(data)


def _file_delete(service: str, username: str) -> None:
    with _file_lock:
        data = _read_store()
        if data.pop(_entry_key(service, username), None) is not None:
            _write_store(data)


def get_password(service: str, username: str) -> Optional[str]:
    """Return a stored secret, or ``None`` if absent.

    In ``auto`` mode, tries the keyring first and falls back to the file store
    when no keyring backend is available.
    """
    mode = _mode()
    if mode == "file":
        return _file_get(service, username)
    if mode == "keyring":
        return keyring.get_password(service, username)
    try:
        return keyring.get_password(service, username)
    except KeyringError as exc:
        _warn_fallback(exc)
        return _file_get(service, username)


def set_password(service: str, username: str, password: str) -> None:
    """Persist a secret, using the keyring or the file-store fallback."""
    mode = _mode()
    if mode == "file":
        _file_set(service, username, password)
        return
    if mode == "keyring":
        keyring.set_password(service, username, password)
        return
    try:
        keyring.set_password(service, username, password)
    except KeyringError as exc:
        _warn_fallback(exc)
        _file_set(service, username, password)


def delete_password(service: str, username: str) -> None:
    """Delete a stored secret from the keyring or the file-store fallback."""
    mode = _mode()
    if mode == "file":
        _file_delete(service, username)
        return
    if mode == "keyring":
        keyring.delete_password(service, username)
        return
    try:
        keyring.delete_password(service, username)
    except KeyringError as exc:
        _warn_fallback(exc)
        _file_delete(service, username)
