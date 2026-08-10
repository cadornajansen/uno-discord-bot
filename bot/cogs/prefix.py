import logging
from typing import Any, Optional

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class PrefixResponse:
    """Adapt Interaction response methods to a prefix command context."""

    def __init__(self, context: commands.Context):
        self.context = context
        self._is_done = False

    def is_done(self) -> bool:
        return self._is_done

    async def defer(self) -> None:
        """Mark a prefix response as deferred without sending a placeholder."""
        self._is_done = True

    async def send_message(
        self,
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> discord.Message:
        """Send an Interaction-style response as a direct message reply with suppressed link previews."""
        kwargs.pop("ephemeral", None)
        kwargs.setdefault("suppress_embeds", True)
        self._is_done = True
        return await self.context.reply(content=content, **kwargs)


class PrefixFollowup:
    """Adapt Interaction follow-up sends to prefix context replies."""

    def __init__(self, context: commands.Context):
        self.context = context

    async def send(
        self,
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> discord.Message:
        kwargs.pop("ephemeral", None)
        kwargs.setdefault("suppress_embeds", True)
        return await self.context.reply(content=content, **kwargs)


class PrefixInteraction:
    """Expose the Interaction subset used by Uno's existing slash callbacks."""

    def __init__(self, context: commands.Context):
        self.context = context
        self.user = context.author
        self.guild = context.guild
        self.channel = context.channel
        self.response = PrefixResponse(context)
        self.followup = PrefixFollowup(context)

    async def edit_original_response(
        self,
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> discord.Message:
        """Send the first deferred prefix response as a direct message reply with suppressed link previews."""
        kwargs.pop("ephemeral", None)
        kwargs.setdefault("suppress_embeds", True)
        return await self.context.reply(content=content, **kwargs)


class PrefixCommandsCog(commands.Cog):
    """Provide global ! aliases for Uno's non-document slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _invoke_app_command(
        self,
        context: commands.Context,
        cog_name: str,
        command_attribute: str,
        *args: Any,
    ) -> None:
        target_cog = self.bot.get_cog(cog_name)
        if target_cog is None:
            logger.error(f"Prefix command target cog '{cog_name}' is not loaded")
            await context.send("That command is currently unavailable.")
            return

        app_command = getattr(type(target_cog), command_attribute)
        interaction = PrefixInteraction(context)
        await app_command.callback(target_cog, interaction, *args)

    @commands.command(name="ask")
    async def ask_prefix(self, context: commands.Context, *, question: str) -> None:
        """Prefix alias for /ask."""
        await self._invoke_app_command(context, "AICog", "ask", question)

    @commands.command(name="search")
    async def search_prefix(self, context: commands.Context, *, query: str) -> None:
        """Prefix alias for /search."""
        await self._invoke_app_command(context, "SearchCog", "search", query)

    @commands.command(name="ping")
    async def ping_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /ping."""
        await self._invoke_app_command(context, "GeneralCog", "ping")

    @commands.command(name="hello")
    async def hello_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /hello."""
        await self._invoke_app_command(context, "GeneralCog", "hello")

    @commands.command(name="userinfo")
    async def userinfo_prefix(
        self,
        context: commands.Context,
        member: Optional[discord.Member] = None,
    ) -> None:
        """Prefix alias for /userinfo."""
        await self._invoke_app_command(context, "GeneralCog", "userinfo", member)

    @commands.command(name="serverinfo")
    async def serverinfo_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /serverinfo."""
        await self._invoke_app_command(context, "GeneralCog", "serverinfo")

    @commands.command(name="help")
    async def help_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /help."""
        await self._invoke_app_command(context, "GeneralCog", "help_command")

    @commands.command(name="about")
    async def about_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /about."""
        await self._invoke_app_command(context, "GeneralCog", "about_command")

    @commands.command(name="today")
    async def today_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /today."""
        await self._invoke_app_command(context, "AcademicsCog", "today")

    @commands.command(name="schedule")
    async def schedule_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /schedule."""
        await self._invoke_app_command(context, "AcademicsCog", "schedule")

    @commands.command(name="nextclass")
    async def nextclass_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /nextclass."""
        await self._invoke_app_command(context, "AcademicsCog", "nextclass")

    @commands.command(name="prof")
    async def prof_prefix(self, context: commands.Context, *, subject: str) -> None:
        """Prefix alias for /prof."""
        await self._invoke_app_command(context, "AcademicsCog", "prof", subject)

    @commands.command(name="weather")
    async def weather_prefix(self, context: commands.Context) -> None:
        """Prefix alias for /weather."""
        await self._invoke_app_command(context, "WeatherCog", "weather")

    @commands.command(name="analyze")
    async def analyze_slash_only(
        self,
        context: commands.Context,
        *,
        ignored: str = "",
    ) -> None:
        """Explain that document uploads require the slash command UI."""
        await context.reply(
            "Document analysis is slash-only because Discord must provide a file "
            "attachment option. Please use `/analyze`.",
            suppress_embeds=True,
        )

    @commands.command(name="docask")
    async def docask_slash_only(
        self,
        context: commands.Context,
        *,
        ignored: str = "",
    ) -> None:
        """Explain that document follow-up questions remain slash-only."""
        await context.reply(
            "Document questions are slash-only. Please use `/docask` instead.",
            suppress_embeds=True,
        )

    async def cog_command_error(
        self,
        context: commands.Context,
        error: commands.CommandError,
    ) -> None:
        """Return compact usage guidance for prefix parsing errors."""
        if isinstance(error, commands.MissingRequiredArgument):
            usage_by_command = {
                "ask": "!ask <question>",
                "search": "!search <query>",
                "prof": "!prof <subject>",
            }
            command_name = context.command.name if context.command else "command"
            usage = usage_by_command.get(command_name, f"!{command_name}")
            await context.reply(f"Usage: `{usage}`", suppress_embeds=True)
            return

        if isinstance(error, commands.BadArgument):
            await context.reply(
                "I couldn't understand that argument. Try `!help` for usage.",
                suppress_embeds=True,
            )
            return

        logger.error(
            f"Unexpected prefix command error in !{context.command}: {error}",
            exc_info=True,
        )
        await context.reply("Something went wrong while running that command.", suppress_embeds=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrefixCommandsCog(bot))
