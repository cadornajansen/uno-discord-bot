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
from bot.utils.formatting import split_message

logger = logging.getLogger(__name__)

# Input validation limit for user prompts (in characters)
MAX_PROMPT_LENGTH = 2000


class AICog(commands.Cog):
    """Cog for local Ollama AI interaction slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Initialize AIService using configuration settings from bot client
        settings = getattr(bot, "settings", None)
        base_url = settings.ollama_base_url if settings else "http://localhost:11434"
        model = settings.ollama_model if settings else "phi4-mini"

        self.ai_service = AIService(base_url=base_url, model=model)

    @app_commands.command(name="ask", description="Ask the local AI assistant a question.")
    @app_commands.describe(question="The question or prompt to ask the AI assistant.")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        """Slash command /ask question:<text>"""
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

        # Discord interactions must be acknowledged quickly (<3s), while local
        # inference may take several seconds, so defer before calling Ollama.
        await interaction.response.defer()

        try:
            response_text = await self.ai_service.ask(cleaned_question)

            chunks = split_message(response_text, limit=2000)
            if not chunks:
                await interaction.followup.send("The AI returned an empty response.")
                return

            # Send first chunk via interaction followup
            await interaction.followup.send(chunks[0])

            # Send remaining chunks if response exceeded 2000 characters
            for chunk in chunks[1:]:
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
                f"User {interaction.user.id} '/ask' failed: Model '{self.ai_service.model}' not found."
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
