import logging
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.formatting import format_latency, format_timestamp

logger = logging.getLogger(__name__)


class GeneralCog(commands.Cog):
    """Cog containing general utility slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check the bot WebSocket latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Respond with the bot's current WebSocket latency."""
        latency_str = format_latency(self.bot.latency)
        await interaction.response.send_message(f"Pong! {latency_str}")

    @app_commands.command(name="hello", description="Say hello to the bot.")
    async def hello(self, interaction: discord.Interaction) -> None:
        """Greet the user using their server display name."""
        display_name = interaction.user.display_name
        await interaction.response.send_message(f"Hello, {display_name}!")

    @app_commands.command(name="userinfo", description="Display public information about a user.")
    @app_commands.describe(member="The member to view information for (defaults to you).")
    async def userinfo(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        """Display non-sensitive account metadata for the specified or calling user."""
        target = member or interaction.user

        embed = discord.Embed(
            title=f"User Info - {target.display_name}",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Username", value=target.name, inline=True)
        embed.add_field(name="Display Name", value=target.display_name, inline=True)
        embed.add_field(name="User ID", value=str(target.id), inline=False)
        embed.add_field(
            name="Account Created",
            value=format_timestamp(target.created_at, style="F"),
            inline=True,
        )

        # Server join date is only available when target is a Member within a server context
        if isinstance(target, discord.Member) and target.joined_at:
            embed.add_field(
                name="Joined Server",
                value=format_timestamp(target.joined_at, style="F"),
                inline=True,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Display information about the current server.")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        """Display server metadata (name, owner, member count, creation date)."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=guild.name,
            description="Server Information",
            color=discord.Color.green(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Server ID", value=str(guild.id), inline=True)
        
        # Display owner name if available in cache, otherwise show owner ID
        owner_display = str(guild.owner) if guild.owner else f"ID: {guild.owner_id}"
        embed.add_field(name="Owner", value=owner_display, inline=True)
        
        embed.add_field(name="Members", value=str(guild.member_count), inline=True)
        embed.add_field(
            name="Created On",
            value=format_timestamp(guild.created_at, style="F"),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="List all available commands and descriptions.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        """List all slash commands grouped by feature area."""
        embed = discord.Embed(
            title="Uno AI - Command Reference",
            description=(
                "Use `/` slash commands or their `!` prefix equivalents. "
                "Document commands remain slash-only."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="AI & Knowledge",
            value=(
                "`/ask question:<text>` or `!ask <text>` - Ask a question. Grounded in class messages when relevant, "
                "otherwise answered from AI knowledge.\n"
                "`/search query:<text>` or `!search <text>` - Search Google and get the top results."
            ),
            inline=False,
        )

        embed.add_field(
            name="Document Analysis",
            value=(
                "`/analyze file:<attachment>` - Upload a PDF or PPTX and get an AI summary.\n"
                "`/docask question:<text>` - Ask a follow-up question about the last analyzed document.\n"
                "These two commands require `/`; `!analyze` and `!docask` provide guidance only."
            ),
            inline=False,
        )

        embed.add_field(
            name="Academic Schedule",
            value=(
                "`/today` or `!today` - Show today's class schedule.\n"
                "`/schedule` or `!schedule` - Show the full weekly schedule.\n"
                "`/nextclass` or `!nextclass` - Show the next upcoming class.\n"
                "`/prof subject:<name>` or `!prof <name>` - Look up the professor for a subject."
            ),
            inline=False,
        )

        embed.add_field(
            name="Weather",
            value=(
                "`/weather` or `!weather` - Current conditions, 6-hour forecast, official PAGASA warnings, "
                "and class disruption risk (LOW / MODERATE / HIGH)."
            ),
            inline=False,
        )

        embed.add_field(
            name="General & Utility",
            value=(
                "`/ping` or `!ping` - Check bot latency.\n"
                "`/hello` or `!hello` - Say hi.\n"
                "`/userinfo [member]` or `!userinfo [member]` - View public account info.\n"
                "`/serverinfo` or `!serverinfo` - View details about this server.\n"
                "`/about` or `!about` - Learn how Uno AI works.\n"
                "`/help` or `!help` - Show this command list."
            ),
            inline=False,
        )

        embed.add_field(
            name="Passive Features",
            value=(
                "**@Uno AI** - Mention the bot and it replies with something cool.\n"
                "**Knowledge indexing** - Messages in approved channels are automatically "
                "indexed so `/ask` can reference class discussions.\n"
                "**Image OCR** - Homework screenshots in approved channels are scanned "
                "and their text is indexed for `/ask` retrieval."
            ),
            inline=False,
        )

        embed.set_footer(text="Uno AI - Powered by Ollama (phi4-mini) + Qdrant")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="about", description="Learn how Uno AI works in simple terms.")
    async def about_command(self, interaction: discord.Interaction) -> None:
        """Brief friendly explanation of how Uno AI works and why it runs locally."""
        embed = discord.Embed(
            title="How does Uno AI work?",
            color=discord.Color.og_blurple(),
        )

        embed.add_field(
            name="The short version",
            value=(
                "Uno AI is a bot that runs an actual AI model directly on our own computer -- "
                "no sending your messages to OpenAI, Google, or any cloud service. "
                "Everything stays local."
            ),
            inline=False,
        )

        embed.add_field(
            name="What happens when you use /ask",
            value=(
                "1. Your question gets converted into numbers (an embedding) on the local machine.\n"
                "2. Those numbers are compared against indexed class messages stored in a local database (Qdrant).\n"
                "3. If something relevant is found, it's passed to the AI as context.\n"
                "4. The AI model (phi4-mini, running locally via Ollama) generates a response.\n"
                "5. The answer comes back to Discord -- all without leaving the computer."
            ),
            inline=False,
        )

        embed.add_field(
            name="Why does this matter?",
            value=(
                "Large cloud AI services (ChatGPT, Gemini, etc.) run in massive data centers "
                "that consume enormous amounts of electricity and water to stay cool.\n\n"
                "Uno AI runs on a regular computer in the room. "
                "No data center. No water cooling towers. No cloud bill. "
                "Your class messages never leave the machine."
            ),
            inline=False,
        )

        embed.add_field(
            name="What gets stored?",
            value=(
                "Messages from approved channels are saved locally as vector embeddings -- "
                "mathematical representations of meaning, not raw copies of every message. "
                "This is what lets /ask understand context from past class discussions."
            ),
            inline=False,
        )

        embed.set_footer(text="Locally hosted. Privately run. No cloud. No water.")
        await interaction.response.send_message(embed=embed)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Handle errors that occur during execution of app commands in this cog."""
        logger.error(
            f"Error in command '{interaction.command.name}' invoked by {interaction.user}: {error}",
            exc_info=True,
        )
        # Inform user politely without exposing technical stack traces
        message = "Something went wrong while running this command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCog(bot))
