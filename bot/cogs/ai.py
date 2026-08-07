import logging
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.ai import (
    AIService,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    AIError,
)
from bot.services.embeddings import EmbeddingService
from bot.services.vector_store import VectorStore
from bot.services.rag import RAGService
from bot.utils.formatting import split_message

logger = logging.getLogger(__name__)

# Input validation limit for user prompts (in characters)
MAX_PROMPT_LENGTH = 2000


class AICog(commands.Cog):
    """Cog for AI chat assistance and RAG-grounded slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        settings = getattr(bot, "settings", None)
        base_url = settings.ollama_base_url if settings else "http://localhost:11434"
        model = settings.ollama_model if settings else "phi4-mini"
        embed_model = settings.ollama_embedding_model if settings else "embeddinggemma"
        qdrant_url = settings.qdrant_url if settings else "http://localhost:6333"
        qdrant_coll = settings.qdrant_collection if settings else "discord_messages"
        top_k = settings.rag_top_k if settings else 5
        min_score = settings.rag_min_score if settings else 0.30

        ai_service = AIService(base_url=base_url, model=model)
        embedding_service = EmbeddingService(base_url=base_url, model=embed_model)
        vector_store = VectorStore(url=qdrant_url, collection_name=qdrant_coll)

        self.rag_service = RAGService(
            ai_service=ai_service,
            embedding_service=embedding_service,
            vector_store=vector_store,
            top_k=top_k,
            min_score=min_score,
        )

    @app_commands.command(name="ask", description="Ask the AI assistant a question grounded in class context.")
    @app_commands.describe(question="The question or prompt to ask the AI assistant.")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        """Slash command /ask question:<text>"""
        # Security boundary: RAG-enabled /ask must run inside a Discord server
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command currently works inside a server.",
                ephemeral=True,
            )
            return

        cleaned_question = question.strip()

        # Input validation
        if not cleaned_question:
            await interaction.response.send_message(
                "Question cannot be empty or contain only whitespace.",
                ephemeral=True,
            )
            return

        if len(cleaned_question) > MAX_PROMPT_LENGTH:
            await interaction.response.send_message(
                f"Question is too long (maximum {MAX_PROMPT_LENGTH} characters).",
                ephemeral=True,
            )
            return

        # Defer interaction before executing vector search and local LLM inference
        await interaction.response.defer()

        try:
            response_text = await self.rag_service.answer(
                cleaned_question,
                guild_id=interaction.guild.id,
            )

            chunks = split_message(response_text, limit=2000)
            if not chunks:
                await interaction.followup.send("The AI returned an empty response.")
                return

            for chunk in chunks:
                await interaction.followup.send(chunk)

        except OllamaConnectionError:
            logger.warning(
                f"User {interaction.user.id} '/ask' failed: Ollama service offline."
            )
            await interaction.followup.send(
                "The local AI service is unavailable right now."
            )

        except OllamaModelNotFoundError:
            logger.warning(
                f"User {interaction.user.id} '/ask' failed: Model '{self.rag_service.ai_service.model}' not found."
            )
            await interaction.followup.send(
                "The configured AI model is not available."
            )

        except OllamaTimeoutError:
            logger.warning(
                f"User {interaction.user.id} '/ask' failed: Local inference timed out."
            )
            await interaction.followup.send(
                "The AI service took too long to respond. Please try again later."
            )

        except AIError as e:
            logger.error(
                f"User {interaction.user.id} '/ask' failed with AI service error: {e}"
            )
            await interaction.followup.send(
                "An error occurred while communicating with the AI service."
            )

        except Exception as e:
            logger.error(
                f"Unexpected exception during '/ask' execution: {e}",
                exc_info=True,
            )
            await interaction.followup.send(
                "Something went wrong while running this command."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
