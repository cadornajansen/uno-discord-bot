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
    DocumentError,
)
from bot.services.ai import (
    AIService,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    AIError,
)
from bot.utils.formatting import split_message

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".pptx")


def format_document_response(analysis: DocumentAnalysis, summary: str) -> str:
    """Format final analysis result and summary into readable Discord Markdown.

    Args:
        analysis: DocumentAnalysis object.
        summary: LLM generated summary string.

    Returns:
        Formatted Discord markdown string.
    """
    sections = [f"**Document Analysis — {analysis.filename}**\n"]

    # Summary section
    sections.append(f"**Summary**\n{summary}")

    # Metadata section
    info_parts = [f"Type: {analysis.file_type}"]
    if analysis.slide_count is not None:
        info_parts.append(f"Slides: {analysis.slide_count}")
    if analysis.page_count is not None:
        info_parts.append(f"Pages: {analysis.page_count}")

    sections.append(f"**Document Info**\n• " + " | ".join(info_parts))

    # Warnings section (if any)
    if analysis.warnings:
        warn_lines = [f"⚠️ {w}" for w in analysis.warnings]
        sections.append("**Notes**\n" + "\n".join(warn_lines))

    return "\n\n".join(sections)


class DocumentsCog(commands.Cog):
    """Cog handling local analysis and summarization of PDF and PPTX file attachments."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        settings = getattr(bot, "settings", None)

        base_url = settings.ollama_base_url if settings else "http://localhost:11434"
        model = settings.ollama_model if settings else "phi4-mini"
        max_chars = settings.document_max_chars if settings else 50000
        self.max_size_mb = settings.document_max_size_mb if settings else 15
        self.max_size_bytes = self.max_size_mb * 1024 * 1024

        timeout = settings.ollama_timeout_seconds if settings else 180.0
        self.document_service = DocumentService(max_chars=max_chars)
        self.ai_service = AIService(base_url=base_url, model=model, default_timeout=timeout)

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
                f"Unsupported file type '{ext}'. Uno currently supports only .pdf and .pptx files.",
                ephemeral=True,
            )
            return

        # 2. Validate file size
        if file.size > self.max_size_bytes:
            await interaction.response.send_message(
                f"File size is too large ({file.size / (1024 * 1024):.1f} MB). "
                f"Maximum allowed limit is {self.max_size_mb} MB.",
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

            # Generate AI summary if extracted text exists
            if not analysis.markdown.strip():
                summary_text = "No readable text content was found in this file to summarize."
            else:
                summary_text = await self.ai_service.summarize_document(
                    markdown=analysis.markdown,
                    filename=analysis.filename,
                )

            response_text = format_document_response(analysis, summary_text)
            chunks = split_message(response_text, limit=2000)

            if not chunks:
                await interaction.followup.send("Could not format document analysis response.")
                return

            for chunk in chunks:
                await interaction.followup.send(chunk)

        except UnsupportedFileError as e:
            await interaction.followup.send(str(e))

        except DocumentParseError:
            logger.warning(f"Failed to parse document attachment '{filename}' for user {interaction.user.id}")
            await interaction.followup.send(
                f"I couldn't read this file ({filename}). It may be corrupted, encrypted, or image-only."
            )

        except OllamaConnectionError:
            logger.warning(f"User {interaction.user.id} '/analyze' failed: Ollama service offline.")
            await interaction.followup.send(
                "The local AI service is unavailable right now."
            )

        except OllamaModelNotFoundError:
            logger.warning(
                f"User {interaction.user.id} '/analyze' failed: Model '{self.ai_service.model}' not found."
            )
            await interaction.followup.send(
                "The configured AI model is not available."
            )

        except OllamaTimeoutError:
            logger.warning(f"User {interaction.user.id} '/analyze' failed: Inference timeout.")
            await interaction.followup.send(
                "The AI service took too long to generate a document summary. Please try again later."
            )

        except AIError as e:
            logger.error(f"User {interaction.user.id} '/analyze' failed with AI error: {e}")
            await interaction.followup.send(
                "An error occurred while communicating with the AI service."
            )

        except Exception as e:
            logger.error(
                f"Unexpected error analyzing document attachment '{filename}': {e}",
                exc_info=True,
            )
            await interaction.followup.send(
                "Something went wrong while analyzing this document."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DocumentsCog(bot))
