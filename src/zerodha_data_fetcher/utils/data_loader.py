"""Utility to load package data files with local caching and auto-refresh."""

import os
import time
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from platformdirs import user_cache_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_INSTRUMENT_FILENAME = "Kite_Instrument_ID.csv"
_INSTRUMENT_URL = "https://api.kite.trade/instruments"
_DEFAULT_TTL_MINUTES = 1440  # 24 hours — matches Zerodha's daily update cadence
_DOWNLOAD_TIMEOUT = 60  # seconds


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_package_data_path(filename: str) -> Path:
    """
    Get path to a data file bundled inside the package.

    Args:
        filename: Name of the data file

    Returns:
        Path to the data file
    """
    current_dir = Path(__file__).parent
    data_dir = current_dir / "data"
    return data_dir / filename


def get_cache_path(filename: str = _INSTRUMENT_FILENAME) -> Path:
    """
    Return the platform-appropriate cache path for *filename*.

    - Windows : ``%LOCALAPPDATA%\\zerodha_data_fetcher\\Cache\\<filename>``
    - Linux/macOS: ``~/.cache/zerodha_data_fetcher/<filename>``

    The parent directory is created automatically if it doesn't exist.
    """
    cache_dir = user_cache_path("zerodha_data_fetcher")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / filename


# ---------------------------------------------------------------------------
# Cache age
# ---------------------------------------------------------------------------

def get_cache_age_minutes(path: Path) -> float:
    """
    Return the age of *path* in minutes.

    If the file does not exist, returns ``float('inf')``.
    """
    if not path.exists():
        return float("inf")
    mtime = path.stat().st_mtime
    return (time.time() - mtime) / 60.0


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def download_instruments(dest: Path) -> bool:
    """
    Download the latest instrument CSV from Zerodha and save to *dest*.

    Args:
        dest: Destination file path.

    Returns:
        ``True`` on success, ``False`` on any failure (network, I/O, etc.).
    """
    try:
        logger.info("Downloading instrument data from %s …", _INSTRUMENT_URL)
        resp = requests.get(_INSTRUMENT_URL, timeout=_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        logger.info("Instrument data saved to %s (%d bytes)", dest, len(resp.content))
        return True
    except Exception as exc:
        logger.warning("Failed to download instrument data: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_instrument_data(
    filename: Optional[str] = None,
    cache_ttl_minutes: Optional[int] = None,
) -> pd.DataFrame:
    """
    Load instrument data with automatic caching.

    Resolution order:
      1. Check the local cache directory (``platformdirs``).
      2. If the cached file is missing **or** older than *cache_ttl_minutes*,
         attempt to download a fresh copy from Zerodha.
      3. If the download fails, fall back to the **bundled** CSV shipped with
         the package.

    Args:
        filename: CSV filename (defaults to the bundled instrument file).
        cache_ttl_minutes: Time-to-live for the cached file in minutes.
            ``None`` → read from ``ZERODHA_INSTRUMENT_CACHE_TTL`` env var,
            then fall back to 1440 (24 h).

    Returns:
        DataFrame with instrument data.

    Raises:
        FileNotFoundError: If neither cache, download, nor bundled file
            can be loaded.
    """
    if filename is None:
        filename = _INSTRUMENT_FILENAME

    # Resolve TTL
    if cache_ttl_minutes is None:
        env_ttl = os.getenv("ZERODHA_INSTRUMENT_CACHE_TTL")
        cache_ttl_minutes = int(env_ttl) if env_ttl is not None else _DEFAULT_TTL_MINUTES

    cache_file = get_cache_path(filename)
    age = get_cache_age_minutes(cache_file)

    # Happy path: cache is fresh
    if age < cache_ttl_minutes:
        logger.debug(
            "Using cached instrument data (%s, age %.0f min, TTL %d min)",
            cache_file, age, cache_ttl_minutes,
        )
        try:
            return pd.read_csv(cache_file)
        except Exception as exc:
            logger.warning("Cached file unreadable (%s), will re-download.", exc)

    # Cache stale / missing / corrupt → try to download
    if download_instruments(cache_file):
        try:
            return pd.read_csv(cache_file)
        except Exception as exc:
            logger.warning("Downloaded file unreadable (%s), falling back to bundled.", exc)

    # Last resort: bundled CSV inside the package
    bundled = get_package_data_path(filename)
    if bundled.exists():
        logger.warning(
            "Using bundled instrument data as fallback (%s)", bundled,
        )
        return pd.read_csv(bundled)

    raise FileNotFoundError(
        f"Instrument data file not found: tried cache ({cache_file}), "
        f"download ({_INSTRUMENT_URL}), and bundled ({bundled})."
    )


def get_default_instrument_path() -> str:
    """Get the default path to the bundled instrument data file."""
    return str(get_package_data_path(_INSTRUMENT_FILENAME))
