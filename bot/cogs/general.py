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
                "You can also mention Uno naturally. Document commands remain slash-only."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="AI & Knowledge",
            value=(
                "`/ask question:<text>` or `!ask <text>` - Chat with Uno. Class questions can use "
                "assignments, announcements, schedules, subjects, and professor data.\n"
                "`/reset-chat` or `!reset-chat` - Clear only your chat memory in this channel.\n"
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
                "**Mention Uno with a question** - `@Uno AI what's due Friday?` works anywhere "
                "in the message. A mention by itself gets a quick static reply.\n"
                "**Reply to Uno** - Continue the conversation without repeating the original question.\n"
                "**Private short-term memory** - History is separated by user and channel, bounded, "
                "and expires automatically.\n"
                "**Approved-channel indexing** - New homework and announcement posts become searchable.\n"
                "**Image OCR** - Homework screenshots in approved channels can also be indexed."
            ),
            inline=False,
        )

        embed.set_footer(text="Uno AI - AssemblyAI LLM Gateway + Gemini Embeddings + Qdrant")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="about", description="Learn how Uno AI works in simple terms.")
    async def about_command(self, interaction: discord.Interaction) -> None:
        """Brief explanation of Uno AI's retrieval and generation flow."""
        embed = discord.Embed(
            title="How does Uno AI work?",
            color=discord.Color.og_blurple(),
        )

        embed.add_field(
            name="The short version",
            value=(
                "Uno is a class assistant with short-term per-user memory and a small set of "
                "read-only class tools. Gemini 3.5 Flash generates replies through AssemblyAI's "
                "LLM Gateway."
            ),
            inline=False,
        )

        embed.add_field(
            name="How a chat request works",
            value=(
                "1. Uno loads your small conversation history for this server channel.\n"
                "2. Clear class questions are routed to a trusted read-only tool.\n"
                "3. Assignment searches prefer newer, structured homework and announcement posts.\n"
                "4. Relative dates such as today, tomorrow, and Friday use Asia/Manila.\n"
                "5. Gemini produces the final Discord reply using only the relevant results."
            ),
            inline=False,
        )

        embed.add_field(
            name="What Uno can check",
            value=(
                "Uno can check approved homework and announcement posts, the class schedule, "
                "subject abbreviations, and professor information. General conversation does "
                "not automatically search the class index."
            ),
            inline=False,
        )

        embed.add_field(
            name="Memory, storage, and privacy",
            value=(
                "Only approved-channel messages and metadata are indexed in Qdrant. Chat memory "
                "keeps at most four completed turns per user and channel, expires after 30 minutes, "
                "and resets when the bot restarts. `/reset-chat` clears it early. Operational logs "
                "record request timing and token counts, never message content or API keys."
            ),
            inline=False,
        )

        embed.add_field(
            name="If retrieval is unavailable",
            value=(
                "A Qdrant or Gemini embedding outage only affects searchable class messages. "
                "Schedule, subject, and professor lookups continue using trusted local academic data."
            ),
            inline=False,
        )

        embed.set_footer(text="Bounded memory, controlled indexing, and read-only class tools")
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
