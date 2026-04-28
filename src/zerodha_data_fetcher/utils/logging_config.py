"""Logging configuration setup for Zerodha Data Fetcher."""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

DEFAULT_CONSOLE_FORMAT = (
    "(%(asctime)s) - [%(levelname)s] - %(name)s %(funcName)s: %(message)s"
)
DEFAULT_FILE_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | "
    "%(threadName)s | %(message)s"
)


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_format: Optional[str] = None,
    console_format: Optional[str] = None,
    file_format: Optional[str] = None,
    console_date_format: str = "%H:%M:%S",
    file_date_format: str = "%Y-%m-%d %H:%M:%S",
    max_file_size: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """
    Set up logging configuration for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file. If None, logs only to console.
        log_format: Backward-compatible format applied to both console and file handlers.
        console_format: Optional console-only log format.
        file_format: Optional file-only log format.
        console_date_format: Date format for console logs.
        file_date_format: Date format for file logs.
        max_file_size: Maximum size of log file before rotation (bytes).
        backup_count: Number of backup files to keep.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    if log_format is not None:
        resolved_console_format = log_format
        resolved_file_format = log_format
    else:
        resolved_console_format = console_format or DEFAULT_CONSOLE_FORMAT
        resolved_file_format = file_format or DEFAULT_FILE_FORMAT

    console_formatter = logging.Formatter(
        resolved_console_format, datefmt=console_date_format
    )
    file_formatter = logging.Formatter(resolved_file_format, datefmt=file_date_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("keyring").setLevel(logging.WARNING)

    logging.getLogger(__name__).debug(
        "Logging configured - level=%s, file=%s",
        log_level,
        log_file or "console only",
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name."""
    return logging.getLogger(name)


def setup_logging_config():
    """Backward compatibility function for existing code."""
    setup_logging()
