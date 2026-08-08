import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.cogs.documents import DocumentsCog, format_document_response
from bot.services.documents import DocumentAnalysis, DocumentParseError


def test_format_document_response_helper():
    """Test format_document_response builds markdown title, summary, info, and warnings."""
    analysis = DocumentAnalysis(
        filename="lecture.pptx",
        file_type="PPTX",
        markdown="Sample markdown",
        warnings=("Visual content present",),
        slide_count=12,
    )

    formatted = format_document_response(analysis, summary="• Key point 1\n• Key point 2")

    assert "**Document Analysis — lecture.pptx**" in formatted
    assert "• Key point 1" in formatted
    assert "Type: PPTX | Slides: 12" in formatted
    assert "⚠️ Visual content present" in formatted


def test_analyze_cog_unsupported_file_extension():
    """Test /analyze slash command rejects unsupported file extension before deferring interaction."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)

        attachment = MagicMock()
        attachment.filename = "document.docx"
        attachment.size = 1000

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.defer = AsyncMock()

        await cog.analyze.callback(cog, interaction, file=attachment)

        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()

    asyncio.run(_test())


def test_analyze_cog_file_size_exceeded():
    """Test /analyze slash command rejects oversized attachment before deferring interaction."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)
        cog.max_size_bytes = 15 * 1024 * 1024  # 15 MB

        attachment = MagicMock()
        attachment.filename = "huge_lecture.pdf"
        attachment.size = 20 * 1024 * 1024  # 20 MB

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.defer = AsyncMock()

        await cog.analyze.callback(cog, interaction, file=attachment)

        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()

    asyncio.run(_test())


def test_analyze_cog_successful_flow():
    """Test /analyze slash command successful file download, extraction, and summary."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)

        mock_analysis = DocumentAnalysis(
            filename="lecture.pdf",
            file_type="PDF",
            markdown="Extracted PDF text",
            warnings=(),
            page_count=5,
        )

        cog.document_service.extract = AsyncMock(return_value=mock_analysis)
        cog.ai_service.summarize_document = AsyncMock(return_value="• Summary point 1")

        attachment = MagicMock()
        attachment.filename = "lecture.pdf"
        attachment.size = 1000
        attachment.id = 12345
        attachment.save = AsyncMock()

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.analyze.callback(cog, interaction, file=attachment)

        interaction.response.defer.assert_called_once()
        attachment.save.assert_called_once()
        cog.document_service.extract.assert_called_once()
        cog.ai_service.summarize_document.assert_called_once_with(
            markdown="Extracted PDF text",
            filename="lecture.pdf",
        )
        interaction.followup.send.assert_called_once()
        sent_text = interaction.followup.send.call_args[0][0]
        assert "**Document Analysis — lecture.pdf**" in sent_text
        assert "• Summary point 1" in sent_text

    asyncio.run(_test())


def test_analyze_cog_parse_error_handled():
    """Test /analyze slash command sends user-friendly error when document parsing fails."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)
        cog.document_service.extract = AsyncMock(side_effect=DocumentParseError("Corrupt file"))

        attachment = MagicMock()
        attachment.filename = "corrupt.pdf"
        attachment.size = 1000
        attachment.id = 12345
        attachment.save = AsyncMock()

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.analyze.callback(cog, interaction, file=attachment)

        interaction.response.defer.assert_called_once()
        interaction.followup.send.assert_called_once()
        sent_text = interaction.followup.send.call_args[0][0]
        assert "I couldn't read this file" in sent_text

    asyncio.run(_test())
