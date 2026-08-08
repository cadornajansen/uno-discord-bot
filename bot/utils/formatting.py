from datetime import datetime
from typing import Optional
import discord


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


def split_message(text: str, limit: int = 2000) -> list[str]:
    """Split a long text string into chunks not exceeding the limit length.

    Prefers splitting along newline boundaries (\\n), then whitespace (space),
    and falls back to hard character splitting if a single line/token exceeds limit.

    Args:
        text: The string content to split.
        limit: Maximum character length per chunk (default: 2000).

    Returns:
        A list of non-empty string chunks.
    """
    if not text:
        return []

    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current_chunk = ""

    lines = text.split("\n")

    for line in lines:
        # If line itself is larger than limit, split it by words/chars
        if len(line) > limit:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            words = line.split(" ")
            current_line_chunk = ""

            for word in words:
                if len(word) > limit:
                    if current_line_chunk:
                        chunks.append(current_line_chunk)
                        current_line_chunk = ""
                    for i in range(0, len(word), limit):
                        chunks.append(word[i : i + limit])
                elif (
                    len(current_line_chunk) + (1 if current_line_chunk else 0) + len(word)
                    <= limit
                ):
                    current_line_chunk = (
                        f"{current_line_chunk} {word}" if current_line_chunk else word
                    )
                else:
                    chunks.append(current_line_chunk)
                    current_line_chunk = word

            if current_line_chunk:
                current_chunk = current_line_chunk
        else:
            needed_len = len(current_chunk) + (1 if current_chunk else 0) + len(line)
            if needed_len <= limit:
                current_chunk = f"{current_chunk}\n{line}" if current_chunk else line
            else:
                chunks.append(current_chunk)
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    return [c for c in chunks if c]


async def send_deferred_response(
    interaction: "discord.Interaction",
    content: str,
    limit: int = 2000,
) -> None:
    """Send text content in response to a deferred slash command interaction.

    Edits the original deferred response message with the first chunk to preserve
    the 'user used /command' invocation header in Discord, and sends any remaining
    chunks as followup messages.

    Args:
        interaction: Discord interaction object.
        content: String content to send.
        limit: Maximum character length per chunk (default: 2000).
    """
    chunks = split_message(content, limit=limit)
    if not chunks:
        await interaction.edit_original_response(content="No response generated.")
        return

    await interaction.edit_original_response(content=chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(content=chunk)

