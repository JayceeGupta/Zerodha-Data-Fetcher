import logging
import logging.handlers
import re

from zerodha_data_fetcher.utils.logging_config import setup_logging


def _get_handlers():
    root = logging.getLogger()
    console_handler = next(
        handler
        for handler in root.handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.handlers.RotatingFileHandler)
    )
    file_handler = next(
        (handler for handler in root.handlers if isinstance(handler, logging.handlers.RotatingFileHandler)),
        None,
    )
    return console_handler, file_handler


def _make_record():
    record = logging.LogRecord(
        name="zerodha_data_fetcher.core.data_fetcher",
        level=logging.INFO,
        pathname=__file__,
        lineno=466,
        msg="Data fetch completed successfully",
        args=(),
        exc_info=None,
        func="fetch_historical_data",
    )
    record.threadName = "MainThread"
    return record


def test_setup_logging_default_formats_split_console_and_file(tmp_path):
    setup_logging(log_level="INFO", log_file=str(tmp_path / "app.log"))
    console_handler, file_handler = _get_handlers()
    record = _make_record()

    console_output = console_handler.format(record)
    file_output = file_handler.format(record)

    assert re.match(
        r"^\(\d{2}:\d{2}:\d{2}\) - \[INFO\] - zerodha_data_fetcher\.core\.data_fetcher fetch_historical_data: Data fetch completed successfully$",
        console_output,
    )
    assert re.match(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| INFO \| zerodha_data_fetcher\.core\.data_fetcher \| fetch_historical_data:466 \| MainThread \| Data fetch completed successfully$",
        file_output,
    )


def test_setup_logging_log_format_overrides_both_handlers(tmp_path):
    setup_logging(log_level="INFO", log_file=str(tmp_path / "app.log"), log_format="%(levelname)s %(message)s")
    console_handler, file_handler = _get_handlers()
    record = _make_record()

    assert console_handler.format(record) == "INFO Data fetch completed successfully"
    assert file_handler.format(record) == "INFO Data fetch completed successfully"


def test_setup_logging_console_and_file_formats_override_independently(tmp_path):
    setup_logging(
        log_level="INFO",
        log_file=str(tmp_path / "app.log"),
        console_format="CONSOLE %(message)s",
        file_format="FILE %(funcName)s:%(lineno)d %(message)s",
    )
    console_handler, file_handler = _get_handlers()
    record = _make_record()

    assert console_handler.format(record) == "CONSOLE Data fetch completed successfully"
    assert file_handler.format(record) == "FILE fetch_historical_data:466 Data fetch completed successfully"
