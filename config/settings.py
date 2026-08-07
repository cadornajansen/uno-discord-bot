import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


class ConfigError(Exception):
    """Raised when application configuration is missing or invalid."""

    pass


class Settings:
    """Holds validated configuration settings for the bot."""

    def __init__(self, discord_token: str, dev_guild_id: int | None):
        self.discord_token = discord_token
        self.dev_guild_id = dev_guild_id


def load_settings() -> Settings:
    """Load and validate environment configuration.

    Raises:
        ConfigError: If required configuration is missing or invalid.
    """
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "DISCORD_TOKEN is missing or empty. "
            "Please set DISCORD_TOKEN in your environment or .env file."
        )

    guild_id_raw = os.getenv("DEV_GUILD_ID", "").strip()
    dev_guild_id: int | None = None

    if guild_id_raw:
        if not guild_id_raw.isdigit():
            raise ConfigError(
                f"Invalid DEV_GUILD_ID '{guild_id_raw}'. "
                "DEV_GUILD_ID must be a numeric Discord server ID (e.g. 123456789012345678)."
            )
        dev_guild_id = int(guild_id_raw)

    return Settings(discord_token=token, dev_guild_id=dev_guild_id)
