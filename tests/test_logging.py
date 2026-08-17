import logging
from bot.client import ColoredConsoleFormatter


def test_colored_formatter_applies_red_to_error_and_critical():
    formatter = ColoredConsoleFormatter("%(levelname)s: %(message)s")
    
    error_record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Database connection failed",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(error_record)
    assert "\033[91m" in formatted
    assert formatted.endswith("\033[0m")
    assert "Database connection failed" in formatted

    critical_record = logging.LogRecord(
        name="test",
        level=logging.CRITICAL,
        pathname="",
        lineno=0,
        msg="Fatal system crash",
        args=(),
        exc_info=None,
    )
    formatted_crit = formatter.format(critical_record)
    assert "\033[91m" in formatted_crit


def test_colored_formatter_applies_yellow_to_warning():
    formatter = ColoredConsoleFormatter("%(levelname)s: %(message)s")
    
    warning_record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="Timeout exceeded, triggering fallback",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(warning_record)
    assert "\033[93m" in formatted
    assert "Timeout exceeded" in formatted


def test_colored_formatter_applies_green_to_info():
    formatter = ColoredConsoleFormatter("%(levelname)s: %(message)s")
    
    info_record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="AI request completed (request_id=123, latency_ms=1200)",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(info_record)
    assert "\033[92m" in formatted
    assert "AI request completed" in formatted
