import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.cogs.documents import DocumentsCog, format_document_response
from bot.services.documents import DocumentAnalysis, DocumentParseError
from bot.services.document_sessions import DocumentSession


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
        sent_msg = interaction.response.send_message.call_args[0][0]
        assert "File too large. Uno currently supports documents up to 15 MB." in sent_msg
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()

    asyncio.run(_test())


def test_analyze_cog_successful_flow():
    """Test /analyze slash command successful file download, extraction, summary, and session storage."""
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
        interaction.guild_id = 100
        interaction.channel_id = 200
        interaction.user.id = 300
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.analyze.callback(cog, interaction, file=attachment)

        interaction.response.defer.assert_called_once()
        attachment.save.assert_called_once()
        cog.document_service.extract.assert_called_once()
        cog.ai_service.summarize_document.assert_called_once_with(
            markdown="Extracted PDF text",
            filename="lecture.pdf",
        )

        # Assert session stored
        session, _ = cog.session_service.get_session(100, 200, 300)
        assert session is not None
        assert session.filename == "lecture.pdf"

        # Assert footer prompt included and original response edited
        interaction.edit_original_response.assert_called_once()
        interaction.delete_original_response.assert_not_called()
        sent_text = interaction.edit_original_response.call_args[1]["content"]
        assert "Document ready for questions. Use `/docask` within the next" in sent_text

    asyncio.run(_test())


def test_docask_successful_qna():
    """Test /docask retrieves active session and calls answer_document_question."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)

        cog.session_service.set_session(
            guild_id=100,
            channel_id=200,
            user_id=300,
            filename="lecture.pdf",
            markdown="Extracted text content",
            warnings=(),
        )

        cog.ai_service.answer_document_question = AsyncMock(return_value="Final exam date is Dec 15.")

        interaction = MagicMock()
        interaction.guild_id = 100
        interaction.channel_id = 200
        interaction.user.id = 300
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.docask.callback(cog, interaction, question="What date is the final exam?")

        interaction.response.defer.assert_called_once()
        cog.ai_service.answer_document_question.assert_called_once_with(
            document="Extracted text content",
            question="What date is the final exam?",
            filename="lecture.pdf",
        )
        interaction.edit_original_response.assert_called_once_with(content="Final exam date is Dec 15.")
        interaction.delete_original_response.assert_not_called()

    asyncio.run(_test())


def test_docask_no_active_session():
    """Test /docask returns clear message when no active document session exists."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)

        interaction = MagicMock()
        interaction.guild_id = 100
        interaction.channel_id = 200
        interaction.user.id = 300
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.docask.callback(cog, interaction, question="Any question?")

        interaction.response.defer.assert_called_once()
        interaction.edit_original_response.assert_called_once_with(
            content="No active document found. Run `/analyze` with a PDF or PPTX first."
        )
        interaction.delete_original_response.assert_not_called()

    asyncio.run(_test())


def test_docask_expired_session():
    """Test /docask returns clear message when user session is expired."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)

        cog.session_service.get_session = MagicMock(return_value=(None, True))

        interaction = MagicMock()
        interaction.guild_id = 100
        interaction.channel_id = 200
        interaction.user.id = 300
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.docask.callback(cog, interaction, question="Any question?")

        interaction.response.defer.assert_called_once()
        interaction.edit_original_response.assert_called_once_with(
            content="Your document session expired. Run `/analyze` again to continue."
        )
        interaction.delete_original_response.assert_not_called()

    asyncio.run(_test())


def test_docask_empty_question_rejected():
    """Test /docask rejects empty question prior to deferring interaction."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = DocumentsCog(bot)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.defer = AsyncMock()

        await cog.docask.callback(cog, interaction, question="   ")

        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()

    asyncio.run(_test())
