import pytest
from bot.utils.formatting import (
    MAX_DISCORD_CHUNK_CHARS,
    build_assignment_embeds,
    split_message,
    format_latency,
    format_timestamp,
)


def test_build_assignment_embeds_groups_tasks_by_subject():
    content = (
        "**Latest Homework & Requirements**\n\n"
        "**ITC — Introduction to Computing**\n"
        "*Professor · Lecture · Room 1*\n"
        "- Finish Activity 1 — No due date stated\n\n"
        "**DS1 — Discrete Structures 1**\n"
        "*Professor · Lecture · Room 2*\n"
        "- Review for Wednesday"
    )

    embeds = build_assignment_embeds(
        [{"content": content}],
        "2026-08-10T20:00+08:00",
    )

    assert len(embeds) == 1
    assert embeds[0].title == "Latest Assignments"
    assert [field.name for field in embeds[0].fields] == [
        "ITC — Introduction to Computing",
        "DS1 — Discrete Structures 1",
    ]
    assert "• Finish Activity 1" in embeds[0].fields[0].value
    assert embeds[0].footer.text == "Checked Aug 10, 2026 at 08:00 PM · Asia/Manila"


def test_send_deferred_chat_response_uses_embed_for_assignments():
    """Structured assignment data replaces the deferred text with an embed."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.formatting import send_deferred_chat_response

    async def _test():
        interaction = MagicMock()
        interaction.edit_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()
        content = (
            "**Latest Homework & Requirements**\n\n"
            "**ITC — Introduction to Computing**\n"
            "- Finish Activity 1"
        )

        await send_deferred_chat_response(
            interaction,
            content,
            ({"content": content},),
        )

        call = interaction.edit_original_response.await_args
        assert call.kwargs["content"] is None
        assert call.kwargs["embed"].title == "Latest Assignments"
        interaction.followup.send.assert_not_awaited()

    asyncio.run(_test())


def test_split_message_empty():
    """Test splitting an empty string returns empty list."""
    assert split_message("") == []


def test_split_message_short():
    """Test message within limit is not split."""
    text = "Hello world!"
    assert split_message(text, limit=2000) == ["Hello world!"]


def test_split_message_newline_boundary():
    """Test splitting occurs at newline boundaries when exceeding limit."""
    line1 = "Line one of text."
    line2 = "Line two of text."
    text = f"{line1}\n{line2}"

    # Set limit so only line1 fits in first chunk
    chunks = split_message(text, limit=20)
    assert chunks == [f"{line1}\n", line2]
    # Check no text was lost
    assert "".join(chunks) == text


def test_split_message_long_text_no_loss():
    """Test splitting a large multi-line block preserves all characters and has no empty chunks."""
    lines = [f"This is line number {i} with some additional content." for i in range(100)]
    original = "\n".join(lines)

    chunks = split_message(original, limit=500)

    # Ensure all chunks are <= 500 chars
    for chunk in chunks:
        assert len(chunk) <= 500
        assert len(chunk) > 0

    # Reconstructed text should match original
    reconstructed = "".join(chunks)
    assert reconstructed == original


def test_split_message_hard_split_long_word():
    """Test hard splitting when a single token/word exceeds the character limit."""
    long_token = "A" * 150
    chunks = split_message(long_token, limit=50)

    assert len(chunks) == 3
    assert chunks[0] == "A" * 50
    assert chunks[1] == "A" * 50
    assert chunks[2] == "A" * 50
    assert "".join(chunks) == long_token


def test_split_message_default_chunks_stay_under_safe_limit():
    """Default chunks leave headroom below Discord's 2,000-character limit."""
    chunks = split_message("word " * 1000)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_DISCORD_CHUNK_CHARS for chunk in chunks)


def test_split_message_prefers_paragraph_boundary():
    """Paragraph boundaries take priority over later single newlines."""
    text = "First.\n\nSecond line\nThird line"

    chunks = split_message(text, limit=20)

    assert chunks[0] == "First.\n\n"
    assert "".join(chunks) == text


def test_split_message_code_fence_handling():
    """Split code blocks are closed and reopened for valid Discord rendering."""
    text = "```python\n" + ("print('hello')\n" * 12) + "```"

    chunks = split_message(text, limit=60)

    assert len(chunks) > 1
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert chunks[0].endswith("\n```")
    assert chunks[1].startswith("```\n")


def test_send_deferred_response_single_chunk():
    """Test send_deferred_response edits original response for single chunk and calls no followup send."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.formatting import send_deferred_response

    async def _test():
        interaction = MagicMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        await send_deferred_response(interaction, "Hello world!")

        interaction.edit_original_response.assert_called_once_with(content="Hello world!")
        interaction.delete_original_response.assert_not_called()
        interaction.followup.send.assert_not_called()

    asyncio.run(_test())


def test_send_deferred_response_multi_chunk():
    """Test send_deferred_response edits original response with chunk 0 and sends chunk 1 as followup."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.formatting import send_deferred_response

    async def _test():
        interaction = MagicMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        text = "Line 1\nLine 2"
        await send_deferred_response(interaction, text, limit=10)

        interaction.edit_original_response.assert_called_once_with(content="Line 1\n")
        interaction.delete_original_response.assert_not_called()
        interaction.followup.send.assert_called_once_with(content="Line 2")

    asyncio.run(_test())


def test_send_deferred_response_sources_appear_once():
    """A multi-chunk response does not duplicate its Sources section."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.formatting import send_deferred_response

    async def _test():
        interaction = MagicMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()
        content = f"{'Answer text. ' * 10}\n\nSources: [Message 1](https://example.com)"

        await send_deferred_response(interaction, content, limit=50)

        sent_chunks = [
            interaction.edit_original_response.call_args.kwargs["content"],
            *[
                call.kwargs["content"]
                for call in interaction.followup.send.call_args_list
            ],
        ]
        assert sum(chunk.count("Sources:") for chunk in sent_chunks) == 1
        interaction.delete_original_response.assert_not_called()

    asyncio.run(_test())
