import logging
import sys
import discord
from discord.ext import commands

from config.settings import Settings, load_settings, ConfigError
from bot.services.chat_orchestrator import build_chat_orchestrator
from bot.services.rewards_db import RewardsDBService

logger = logging.getLogger(__name__)


class UnoDiscordBot(commands.Bot):
    """Discord bot client for UNO Discord Bot."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.chat_orchestrator = build_chat_orchestrator(settings)
        self.rewards_service = RewardsDBService(settings.rewards_db_path)

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
            "bot.cogs.weather",
            "bot.cogs.mentions",
            "bot.cogs.forum",
            "bot.cogs.rewards",
            "bot.cogs.community",
            "bot.cogs.bulletin",
            "bot.cogs.prefix",
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


class ColoredConsoleFormatter(logging.Formatter):
    """ANSI colorized log formatter for terminal and Docker console output.

    Colors:
    - CRITICAL / ERROR: Bold / Bright Red (\033[91m)
    - WARNING: Bright Yellow (\033[93m)
    - INFO: Bright Green (\033[92m)
    - DEBUG / DEFAULT: Reset / White (\033[0m)
    """

    COLOR_RESET = "\033[0m"
    COLOR_RED = "\033[91m"
    COLOR_YELLOW = "\033[93m"
    COLOR_GREEN = "\033[92m"
    COLOR_CYAN = "\033[96m"

    LEVEL_COLORS = {
        logging.CRITICAL: COLOR_RED,
        logging.ERROR: COLOR_RED,
        logging.WARNING: COLOR_YELLOW,
        logging.INFO: COLOR_GREEN,
        logging.DEBUG: COLOR_CYAN,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, self.COLOR_RESET)
        formatted = super().format(record)
        return f"{color}{formatted}{self.COLOR_RESET}"


def configure_logging() -> None:
    """Setup clean colorized console + uncolored rotating file logging."""
    import os
    from logging.handlers import RotatingFileHandler

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredConsoleFormatter(log_format))
    handlers: list[logging.Handler] = [console_handler]

    # Write logs to file if LOG_FILE env var is set (recommended for deployment)
    log_file = os.getenv("LOG_FILE", "").strip()
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)

    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        force=True,
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
