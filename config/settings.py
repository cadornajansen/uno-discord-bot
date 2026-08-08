import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


class ConfigError(Exception):
    """Raised when application configuration is missing or invalid."""

    pass


class Settings:
    """Holds validated configuration settings for the bot."""

    def __init__(
        self,
        discord_token: str,
        dev_guild_id: int | None,
        ollama_base_url: str,
        ollama_model: str,
        ollama_embedding_model: str,
        qdrant_url: str,
        qdrant_collection: str,
        indexed_channel_ids: frozenset[int],
        rag_top_k: int,
        rag_min_score: float,
        serper_api_key: str,
        serper_base_url: str,
        search_result_limit: int,
    ):
        self.discord_token = discord_token
        self.dev_guild_id = dev_guild_id
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_model = ollama_model
        self.ollama_embedding_model = ollama_embedding_model
        self.qdrant_url = qdrant_url.rstrip("/")
        self.qdrant_collection = qdrant_collection
        self.indexed_channel_ids = indexed_channel_ids
        self.rag_top_k = rag_top_k
        self.rag_min_score = rag_min_score
        self.serper_api_key = serper_api_key
        self.serper_base_url = serper_base_url.rstrip("/")
        self.search_result_limit = search_result_limit


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

    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
    ollama_model = os.getenv("OLLAMA_MODEL", "phi4-mini").strip()
    ollama_embedding_model = os.getenv(
        "OLLAMA_EMBEDDING_MODEL", "embeddinggemma"
    ).strip()

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333").strip()
    qdrant_collection = os.getenv("QDRANT_COLLECTION", "discord_messages").strip()

    channels_raw = os.getenv("INDEXED_CHANNEL_IDS", "").strip()
    indexed_channel_ids: set[int] = set()

    if channels_raw:
        for part in channels_raw.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            if not cleaned.isdigit():
                raise ConfigError(
                    f"Invalid channel ID '{cleaned}' in INDEXED_CHANNEL_IDS. "
                    "All channel IDs must be numeric integers."
                )
            indexed_channel_ids.add(int(cleaned))

    rag_top_k_raw = os.getenv("RAG_TOP_K", "5").strip()
    if not rag_top_k_raw.isdigit() or int(rag_top_k_raw) <= 0:
        raise ConfigError("RAG_TOP_K must be a positive integer.")
    rag_top_k = int(rag_top_k_raw)

    rag_min_score_raw = os.getenv("RAG_MIN_SCORE", "0.30").strip()
    try:
        rag_min_score = float(rag_min_score_raw)
        if not (0.0 <= rag_min_score <= 1.0):
            raise ValueError()
    except ValueError:
        raise ConfigError("RAG_MIN_SCORE must be a float between 0.0 and 1.0.")

    serper_api_key = os.getenv("SERPER_API_KEY", "").strip()
    serper_base_url = os.getenv("SERPER_BASE_URL", "https://google.serper.dev").strip()

    search_limit_raw = os.getenv("SEARCH_RESULT_LIMIT", "5").strip()
    if not search_limit_raw.isdigit() or not (1 <= int(search_limit_raw) <= 10):
        raise ConfigError("SEARCH_RESULT_LIMIT must be an integer between 1 and 10.")
    search_result_limit = int(search_limit_raw)

    return Settings(
        discord_token=token,
        dev_guild_id=dev_guild_id,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_embedding_model=ollama_embedding_model,
        qdrant_url=qdrant_url,
        qdrant_collection=qdrant_collection,
        indexed_channel_ids=frozenset(indexed_channel_ids),
        rag_top_k=rag_top_k,
        rag_min_score=rag_min_score,
        serper_api_key=serper_api_key,
        serper_base_url=serper_base_url,
        search_result_limit=search_result_limit,
    )
