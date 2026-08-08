import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import pytest

from scripts.backfill_discord_history import run_backfill


def test_backfill_unapproved_channel_rejected(monkeypatch: pytest.MonkeyPatch):
    """Test that specifying an unapproved channel ID causes backfill to exit with code 1."""
    async def _test():
        monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
        monkeypatch.setenv("INDEXED_CHANNEL_IDS", "123456789")

        code = await run_backfill(channel_id_filter=999999999, limit=10)
        assert code == 1

    asyncio.run(_test())


def test_backfill_empty_allowlist_rejected(monkeypatch: pytest.MonkeyPatch):
    """Test that empty INDEXED_CHANNEL_IDS causes backfill to exit with code 1."""
    async def _test():
        monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
        monkeypatch.setenv("INDEXED_CHANNEL_IDS", "")

        code = await run_backfill(channel_id_filter=None, limit=10)
        assert code == 1

    asyncio.run(_test())


def test_backfill_ocr_channel_integration(monkeypatch: pytest.MonkeyPatch):
    """Test run_backfill processes image attachments in OCR channels via shared KnowledgeCog ingestion."""
    async def _test():
        monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
        monkeypatch.setenv("INDEXED_CHANNEL_IDS", "123")
        monkeypatch.setenv("OCR_CHANNEL_IDS", "123")

        class MockTextChannel(discord.TextChannel):
            def __init__(self):
                pass

        mock_bot = MagicMock()
        mock_channel = MagicMock(spec=MockTextChannel)

        att = MagicMock()
        att.filename = "assignment.png"
        att.content_type = "image/png"
        att.size = 500
        att.read = AsyncMock(return_value=b"png_bytes")

        msg = MagicMock()
        msg.id = 555
        msg.guild.id = 111
        msg.channel.id = 123
        msg.author.id = 222
        msg.author.bot = False
        msg.webhook_id = None
        msg.interaction_metadata = None
        msg.content = "Due tomorrow"
        msg.attachments = [att]
        msg.created_at.isoformat.return_value = "2026-08-08T12:00:00Z"

        class AsyncHist:
            def __init__(self, messages):
                self.messages = messages

            def __aiter__(self):
                self.iter = iter(self.messages)
                return self

            async def __anext__(self):
                try:
                    return next(self.iter)
                except StopIteration:
                    raise StopAsyncIteration

        mock_channel.history = MagicMock(return_value=AsyncHist([msg]))
        mock_channel.name = "homework"

        mock_bot.get_channel = MagicMock(return_value=mock_channel)
        mock_bot.fetch_channel = AsyncMock(return_value=mock_channel)
        async def mock_start(token):
            on_ready_fn = mock_bot.event.call_args_list[0][0][0]
            await on_ready_fn()

        mock_bot.start = mock_start
        mock_bot.close = AsyncMock()

        mock_ocr_service = MagicMock()
        mock_ocr_service.extract_text = AsyncMock(return_value="Exercise 1: Solve X")

        with patch("discord.ext.commands.Bot", return_value=mock_bot), \
             patch("bot.cogs.knowledge.EmbeddingService.embed", new_callable=AsyncMock) as mock_embed, \
             patch("bot.cogs.knowledge.VectorStore.upsert_message", new_callable=AsyncMock) as mock_upsert, \
             patch("bot.cogs.knowledge.VectorStore.close", new_callable=AsyncMock), \
             patch("bot.cogs.knowledge.OCRService", return_value=mock_ocr_service):

            mock_embed.return_value = [0.1] * 768

            code = await run_backfill(channel_id_filter=123, limit=1)

            assert code == 0
            mock_ocr_service.extract_text.assert_called_once()
            mock_upsert.assert_called_once()
            point_id = mock_upsert.call_args[1]["message_id"]
            payload = mock_upsert.call_args[1]["payload"]

            assert point_id == 555
            assert "Discord message:\nDue tomorrow" in payload["content"]
            assert "Image text:\nExercise 1: Solve X" in payload["content"]
            assert payload["source_type"] == "text_and_image_ocr"

    asyncio.run(_test())
