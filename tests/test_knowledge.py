from unittest.mock import MagicMock
from bot.cogs.knowledge import should_index_message


def test_should_index_valid_message():
    """Test that a valid guild text message in an allowlisted channel returns True."""
    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123456789
    message.author.bot = False
    message.webhook_id = None
    message.content = "Our DSA quiz is on Friday."

    allowlist = frozenset({123456789, 987654321})
    assert should_index_message(message, allowlist) is True


def test_should_index_ignore_dm():
    """Test that DM messages (message.guild is None) are ignored."""
    message = MagicMock()
    message.guild = None
    message.channel.id = 123456789
    message.author.bot = False
    message.webhook_id = None
    message.content = "Hello in DM"

    allowlist = frozenset({123456789})
    assert should_index_message(message, allowlist) is False


def test_should_index_unapproved_channel():
    """Test that messages in non-allowlisted channels are ignored."""
    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 999999999
    message.author.bot = False
    message.webhook_id = None
    message.content = "Random chat"

    allowlist = frozenset({123456789})
    assert should_index_message(message, allowlist) is False


def test_should_index_ignore_bots():
    """Test that messages from bot users are ignored."""
    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123456789
    message.author.bot = True
    message.webhook_id = None
    message.content = "Automated bot message"

    allowlist = frozenset({123456789})
    assert should_index_message(message, allowlist) is False


def test_should_index_ignore_webhooks():
    """Test that messages from webhooks are ignored."""
    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123456789
    message.author.bot = False
    message.webhook_id = 55555
    message.content = "Webhook message"

    allowlist = frozenset({123456789})
    assert should_index_message(message, allowlist) is False


def test_should_index_ignore_empty_content():
    """Test that empty or whitespace-only messages are ignored."""
    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123456789
    message.author.bot = False
    message.webhook_id = None
    message.content = "   "

    allowlist = frozenset({123456789})
    assert should_index_message(message, allowlist) is False
