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
        assemblyai_api_key: str,
        assemblyai_llm_base_url: str,
        assemblyai_llm_model: str,
        assemblyai_llm_timeout_seconds: float,
        assemblyai_llm_max_tokens: int,
        gemini_api_key: str,
        gemini_embedding_base_url: str,
        gemini_embedding_model: str,
        gemini_embedding_dimensions: int,
        gemini_embedding_timeout_seconds: float,
        qdrant_url: str,
        qdrant_collection: str,
        indexed_channel_ids: frozenset[int],
        assignment_channel_ids: frozenset[int],
        rag_top_k: int,
        rag_min_score: float,
        rag_max_context_results: int,
        serper_api_key: str,
        serper_base_url: str,
        search_result_limit: int,
        document_max_size_mb: int,
        document_max_chars: int,
        document_session_ttl_minutes: int,
        academic_school_year: str,
        academic_semester: int,
        academic_timezone: str,
        weather_latitude: float,
        weather_longitude: float,
        weather_location_name: str,
        weather_timezone: str,
        pagasa_ncr_url: str,
        ocr_channel_ids: frozenset[int],
        ocr_max_image_mb: int,
        ocr_min_text_chars: int,
        ocr_max_images_per_message: int,
        forum_channel_ids: frozenset[int],
        chat_memory_max_turns: int,
        chat_memory_ttl_minutes: int,
        chat_memory_max_tokens: int,
        chat_max_tool_rounds: int,
    ):
        self.discord_token = discord_token
        self.dev_guild_id = dev_guild_id
        self.assemblyai_api_key = assemblyai_api_key
        self.assemblyai_llm_base_url = assemblyai_llm_base_url.rstrip("/")
        self.assemblyai_llm_model = assemblyai_llm_model
        self.assemblyai_llm_timeout_seconds = assemblyai_llm_timeout_seconds
        self.assemblyai_llm_max_tokens = assemblyai_llm_max_tokens
        self.gemini_api_key = gemini_api_key
        self.gemini_embedding_base_url = gemini_embedding_base_url.rstrip("/")
        self.gemini_embedding_model = gemini_embedding_model
        self.gemini_embedding_dimensions = gemini_embedding_dimensions
        self.gemini_embedding_timeout_seconds = gemini_embedding_timeout_seconds
        self.qdrant_url = qdrant_url.rstrip("/")
        self.qdrant_collection = qdrant_collection
        self.indexed_channel_ids = indexed_channel_ids
        self.assignment_channel_ids = assignment_channel_ids
        self.rag_top_k = rag_top_k
        self.rag_min_score = rag_min_score
        self.rag_max_context_results = rag_max_context_results
        self.serper_api_key = serper_api_key
        self.serper_base_url = serper_base_url.rstrip("/")
        self.search_result_limit = search_result_limit
        self.document_max_size_mb = document_max_size_mb
        self.document_max_chars = document_max_chars
        self.document_session_ttl_minutes = document_session_ttl_minutes
        self.academic_school_year = academic_school_year
        self.academic_semester = academic_semester
        self.academic_timezone = academic_timezone
        self.weather_latitude = weather_latitude
        self.weather_longitude = weather_longitude
        self.weather_location_name = weather_location_name
        self.weather_timezone = weather_timezone
        self.pagasa_ncr_url = pagasa_ncr_url.strip()
        self.ocr_channel_ids = ocr_channel_ids
        self.ocr_max_image_mb = ocr_max_image_mb
        self.ocr_min_text_chars = ocr_min_text_chars
        self.ocr_max_images_per_message = ocr_max_images_per_message
        self.forum_channel_ids = forum_channel_ids
        self.chat_memory_max_turns = chat_memory_max_turns
        self.chat_memory_ttl_minutes = chat_memory_ttl_minutes
        self.chat_memory_max_tokens = chat_memory_max_tokens
        self.chat_max_tool_rounds = chat_max_tool_rounds


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

    assemblyai_api_key = os.getenv("ASSEMBLYAI_API_KEY", "").strip()
    assemblyai_llm_base_url = os.getenv(
        "ASSEMBLYAI_LLM_BASE_URL", "https://llm-gateway.assemblyai.com/v1"
    ).strip()
    assemblyai_llm_model = os.getenv(
        "ASSEMBLYAI_LLM_MODEL", "gemini-3.5-flash"
    ).strip()

    timeout_raw = os.getenv("ASSEMBLYAI_LLM_TIMEOUT_SECONDS", "60.0").strip()
    try:
        assemblyai_llm_timeout_seconds = float(timeout_raw)
        if assemblyai_llm_timeout_seconds <= 0:
            raise ValueError()
    except ValueError:
        raise ConfigError("ASSEMBLYAI_LLM_TIMEOUT_SECONDS must be a positive float.")

    assemblyai_llm_max_tokens_raw = os.getenv(
        "ASSEMBLYAI_LLM_MAX_TOKENS", "1000"
    ).strip()
    if (
        not assemblyai_llm_max_tokens_raw.isdigit()
        or int(assemblyai_llm_max_tokens_raw) <= 0
    ):
        raise ConfigError("ASSEMBLYAI_LLM_MAX_TOKENS must be a positive integer.")
    assemblyai_llm_max_tokens = int(assemblyai_llm_max_tokens_raw)

    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_embedding_base_url = os.getenv(
        "GEMINI_EMBEDDING_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    ).strip()
    gemini_embedding_model = os.getenv(
        "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2"
    ).strip()

    dimensions_raw = os.getenv("GEMINI_EMBEDDING_DIMENSIONS", "768").strip()
    if not dimensions_raw.isdigit() or not (128 <= int(dimensions_raw) <= 3072):
        raise ConfigError(
            "GEMINI_EMBEDDING_DIMENSIONS must be an integer between 128 and 3072."
        )
    gemini_embedding_dimensions = int(dimensions_raw)

    embedding_timeout_raw = os.getenv(
        "GEMINI_EMBEDDING_TIMEOUT_SECONDS", "30.0"
    ).strip()
    try:
        gemini_embedding_timeout_seconds = float(embedding_timeout_raw)
        if gemini_embedding_timeout_seconds <= 0:
            raise ValueError()
    except ValueError:
        raise ConfigError("GEMINI_EMBEDDING_TIMEOUT_SECONDS must be a positive float.")

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333").strip()
    qdrant_collection = os.getenv(
        "QDRANT_COLLECTION", "discord_messages_gemini_v1"
    ).strip()

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

    assignment_channels_raw = os.getenv(
        "ASSIGNMENT_CHANNEL_IDS",
        "1531615193786876064,1531615193786876063",
    ).strip()
    assignment_channel_ids: set[int] = set()
    if assignment_channels_raw:
        for part in assignment_channels_raw.split(","):
            cleaned = part.strip()
            if not cleaned or not cleaned.isdigit():
                raise ConfigError("ASSIGNMENT_CHANNEL_IDS must contain only numeric channel IDs.")
            assignment_channel_ids.add(int(cleaned))

    rag_top_k_raw = os.getenv("RAG_TOP_K", "5").strip()
    if not rag_top_k_raw.isdigit() or int(rag_top_k_raw) <= 0:
        raise ConfigError("RAG_TOP_K must be a positive integer.")
    rag_top_k = int(rag_top_k_raw)

    rag_min_score_raw = os.getenv("RAG_MIN_SCORE", "0.50").strip()
    try:
        rag_min_score = float(rag_min_score_raw)
        if not (0.0 <= rag_min_score <= 1.0):
            raise ValueError()
    except ValueError:
        raise ConfigError("RAG_MIN_SCORE must be a float between 0.0 and 1.0.")

    rag_max_context_results_raw = os.getenv("RAG_MAX_CONTEXT_RESULTS", "3").strip()
    if (
        not rag_max_context_results_raw.isdigit()
        or int(rag_max_context_results_raw) <= 0
    ):
        raise ConfigError("RAG_MAX_CONTEXT_RESULTS must be a positive integer.")
    rag_max_context_results = int(rag_max_context_results_raw)

    serper_api_key = os.getenv("SERPER_API_KEY", "").strip()
    serper_base_url = os.getenv("SERPER_BASE_URL", "https://google.serper.dev").strip()

    search_limit_raw = os.getenv("SEARCH_RESULT_LIMIT", "5").strip()
    if not search_limit_raw.isdigit() or not (1 <= int(search_limit_raw) <= 10):
        raise ConfigError("SEARCH_RESULT_LIMIT must be an integer between 1 and 10.")
    search_result_limit = int(search_limit_raw)

    doc_size_raw = os.getenv("DOCUMENT_MAX_SIZE_MB", "15").strip()
    if not doc_size_raw.isdigit() or int(doc_size_raw) <= 0:
        raise ConfigError("DOCUMENT_MAX_SIZE_MB must be a positive integer.")
    document_max_size_mb = int(doc_size_raw)

    doc_chars_raw = os.getenv("DOCUMENT_MAX_CHARS", "20000").strip()
    if not doc_chars_raw.isdigit() or int(doc_chars_raw) <= 0:
        raise ConfigError("DOCUMENT_MAX_CHARS must be a positive integer.")
    document_max_chars = int(doc_chars_raw)

    ttl_raw = os.getenv("DOCUMENT_SESSION_TTL_MINUTES", "30").strip()
    if not ttl_raw.isdigit() or int(ttl_raw) <= 0:
        raise ConfigError("DOCUMENT_SESSION_TTL_MINUTES must be a positive integer.")
    document_session_ttl_minutes = int(ttl_raw)

    academic_school_year = os.getenv("ACADEMIC_SCHOOL_YEAR", "2026-2027").strip()

    semester_raw = os.getenv("ACADEMIC_SEMESTER", "1").strip()
    if not semester_raw.isdigit() or int(semester_raw) <= 0:
        raise ConfigError("ACADEMIC_SEMESTER must be a positive integer.")
    academic_semester = int(semester_raw)

    academic_timezone = os.getenv("ACADEMIC_TIMEZONE", "Asia/Manila").strip()

    lat_raw = os.getenv("WEATHER_LATITUDE", "14.5869").strip()
    try:
        weather_latitude = float(lat_raw)
        if not (-90.0 <= weather_latitude <= 90.0):
            raise ValueError()
    except ValueError:
        raise ConfigError("WEATHER_LATITUDE must be a float between -90.0 and 90.0.")

    lon_raw = os.getenv("WEATHER_LONGITUDE", "120.9762").strip()
    try:
        weather_longitude = float(lon_raw)
        if not (-180.0 <= weather_longitude <= 180.0):
            raise ValueError()
    except ValueError:
        raise ConfigError("WEATHER_LONGITUDE must be a float between -180.0 and 180.0.")

    weather_location_name = os.getenv("WEATHER_LOCATION_NAME", "Manila (PLM)").strip()
    weather_timezone = os.getenv("WEATHER_TIMEZONE", "Asia/Manila").strip()

    pagasa_ncr_url = os.getenv(
        "PAGASA_NCR_URL", "https://www.pagasa.dost.gov.ph/regional-forecast/ncrprsd"
    ).strip()

    ocr_channels_raw = os.getenv("OCR_CHANNEL_IDS", "").strip()
    ocr_channel_ids: set[int] = set()

    if ocr_channels_raw:
        for part in ocr_channels_raw.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            if not cleaned.isdigit():
                raise ConfigError(
                    f"Invalid channel ID '{cleaned}' in OCR_CHANNEL_IDS. "
                    "All channel IDs must be numeric integers."
                )
            ocr_channel_ids.add(int(cleaned))

    ocr_max_image_mb_raw = os.getenv("OCR_MAX_IMAGE_MB", "8").strip()
    if not ocr_max_image_mb_raw.isdigit() or int(ocr_max_image_mb_raw) <= 0:
        raise ConfigError("OCR_MAX_IMAGE_MB must be a positive integer.")
    ocr_max_image_mb = int(ocr_max_image_mb_raw)

    ocr_min_text_chars_raw = os.getenv("OCR_MIN_TEXT_CHARS", "10").strip()
    if not ocr_min_text_chars_raw.isdigit() or int(ocr_min_text_chars_raw) <= 0:
        raise ConfigError("OCR_MIN_TEXT_CHARS must be a positive integer.")
    ocr_min_text_chars = int(ocr_min_text_chars_raw)

    ocr_max_images_per_message_raw = os.getenv("OCR_MAX_IMAGES_PER_MESSAGE", "3").strip()
    if not ocr_max_images_per_message_raw.isdigit() or int(ocr_max_images_per_message_raw) <= 0:
        raise ConfigError("OCR_MAX_IMAGES_PER_MESSAGE must be a positive integer.")
    ocr_max_images_per_message = int(ocr_max_images_per_message_raw)

    forum_channels_raw = os.getenv(
        "FORUM_CHANNEL_IDS", "1538209328018886676"
    ).strip()
    forum_channel_ids: set[int] = set()
    if forum_channels_raw:
        for part in forum_channels_raw.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            if not cleaned.isdigit():
                raise ConfigError(
                    f"Invalid channel ID '{cleaned}' in FORUM_CHANNEL_IDS. "
                    "All channel IDs must be numeric integers."
                )
            forum_channel_ids.add(int(cleaned))

    chat_memory_max_turns = _positive_int_env("CHAT_MEMORY_MAX_TURNS", "4")
    chat_memory_ttl_minutes = _positive_int_env("CHAT_MEMORY_TTL_MINUTES", "30")
    chat_memory_max_tokens = _positive_int_env("CHAT_MEMORY_MAX_TOKENS", "1200")
    chat_max_tool_rounds = _positive_int_env("CHAT_MAX_TOOL_ROUNDS", "2")

    return Settings(
        discord_token=token,
        dev_guild_id=dev_guild_id,
        assemblyai_api_key=assemblyai_api_key,
        assemblyai_llm_base_url=assemblyai_llm_base_url,
        assemblyai_llm_model=assemblyai_llm_model,
        assemblyai_llm_timeout_seconds=assemblyai_llm_timeout_seconds,
        assemblyai_llm_max_tokens=assemblyai_llm_max_tokens,
        gemini_api_key=gemini_api_key,
        gemini_embedding_base_url=gemini_embedding_base_url,
        gemini_embedding_model=gemini_embedding_model,
        gemini_embedding_dimensions=gemini_embedding_dimensions,
        gemini_embedding_timeout_seconds=gemini_embedding_timeout_seconds,
        qdrant_url=qdrant_url,
        qdrant_collection=qdrant_collection,
        indexed_channel_ids=frozenset(indexed_channel_ids),
        assignment_channel_ids=frozenset(assignment_channel_ids),
        rag_top_k=rag_top_k,
        rag_min_score=rag_min_score,
        rag_max_context_results=rag_max_context_results,
        serper_api_key=serper_api_key,
        serper_base_url=serper_base_url,
        search_result_limit=search_result_limit,
        document_max_size_mb=document_max_size_mb,
        document_max_chars=document_max_chars,
        document_session_ttl_minutes=document_session_ttl_minutes,
        academic_school_year=academic_school_year,
        academic_semester=academic_semester,
        academic_timezone=academic_timezone,
        weather_latitude=weather_latitude,
        weather_longitude=weather_longitude,
        weather_location_name=weather_location_name,
        weather_timezone=weather_timezone,
        pagasa_ncr_url=pagasa_ncr_url,
        ocr_channel_ids=frozenset(ocr_channel_ids),
        ocr_max_image_mb=ocr_max_image_mb,
        ocr_min_text_chars=ocr_min_text_chars,
        ocr_max_images_per_message=ocr_max_images_per_message,
        forum_channel_ids=frozenset(forum_channel_ids),
        chat_memory_max_turns=chat_memory_max_turns,
        chat_memory_ttl_minutes=chat_memory_ttl_minutes,
        chat_memory_max_tokens=chat_memory_max_tokens,
        chat_max_tool_rounds=chat_max_tool_rounds,
    )


def _positive_int_env(name: str, default: str) -> int:
    raw = os.getenv(name, default).strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ConfigError(f"{name} must be a positive integer.")
    return int(raw)
