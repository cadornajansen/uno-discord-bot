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

    @app_commands.command(name="help", description="List available commands and descriptions.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        """List Phase 1 slash commands and their usage."""
        embed = discord.Embed(
            title="UNO Discord Bot - Help",
            description="Available commands:",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="/ping",
            value="Check bot connection latency.",
            inline=False,
        )
        embed.add_field(
            name="/hello",
            value="Receive a friendly greeting.",
            inline=False,
        )
        embed.add_field(
            name="/userinfo [member]",
            value="View public account details for yourself or another member.",
            inline=False,
        )
        embed.add_field(
            name="/serverinfo",
            value="View details about the current server.",
            inline=False,
        )
        embed.add_field(
            name="/help",
            value="Show this list of commands.",
            inline=False,
        )

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
