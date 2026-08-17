import logging
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.ai import (
    AIConnectionError,
    AIEmptyResponseError,
    AIError,
    AIModelNotFoundError,
    AISafetyBlockError,
    AITimeoutError,
)
from bot.utils.formatting import send_deferred_chat_response

logger = logging.getLogger(__name__)

# Input validation limit for user prompts (in characters)
MAX_PROMPT_LENGTH = 2000


class AICog(commands.Cog):
    """Cog for AI chat assistance and RAG-grounded slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_orchestrator = bot.chat_orchestrator

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
            response = await self.chat_orchestrator.chat(
                cleaned_question,
                guild_id=interaction.guild.id,
                channel_id=interaction.channel.id,
                user_id=interaction.user.id,
                user_display_name=interaction.user.display_name,
                channel_name=getattr(interaction.channel, "name", "unknown"),
            )

            await send_deferred_chat_response(
                interaction,
                response.content,
                response.assignment_items,
                response.current_datetime,
            )

        except AISafetyBlockError:
            logger.warning(
                f"User {interaction.user.id} '/ask' triggered AI safety filter."
            )
            await interaction.edit_original_response(
                content="That prompt triggered a content safety filter. Rephrase it and try again."
            )

        except AIEmptyResponseError:
            logger.warning(
                f"User {interaction.user.id} '/ask' received empty response from AI gateway."
            )
            await interaction.edit_original_response(
                content="The AI returned an empty response. Try rephrasing your question."
            )

        except AIConnectionError:
            logger.warning(
                f"User {interaction.user.id} '/ask' failed: AI gateway unavailable."
            )
            await interaction.edit_original_response(
                content="The AI service is unavailable right now."
            )

        except AIModelNotFoundError:
            logger.warning(
                f"User {interaction.user.id} '/ask' failed: Model '{self.chat_orchestrator.ai_service.model}' not found."
            )
            await interaction.edit_original_response(
                content="The configured AI model is not available."
            )

        except AITimeoutError:
            logger.warning(
                f"User {interaction.user.id} '/ask' failed: AI gateway timed out."
            )
            await interaction.edit_original_response(
                content="The AI service took too long to respond. Please try again later."
            )

        except AIError as e:
            logger.error(
                f"User {interaction.user.id} '/ask' failed with AI service error: {e}"
            )
            await interaction.edit_original_response(
                content="An error occurred while communicating with the AI service."
            )

        except Exception as e:
            logger.error(
                f"Unexpected exception during '/ask' execution: {e}",
                exc_info=True,
            )
            await interaction.edit_original_response(
                content="Something went wrong while running this command."
            )

    @app_commands.command(name="reset-chat", description="Clear your Uno AI conversation memory in this channel.")
    async def reset_chat(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("This command works inside a server.", ephemeral=True)
            return
        cleared = self.chat_orchestrator.clear_memory(
            interaction.guild.id,
            interaction.channel.id,
            interaction.user.id,
        )
        message = "Your chat memory for this channel was cleared." if cleared else "You have no saved chat memory in this channel."
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
