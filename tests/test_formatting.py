import pytest
from bot.utils.formatting import split_message, format_latency, format_timestamp


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
    assert chunks == [line1, line2]
    # Check no text was lost
    assert "\n".join(chunks) == text


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
    reconstructed = "\n".join(chunks)
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
