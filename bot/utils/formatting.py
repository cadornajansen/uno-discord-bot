from datetime import datetime
from typing import Optional
import discord


MAX_DISCORD_CHUNK_CHARS = 1900


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


def _find_split_position(text: str, limit: int) -> int:
    """Find the best content-preserving split position within ``limit``."""
    for separator in ("\n\n", "\n", ". "):
        index = text.rfind(separator, 0, limit + 1)
        if index >= 0:
            return index + len(separator)

    for index in range(limit - 1, -1, -1):
        if text[index].isspace():
            return index + 1

    return limit


def _split_text_at_boundaries(text: str, limit: int) -> list[str]:
    """Split text while retaining every original separator character."""
    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        split_position = _find_split_position(remaining, limit)
        nearby_fence = remaining.find(
            "```",
            max(0, split_position - 2),
            min(len(remaining), split_position + 2),
        )
        if nearby_fence >= 0 and nearby_fence < split_position < nearby_fence + 3:
            split_position = nearby_fence if nearby_fence > 0 else 3
        chunks.append(remaining[:split_position])
        remaining = remaining[split_position:]

    if remaining:
        chunks.append(remaining)

    return chunks


def split_message(
    text: str,
    limit: int = MAX_DISCORD_CHUNK_CHARS,
) -> list[str]:
    """Split text into Discord-safe chunks at readable boundaries.

    Split priority is paragraph, newline, sentence, whitespace, then a hard
    character boundary. Markdown code blocks are closed and reopened across
    chunk boundaries so each Discord message renders independently.

    Args:
        text: The string content to split.
        limit: Maximum character length per chunk (default: 1900).

    Returns:
        A list of non-empty string chunks.
    """
    if not text:
        return []

    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    if len(text) <= limit:
        return [text]

    has_code_fence = "```" in text
    fence_overhead = 8 if has_code_fence else 0
    content_limit = max(1, limit - fence_overhead)
    raw_chunks = _split_text_at_boundaries(text, content_limit)

    if not has_code_fence:
        return raw_chunks

    chunks: list[str] = []
    code_fence_open = False
    for raw_chunk in raw_chunks:
        prefix = "```\n" if code_fence_open else ""
        code_fence_open = code_fence_open != (raw_chunk.count("```") % 2 == 1)
        suffix = "\n```" if code_fence_open else ""
        chunks.append(f"{prefix}{raw_chunk}{suffix}")

    return chunks


async def send_deferred_response(
    interaction: "discord.Interaction",
    content: str,
    limit: int = MAX_DISCORD_CHUNK_CHARS,
) -> None:
    """Send text content in response to a deferred slash command interaction.

    Edits the original deferred response message with the first chunk to preserve
    the 'user used /command' invocation header in Discord, and sends any remaining
    chunks as followup messages.

    Args:
        interaction: Discord interaction object.
        content: String content to send.
        limit: Maximum character length per chunk (default: 1900).
    """
    chunks = split_message(content, limit=limit)
    if not chunks:
        await interaction.edit_original_response(content="No response generated.")
        return

    await interaction.edit_original_response(content=chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(content=chunk)
