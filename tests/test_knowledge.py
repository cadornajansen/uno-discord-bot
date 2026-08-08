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
    message.interaction = None
    message.interaction_metadata = None
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
    message.interaction = None
    message.interaction_metadata = None
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
    message.interaction = None
    message.interaction_metadata = None
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
    message.interaction = None
    message.interaction_metadata = None
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
    message.interaction = None
    message.interaction_metadata = None
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
    message.interaction = None
    message.interaction_metadata = None
    message.content = "   "

    allowlist = frozenset({123456789})
    assert should_index_message(message, allowlist) is False


def test_should_index_ignore_interaction_slash_command_messages():
    """Test that interaction and slash-command messages with interaction_metadata are ignored."""
    msg_with_metadata = MagicMock()
    msg_with_metadata.guild = MagicMock()
    msg_with_metadata.channel.id = 123456789
    msg_with_metadata.author.bot = False
    msg_with_metadata.webhook_id = None
    msg_with_metadata.interaction_metadata = MagicMock()
    msg_with_metadata.content = "/ask"

    allowlist = frozenset({123456789})
    assert should_index_message(msg_with_metadata, allowlist) is False


def test_should_index_image_only_in_ocr_channel_eligible():
    """Test image-only message in indexed + OCR-enabled channel is eligible."""
    att = MagicMock()
    att.filename = "assignment.png"
    att.content_type = "image/png"
    att.size = 1000

    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123
    message.author.bot = False
    message.webhook_id = None
    message.interaction_metadata = None
    message.content = ""
    message.attachments = [att]

    indexed = frozenset({123})
    ocr = frozenset({123})

    assert should_index_message(message, indexed_channel_ids=indexed, ocr_channel_ids=ocr) is True


def test_should_index_image_only_outside_ocr_channel_skipped():
    """Test image-only message in indexed channel NOT in ocr_channel_ids is skipped."""
    att = MagicMock()
    att.filename = "assignment.png"
    att.content_type = "image/png"
    att.size = 1000

    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123
    message.author.bot = False
    message.webhook_id = None
    message.interaction_metadata = None
    message.content = ""
    message.attachments = [att]

    indexed = frozenset({123})
    ocr = frozenset({999})  # Different channel

    assert should_index_message(message, indexed_channel_ids=indexed, ocr_channel_ids=ocr) is False


def test_should_index_unsupported_attachment_only_skipped():
    """Test PDF/ZIP attachment-only message in OCR channel is skipped."""
    att = MagicMock()
    att.filename = "document.pdf"
    att.content_type = "application/pdf"
    att.size = 1000

    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123
    message.author.bot = False
    message.webhook_id = None
    message.interaction_metadata = None
    message.content = ""
    message.attachments = [att]

    indexed = frozenset({123})
    ocr = frozenset({123})

    assert should_index_message(message, indexed_channel_ids=indexed, ocr_channel_ids=ocr) is False


def test_should_index_oversized_image_attachment_only_skipped():
    """Test oversized image attachment-only message in OCR channel is skipped."""
    att = MagicMock()
    att.filename = "huge.png"
    att.content_type = "image/png"
    att.size = 20 * 1024 * 1024  # 20 MB

    message = MagicMock()
    message.guild = MagicMock()
    message.channel.id = 123
    message.author.bot = False
    message.webhook_id = None
    message.interaction_metadata = None
    message.content = ""
    message.attachments = [att]

    indexed = frozenset({123})
    ocr = frozenset({123})

    assert (
        should_index_message(
            message,
            indexed_channel_ids=indexed,
            ocr_channel_ids=ocr,
            ocr_max_image_mb=8,
        )
        is False
    )


def test_index_message_combines_text_and_ocr():
    """Test KnowledgeCog index_message combines message content and OCR text in Qdrant payload."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})
        cog.ocr_channel_ids = frozenset({123})
        cog.embedding_service.embed = AsyncMock(return_value=[0.1] * 768)
        cog.vector_store.upsert_message = AsyncMock()
        cog.ocr_service.extract_text = AsyncMock(return_value="Quiz on Chapter 4 due Aug 10")

        att = MagicMock()
        att.filename = "homework.png"
        att.content_type = "image/png"
        att.size = 500
        att.read = AsyncMock(return_value=b"image_bytes")

        message = MagicMock()
        message.id = 777
        message.guild.id = 111
        message.channel.id = 123
        message.author.id = 222
        message.author.bot = False
        message.webhook_id = None
        message.interaction_metadata = None
        message.content = "Check attached homework assignment."
        message.attachments = [att]
        message.created_at.isoformat.return_value = "2026-08-08T12:00:00Z"

        success = await cog.index_message(message)
        assert success is True

        cog.vector_store.upsert_message.assert_called_once()
        call_kwargs = cog.vector_store.upsert_message.call_args[1]
        payload = call_kwargs["payload"]

        assert "Discord message:\nCheck attached homework assignment." in payload["content"]
        assert "Image text:\nQuiz on Chapter 4 due Aug 10" in payload["content"]
        assert payload["source_type"] == "text_and_image_ocr"
        assert payload["ocr_attachment_count"] == 1
        assert payload["ocr_filenames"] == ["homework.png"]

    asyncio.run(_test())


def test_index_message_ocr_failure_preserves_normal_text():
    """Test KnowledgeCog still indexes normal text if OCR raises an error."""
    async def _test():
        bot = MagicMock()
        cog = KnowledgeCog(bot)
        cog.indexed_channel_ids = frozenset({123})
        cog.ocr_channel_ids = frozenset({123})
        cog.embedding_service.embed = AsyncMock(return_value=[0.1] * 768)
        cog.vector_store.upsert_message = AsyncMock()
        cog.ocr_service.extract_text = AsyncMock(side_effect=Exception("Corrupt image"))

        att = MagicMock()
        att.filename = "bad.png"
        att.content_type = "image/png"
        att.size = 500
        att.read = AsyncMock(return_value=b"corrupt")

        message = MagicMock()
        message.id = 888
        message.guild.id = 111
        message.channel.id = 123
        message.author.id = 222
        message.author.bot = False
        message.webhook_id = None
        message.interaction_metadata = None
        message.content = "Please read textbook."
        message.attachments = [att]
        message.created_at.isoformat.return_value = "2026-08-08T12:00:00Z"

        success = await cog.index_message(message)
        assert success is True

        payload = cog.vector_store.upsert_message.call_args[1]["payload"]
        assert payload["content"] == "Please read textbook."
        assert payload["source_type"] == "text"
        assert payload["ocr_attachment_count"] == 0

    asyncio.run(_test())


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
        after.interaction = None
        after.interaction_metadata = None
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
