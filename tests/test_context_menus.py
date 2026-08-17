import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.general import GeneralCog
from bot.services.chat_orchestrator import ChatResponse


def _make_general_cog() -> GeneralCog:
    bot = MagicMock()
    bot.chat_orchestrator = MagicMock()
    bot.chat_orchestrator.chat = AsyncMock(
        return_value=ChatResponse(content="This is a simple explanation of the Python snippet.")
    )
    return GeneralCog(bot)


def test_explain_this_context_menu_with_text():
    """Test 'Explain This' context menu extracts message text and returns explanation."""
    async def _test():
        cog = _make_general_cog()

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user.display_name = "Alex"
        interaction.user.id = 123
        interaction.guild.id = 777
        interaction.channel.id = 456
        interaction.channel.name = "bot-channel"

        message = MagicMock()
        message.clean_content = "def add(a, b): return a + b"
        message.author.display_name = "Maria"
        message.attachments = []
        message.embeds = []

        await cog.explain_this(interaction, message)

        interaction.response.defer.assert_awaited_once_with(ephemeral=False)
        cog.bot.chat_orchestrator.chat.assert_awaited_once()
        prompt = cog.bot.chat_orchestrator.chat.await_args.args[0]
        assert "def add(a, b): return a + b" in prompt
        assert "Maria" in prompt
        interaction.followup.send.assert_awaited_once()
        sent_text = interaction.followup.send.call_args[0][0]
        assert "Explanation for Maria's message" in sent_text

    asyncio.run(_test())


def test_explain_this_context_menu_empty_message():
    """Test 'Explain This' context menu handles messages without text."""
    async def _test():
        cog = _make_general_cog()

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        message = MagicMock()
        message.clean_content = ""
        message.attachments = []
        message.embeds = []

        await cog.explain_this(interaction, message)

        cog.bot.chat_orchestrator.chat.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with(
            "That message doesn't contain readable text to explain.",
            ephemeral=True,
        )

    asyncio.run(_test())


def test_run_ocr_context_menu_with_image():
    """Test 'Run OCR' context menu extracts text from image attachments."""
    async def _test():
        cog = _make_general_cog()

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        attachment = MagicMock()
        attachment.filename = "homework.png"
        attachment.content_type = "image/png"
        attachment.url = "https://cdn.discordapp.com/attachments/123/homework.png"

        message = MagicMock()
        message.attachments = [attachment]

        mock_http_response = MagicMock()
        mock_http_response.content = b"fake_png_data"
        mock_http_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient.get", return_value=mock_http_response), \
             patch("bot.services.ocr.OCRService.extract_text", new_callable=AsyncMock) as mock_ocr:
            mock_ocr.return_value = "Page 1: Solve problem 4 and 5"
            await cog.run_ocr(interaction, message)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        mock_ocr.assert_awaited_once_with(b"fake_png_data")
        interaction.followup.send.assert_awaited_once()
        sent_text = interaction.followup.send.call_args[0][0]
        assert "homework.png" in sent_text
        assert "Page 1: Solve problem 4 and 5" in sent_text

    asyncio.run(_test())


def test_run_ocr_context_menu_without_image():
    """Test 'Run OCR' context menu alerts user if no image attachment is found."""
    async def _test():
        cog = _make_general_cog()

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        message = MagicMock()
        message.attachments = []

        await cog.run_ocr(interaction, message)

        interaction.followup.send.assert_awaited_once_with(
            "No supported image attachments (.png, .jpg, .webp) found in that message.",
            ephemeral=True,
        )

    asyncio.run(_test())
