import logging
import sys
import discord
from discord.ext import commands

from config.settings import Settings, load_settings, ConfigError

logger = logging.getLogger(__name__)


class UnoDiscordBot(commands.Bot):
    """Discord bot client for UNO Discord Bot."""

    def __init__(self, settings: Settings):
        self.settings = settings

        # Request required default intents + message_content intent for Phase 2B message ingestion
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        """Asynchronous initialization executed prior to bot login."""
        # Load cogs
        cogs_to_load = [
            "bot.cogs.general",
            "bot.cogs.ai",
            "bot.cogs.knowledge",
            "bot.cogs.search",
            "bot.cogs.documents",
            "bot.cogs.academics",
        ]
        for extension in cogs_to_load:
            try:
                await self.load_extension(extension)
                logger.info(f"Loaded cog: {extension}")
            except Exception as e:
                logger.error(f"Failed to load cog {extension}: {e}", exc_info=True)

        # Guild-scoped commands are used during development because
        # Discord propagates guild-specific slash commands instantly, whereas
        # global command registration can take up to an hour to propagate.
        if self.settings.dev_guild_id:
            dev_guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=dev_guild)
            synced = await self.tree.sync(guild=dev_guild)
            logger.info(
                f"Synced {len(synced)} command(s) to development guild (ID: {self.settings.dev_guild_id})"
            )
        else:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) globally")

    async def on_ready(self) -> None:
        """Event listener triggered when the bot establishes a connection to Discord."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/help",
            )
        )


def configure_logging() -> None:
    """Setup clean console logging formatting."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def run_bot() -> None:
    """Main execution function to load configuration and launch the bot."""
    configure_logging()
    logger.info("Starting UNO Discord Bot...")

    try:
        settings = load_settings()
    except ConfigError as e:
        logger.critical(f"Configuration error: {e}")
        sys.exit(1)

    bot = UnoDiscordBot(settings=settings)
    bot.run(settings.discord_token)
