from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.cogs.community import CommunityCog
from bot.services.bulletin import AnySearchNewsClient, BulletinArticle, BulletinState
from bot.services.community_games import CommunityGamesService
from bot.services.rewards_db import RewardsDBService


logger = logging.getLogger(__name__)
PHT = timezone(timedelta(hours=8))


class BulletinCog(commands.Cog):
    """Scheduled technology news and Uno economy reporting."""

    bulletin_group = app_commands.Group(name="bulletin", description="Read or manage the Uno AI Bulletin.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        rewards = getattr(bot, "rewards_service", None)
        if not isinstance(rewards, RewardsDBService):
            raise RuntimeError("BulletinCog requires the shared RewardsDBService.")
        self.state = BulletinState(rewards)
        self.community = CommunityGamesService(rewards)
        settings = bot.settings
        self.news = AnySearchNewsClient(getattr(settings, "anysearch_api_key", ""))
        self.enabled = bool(getattr(settings, "bulletin_enabled", True))
        self.chismis_channel_id = int(getattr(settings, "bulletin_chismis_channel_id", 1531615193786876062))
        self.bot_channel_id = int(getattr(settings, "bulletin_bot_channel_id", 1533779047480299690))

    async def cog_load(self) -> None:
        if self.enabled:
            self.scheduler.start()

    async def cog_unload(self) -> None:
        if self.scheduler.is_running():
            self.scheduler.cancel()

    async def _channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        if not hasattr(channel, "send"):
            raise RuntimeError(f"Bulletin channel {channel_id} cannot receive messages.")
        return channel

    @staticmethod
    def _embed(articles: list[BulletinArticle], digest: bool) -> discord.Embed:
        embed = discord.Embed(
            title="Uno AI Bulletin — Tech Brief" if digest else "Uno AI Bulletin — Tech Flash",
            description="Philippines-first technology updates with selected global context.",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        for article in articles:
            summary = article.summary or "Open the source for the full report."
            embed.add_field(
                name=article.title[:256],
                value=f"{summary[:700]}\n[Read at {article.source}]({article.url})",
                inline=False,
            )
        embed.set_footer(text="Uno AI Bulletin · Sources linked above")
        return embed

    async def publish_news(self, channel_id: int, digest: bool) -> int:
        queries = [
            "latest Philippines technology news AI cybersecurity startups telecom today",
            "latest global technology news today important developments",
        ] if digest else ["latest Philippines technology breaking news today"]
        articles = await self.news.search(queries, max_results=5)
        fresh = self.state.filter_new(articles, channel_id=channel_id)
        chosen = fresh[:4 if digest else 1]
        if not chosen:
            return 0
        channel = await self._channel(channel_id)
        await channel.send(embed=self._embed(chosen, digest=digest), allowed_mentions=discord.AllowedMentions.none())
        for article in chosen:
            self.state.mark_posted(article, channel_id)
        return len(chosen)

    async def publish_economy_pulse(self) -> None:
        report = self.community.capture_economy_pulse(hours=6)
        channel = await self._channel(self.chismis_channel_id)
        await channel.send(CommunityCog.format_pulse(report), allowed_mentions=discord.AllowedMentions.none())

    async def _run_once(self, run_key: str, operation) -> None:
        if self.state.has_run(run_key):
            return
        try:
            detail = await operation()
            self.state.record_run(run_key, "OK", str(detail or "completed"))
        except Exception as error:
            logger.warning("[bulletin] Run %s failed: %s", run_key, error, exc_info=True)
            self.state.record_run(run_key, "ERROR", str(error))

    @tasks.loop(minutes=5)
    async def scheduler(self) -> None:
        now = datetime.now(PHT)
        hour_key = now.strftime("%Y-%m-%dT%H")
        await self._run_once(
            f"flash:{hour_key}",
            lambda: self.publish_news(self.bot_channel_id, digest=False),
        )
        if now.hour % 12 == 0:
            await self._run_once(
                f"digest:{hour_key}",
                lambda: self.publish_news(self.chismis_channel_id, digest=True),
            )
        if now.hour % 6 == 0:
            await self._run_once(
                f"economy:{hour_key}",
                self.publish_economy_pulse,
            )

    @scheduler.before_loop
    async def before_scheduler(self) -> None:
        await self.bot.wait_until_ready()

    @bulletin_group.command(name="latest", description="Show links from the most recently posted bulletins.")
    async def bulletin_latest(self, interaction: discord.Interaction) -> None:
        latest = self.state.latest()
        if not latest:
            await interaction.response.send_message("No bulletin articles have been posted yet.", ephemeral=True)
            return
        lines = [f"[{item['title']}]({item['url']}) — {item['source']}" for item in latest]
        await interaction.response.send_message("**Latest Uno AI Bulletin links**\n" + "\n".join(lines), ephemeral=True)

    @bulletin_group.command(name="status", description="Show the scheduler's most recent run. Administrators only.")
    @app_commands.default_permissions(administrator=True)
    async def bulletin_status(self, interaction: discord.Interaction) -> None:
        status = self.state.status()
        await interaction.response.send_message(
            f"Enabled: `{self.enabled}`\nLatest run: `{status or 'none'}`",
            ephemeral=True,
        )

    @bulletin_group.command(name="publish", description="Publish a tech digest in this channel. Administrators only.")
    @app_commands.default_permissions(administrator=True)
    async def bulletin_publish(self, interaction: discord.Interaction) -> None:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not permissions or not permissions.administrator:
            await interaction.response.send_message("Administrator permission is required.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        count = await self.publish_news(interaction.channel_id, digest=True)
        await interaction.edit_original_response(content=f"Published {count} new bulletin item(s).")

    @commands.group(name="bulletin", invoke_without_command=True)
    async def bulletin_prefix(self, context: commands.Context) -> None:
        await context.reply("Use `!bulletin latest` or `!bulletin publish`.")

    @bulletin_prefix.command(name="latest")
    async def bulletin_latest_prefix(self, context: commands.Context) -> None:
        latest = self.state.latest()
        lines = [f"[{item['title']}]({item['url']}) — {item['source']}" for item in latest]
        await context.reply("**Latest Uno AI Bulletin links**\n" + ("\n".join(lines) or "No articles yet."))

    @bulletin_prefix.command(name="publish")
    @commands.has_permissions(administrator=True)
    async def bulletin_publish_prefix(self, context: commands.Context) -> None:
        count = await self.publish_news(context.channel.id, digest=True)
        await context.reply(f"Published {count} new bulletin item(s).")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BulletinCog(bot))
