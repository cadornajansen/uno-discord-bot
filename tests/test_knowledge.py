import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.cogs.knowledge import KnowledgeCog, should_index_message
from bot.services.vector_store import VectorStoreError


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


def test_on_message_edit_reindexes_same_message_id():
    """Test on_message_edit re-embeds and updates point when content changes."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})

        cog.index_message = AsyncMock()

        before = MagicMock()
        before.content = "Our quiz is Friday."

        after = MagicMock()
        after.id = 999
        after.guild = MagicMock()
        after.channel.id = 123
        after.author.bot = False
        after.webhook_id = None
        after.content = "Our quiz is Monday."

        await cog.on_message_edit(before, after)

        cog.index_message.assert_called_once_with(after)

    asyncio.run(_test())


def test_on_message_edit_unchanged_content_skips():
    """Test on_message_edit skips processing if message content is unchanged."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})
        cog.index_message = AsyncMock()

        before = MagicMock()
        before.content = "Same content"

        after = MagicMock()
        after.content = "Same content"

        await cog.on_message_edit(before, after)

        cog.index_message.assert_not_called()

    asyncio.run(_test())


def test_on_message_edit_edited_to_empty_deletes_point():
    """Test on_message_edit deletes point if message is edited to empty/whitespace text."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})
        cog.index_message = AsyncMock()
        cog.vector_store = AsyncMock()

        before = MagicMock()
        before.guild = MagicMock()
        before.channel.id = 123
        before.content = "Valid content"

        after = MagicMock()
        after.id = 888
        after.guild = MagicMock()
        after.channel.id = 123
        after.author.bot = False
        after.webhook_id = None
        after.content = "   "  # Edited to whitespace

        await cog.on_message_edit(before, after)

        cog.index_message.assert_not_called()
        cog.vector_store.delete_message.assert_called_once_with(888)

    asyncio.run(_test())


def test_on_raw_message_delete_approved_channel():
    """Test on_raw_message_delete deletes point for allowlisted channel deletion."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})
        cog.vector_store = AsyncMock()

        payload = MagicMock()
        payload.guild_id = 777
        payload.channel_id = 123
        payload.message_id = 55555

        await cog.on_raw_message_delete(payload)

        cog.vector_store.delete_message.assert_called_once_with(55555)

    asyncio.run(_test())


def test_on_raw_message_delete_unapproved_channel_ignored():
    """Test on_raw_message_delete ignores deletion events from non-allowlisted channels."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})
        cog.vector_store = AsyncMock()

        payload = MagicMock()
        payload.guild_id = 777
        payload.channel_id = 999  # Unapproved channel
        payload.message_id = 55555

        await cog.on_raw_message_delete(payload)

        cog.vector_store.delete_message.assert_not_called()

    asyncio.run(_test())


def test_on_raw_message_delete_qdrant_failure_handled_safely():
    """Test on_raw_message_delete catches Qdrant deletion errors without crashing."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})

        vector_mock = AsyncMock()
        vector_mock.delete_message.side_effect = VectorStoreError("Qdrant offline")
        cog.vector_store = vector_mock

        payload = MagicMock()
        payload.guild_id = 777
        payload.channel_id = 123
        payload.message_id = 55555

        # Should not raise exception
        await cog.on_raw_message_delete(payload)

        vector_mock.delete_message.assert_called_once_with(55555)

    asyncio.run(_test())
