from datetime import datetime
from typing import Optional


def format_latency(latency_seconds: float) -> str:
    """Format bot WebSocket latency in milliseconds.

    Args:
        latency_seconds: Latency in seconds (e.g. from bot.latency).

    Returns:
        Formatted string like "42ms".
    """
    ms = round(latency_seconds * 1000)
    return f"{ms}ms"


def format_timestamp(dt: Optional[datetime], style: str = "F") -> str:
    """Format a datetime into Discord Markdown timestamp syntax.

    Args:
        dt: Datetime object to format.
        style: Discord timestamp style flag (e.g., 'F' for long date/time, 'R' for relative).

    Returns:
        Formatted Discord timestamp tag string, or 'Unknown' if dt is None.
    """
    if dt is None:
        return "Unknown"
    unix_timestamp = int(dt.timestamp())
    return f"<t:{unix_timestamp}:{style}>"
