import logging
from pathlib import Path
import tempfile
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.documents import (
    DocumentService,
    DocumentAnalysis,
    UnsupportedFileError,
    DocumentParseError,
)
from bot.services.document_sessions import DocumentSessionService
from bot.services.ai import (
    AIService,
    AIConnectionError,
    AIModelNotFoundError,
    AITimeoutError,
    AIError,
)
from bot.utils.formatting import (
    discord_safe_markdown,
    send_deferred_pages,
    send_deferred_response,
    split_message,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".pptx")
MAX_QUESTION_LENGTH = 500
DOCUMENT_SUMMARY_PREVIEW_CHARS = 1100


def format_document_response(analysis: DocumentAnalysis, summary: str) -> str:
    """Format final analysis result and summary into readable Discord Markdown.

    Args:
        analysis: DocumentAnalysis object.
        summary: LLM generated summary string.

    Returns:
        Formatted Discord markdown string.
    """
    sections = [f"**Document Analysis — {analysis.filename}**"]

    # Show available metadata before the generated summary.
    info_parts = []
    if analysis.slide_count is not None:
        info_parts.append(f"Slides: {analysis.slide_count}")
    if analysis.page_count is not None:
        info_parts.append(f"Pages: {analysis.page_count}")
    if info_parts:
        sections.append("**Details**\n• " + " | ".join(info_parts))

    sections.append(f"**Summary**\n{summary}")
    sections.append(f"**Document:** {analysis.file_type}")

    # Warnings section (if any)
    if analysis.warnings:
        warn_lines = [f"⚠️ {w}" for w in analysis.warnings]
        sections.append("**Notes**\n" + "\n".join(warn_lines))

    return "\n\n".join(sections)


def build_document_response_pages(
    analysis: DocumentAnalysis,
    summary: str,
    session_note: str | None = None,
) -> list[str]:
    """Keep the document card on page one and hide extra detail behind controls."""
    summary_pages = split_message(
        discord_safe_markdown(summary),
        limit=DOCUMENT_SUMMARY_PREVIEW_CHARS,
    ) or ["No summary was generated."]

    first_page = format_document_response(analysis, summary_pages[0])
    if session_note:
        first_page += f"\n\n{session_note}"

    continuation_pages = [
        f"**Summary Continued**\n{page}"
        for page in summary_pages[1:]
    ]
    return [first_page, *continuation_pages]


class DocumentsCog(commands.Cog):
    """Cog handling local analysis and interactive Q&A for PDF and PPTX file attachments."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        settings = getattr(bot, "settings", None)

        base_url = (
            settings.assemblyai_llm_base_url
            if settings
            else "https://llm-gateway.assemblyai.com/v1"
        )
        model = settings.assemblyai_llm_model if settings else "gemini-3.5-flash"
        max_chars = settings.document_max_chars if settings else 20000
        ttl_minutes = settings.document_session_ttl_minutes if settings else 30
        self.max_size_mb = settings.document_max_size_mb if settings else 15
        self.max_size_bytes = self.max_size_mb * 1024 * 1024

        timeout = settings.assemblyai_llm_timeout_seconds if settings else 60.0
        self.document_service = DocumentService(max_chars=max_chars)
        self.session_service = DocumentSessionService(ttl_minutes=ttl_minutes)
        self.ai_service = AIService(
            api_key=settings.assemblyai_api_key if settings else "",
            base_url=base_url,
            model=model,
            default_timeout=timeout,
            max_tokens=settings.assemblyai_llm_max_tokens if settings else 400,
        )

    @app_commands.command(
        name="analyze",
        description="Analyze and summarize a PDF or PowerPoint file.",
    )
    @app_commands.describe(file="The PDF or PPTX file attachment to analyze.")
    async def analyze(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
    ) -> None:
        """Slash command /analyze file:<attachment>"""
        filename = file.filename
        ext = Path(filename).suffix.lower()

        # 1. Validate file extension
        if ext not in SUPPORTED_EXTENSIONS:
            await interaction.response.send_message(
                f"Unsupported file format '{ext}'. Uno currently supports only .pdf and .pptx files.",
                ephemeral=True,
            )
            return

        # 2. Validate file size
        if file.size > self.max_size_bytes:
            await interaction.response.send_message(
                f"File too large. Uno currently supports documents up to {self.max_size_mb} MB.",
                ephemeral=True,
            )
            return

        # Defer interaction before downloading and processing file
        await interaction.response.defer()

        # 3. Download attachment into temporary directory & process
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_file_path = Path(temp_dir) / f"temp_{file.id}{ext}"

                # Download Discord attachment
                await file.save(temp_file_path)

                # Extract textual content & metadata
                analysis = await self.document_service.extract(
                    path=temp_file_path,
                    filename=filename,
                )

            # Check if readable text content exists
            if not analysis.markdown.strip():
                summary_text = "No readable text content was found in this file to summarize."
                stored_session = False
            else:
                # Store active document session in memory
                self.session_service.set_session(
                    guild_id=interaction.guild_id,
                    channel_id=interaction.channel_id,
                    user_id=interaction.user.id,
                    filename=analysis.filename,
                    markdown=analysis.markdown,
                    warnings=analysis.warnings,
                )
                stored_session = True

                summary_text = await self.ai_service.summarize_document(
                    markdown=analysis.markdown,
                    filename=analysis.filename,
                )

            session_note = None
            if stored_session:
                session_note = (
                    "Document ready for questions. Use `/docask` within the next "
                    f"{self.session_service.ttl_minutes} minutes."
                )

            response_pages = build_document_response_pages(
                analysis,
                summary_text,
                session_note,
            )
            await send_deferred_pages(interaction, response_pages)

        except UnsupportedFileError as e:
            await interaction.edit_original_response(content=str(e))

        except DocumentParseError:
            logger.warning(f"Failed to parse document attachment '{filename}' for user {interaction.user.id}")
            await interaction.edit_original_response(
                content=f"I couldn't read this file ({filename}). It may be corrupted, encrypted, or image-only."
            )

        except AIConnectionError:
            logger.warning(f"User {interaction.user.id} '/analyze' failed: AI gateway unavailable.")
            await interaction.edit_original_response(
                content="The AI service is unavailable right now."
            )

        except AIModelNotFoundError:
            logger.warning(
                f"User {interaction.user.id} '/analyze' failed: Model '{self.ai_service.model}' not found."
            )
            await interaction.edit_original_response(
                content="The configured AI model is not available."
            )

        except AITimeoutError:
            logger.warning(f"User {interaction.user.id} '/analyze' failed: Inference timeout.")
            await interaction.edit_original_response(
                content="The AI service took too long to generate a document summary. Please try again later."
            )

        except AIError as e:
            logger.error(f"User {interaction.user.id} '/analyze' failed with AI error: {e}")
            await interaction.edit_original_response(
                content="An error occurred while communicating with the AI service."
            )

        except Exception as e:
            logger.error(
                f"Unexpected error analyzing document attachment '{filename}': {e}",
                exc_info=True,
            )
            await interaction.edit_original_response(
                content="Something went wrong while analyzing this document."
            )

    @app_commands.command(
        name="docask",
        description="Ask a question about your currently analyzed document.",
    )
    @app_commands.describe(question="The question to ask about your active document.")
    async def docask(
        self,
        interaction: discord.Interaction,
        question: str,
    ) -> None:
        """Slash command /docask question:<text>"""
        cleaned_question = question.strip()

        # 1. Validate question input
        if not cleaned_question:
            await interaction.response.send_message(
                "Question cannot be empty or contain only whitespace.",
                ephemeral=True,
            )
            return

        if len(cleaned_question) > MAX_QUESTION_LENGTH:
            await interaction.response.send_message(
                f"Question is too long (maximum {MAX_QUESTION_LENGTH} characters).",
                ephemeral=True,
            )
            return

        # Defer interaction before retrieving session and calling LLM
        await interaction.response.defer()

        # 2. Retrieve active document session with lazy TTL check
        session, was_expired = self.session_service.get_session(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
        )

        if was_expired:
            await interaction.edit_original_response(
                content="Your document session expired. Run `/analyze` again to continue."
            )
            return

        if session is None:
            await interaction.edit_original_response(
                content="No active document found. Run `/analyze` with a PDF or PPTX first."
            )
            return

        try:
            answer_text = await self.ai_service.answer_document_question(
                document=session.markdown,
                question=cleaned_question,
                filename=session.filename,
            )

            await send_deferred_response(interaction, answer_text)

        except AIConnectionError:
            logger.warning(f"User {interaction.user.id} '/docask' failed: AI gateway unavailable.")
            await interaction.edit_original_response(
                content="The AI service is unavailable right now."
            )

        except AIModelNotFoundError:
            logger.warning(
                f"User {interaction.user.id} '/docask' failed: Model '{self.ai_service.model}' not found."
            )
            await interaction.edit_original_response(
                content="The configured AI model is not available."
            )

        except AITimeoutError:
            logger.warning(f"User {interaction.user.id} '/docask' failed: Inference timeout.")
            await interaction.edit_original_response(
                content="The AI service took too long to respond. Please try again later."
            )

        except AIError as e:
            logger.error(f"User {interaction.user.id} '/docask' failed with AI error: {e}")
            await interaction.edit_original_response(
                content="An error occurred while communicating with the AI service."
            )

        except Exception as e:
            logger.error(
                f"Unexpected error during '/docask' execution: {e}",
                exc_info=True,
            )
            await interaction.edit_original_response(
                content="Something went wrong while running this command."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DocumentsCog(bot))
