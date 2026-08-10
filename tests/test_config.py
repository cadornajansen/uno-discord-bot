import pytest
from config.settings import load_settings, ConfigError


def test_valid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading valid DISCORD_TOKEN and numeric DEV_GUILD_ID."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_secret_token_123")
    monkeypatch.setenv("DEV_GUILD_ID", "987654321098765432")
    monkeypatch.setenv("INDEXED_CHANNEL_IDS", "")

    settings = load_settings()
    assert settings.discord_token == "mock_secret_token_123"
    assert settings.dev_guild_id == 987654321098765432
    assert settings.indexed_channel_ids == frozenset()


def test_rag_and_generation_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Phase 7A settings use conservative defaults."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
    monkeypatch.delenv("RAG_MIN_SCORE", raising=False)
    monkeypatch.delenv("RAG_MAX_CONTEXT_RESULTS", raising=False)
    monkeypatch.delenv("ASSEMBLYAI_LLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("GEMINI_EMBEDDING_DIMENSIONS", raising=False)

    settings = load_settings()

    assert settings.rag_min_score == 0.50
    assert settings.rag_max_context_results == 3
    assert settings.assemblyai_llm_max_tokens == 400
    assert settings.assemblyai_llm_model == "gemini-3.5-flash"
    assert settings.gemini_embedding_model == "gemini-embedding-2"
    assert settings.gemini_embedding_dimensions == 768
    assert settings.chat_memory_max_turns == 4
    assert settings.chat_memory_ttl_minutes == 30
    assert settings.chat_memory_max_tokens == 1200
    assert settings.chat_max_tool_rounds == 2


def test_ai_provider_urls_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generation and embedding providers are independently configurable."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
    monkeypatch.setenv("ASSEMBLYAI_LLM_BASE_URL", "https://gateway.example.com/v1/")
    monkeypatch.setenv("GEMINI_EMBEDDING_BASE_URL", "https://gemini.example.com/v1beta/")

    settings = load_settings()

    assert settings.assemblyai_llm_base_url == "https://gateway.example.com/v1"
    assert settings.gemini_embedding_base_url == "https://gemini.example.com/v1beta"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("RAG_MAX_CONTEXT_RESULTS", "0", "RAG_MAX_CONTEXT_RESULTS"),
        ("ASSEMBLYAI_LLM_MAX_TOKENS", "none", "ASSEMBLYAI_LLM_MAX_TOKENS"),
        ("GEMINI_EMBEDDING_DIMENSIONS", "0", "GEMINI_EMBEDDING_DIMENSIONS"),
    ],
)
def test_invalid_positive_integer_settings(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    """Test new integer settings reject zero and non-numeric values."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match=message):
        load_settings()


def test_optional_dev_guild_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading settings when DEV_GUILD_ID is omitted or empty."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_secret_token_123")
    monkeypatch.delenv("DEV_GUILD_ID", raising=False)
    monkeypatch.setenv("INDEXED_CHANNEL_IDS", "")

    settings = load_settings()
    assert settings.discord_token == "mock_secret_token_123"
    assert settings.dev_guild_id is None


def test_missing_discord_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that ConfigError is raised when DISCORD_TOKEN is missing or empty."""
    monkeypatch.setenv("DISCORD_TOKEN", "")
    monkeypatch.setenv("INDEXED_CHANNEL_IDS", "")

    with pytest.raises(ConfigError, match="DISCORD_TOKEN is missing"):
        load_settings()


def test_invalid_dev_guild_id_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that ConfigError is raised when DEV_GUILD_ID is non-numeric."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_secret_token_123")
    monkeypatch.setenv("DEV_GUILD_ID", "invalid_not_a_number")
    monkeypatch.setenv("INDEXED_CHANNEL_IDS", "")

    with pytest.raises(ConfigError, match="Invalid DEV_GUILD_ID"):
        load_settings()


def test_indexed_channel_ids_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test parsing INDEXED_CHANNEL_IDS into frozenset[int]."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
    monkeypatch.setenv(
        "INDEXED_CHANNEL_IDS",
        "123456789012345678, 987654321098765432 , 123456789012345678",
    )

    settings = load_settings()
    assert settings.indexed_channel_ids == frozenset(
        {123456789012345678, 987654321098765432}
    )


def test_empty_indexed_channel_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that an empty INDEXED_CHANNEL_IDS returns an empty frozenset."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
    monkeypatch.setenv("INDEXED_CHANNEL_IDS", "  ")

    settings = load_settings()
    assert settings.indexed_channel_ids == frozenset()


def test_invalid_indexed_channel_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that ConfigError is raised when INDEXED_CHANNEL_IDS contains non-numeric values."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
    monkeypatch.setenv("INDEXED_CHANNEL_IDS", "123456789, invalid_id")

    with pytest.raises(ConfigError, match="Invalid channel ID 'invalid_id'"):
        load_settings()


def test_ocr_channel_ids_and_settings_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test parsing OCR_CHANNEL_IDS, OCR_MAX_IMAGE_MB, OCR_MIN_TEXT_CHARS, OCR_MAX_IMAGES_PER_MESSAGE."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
    monkeypatch.setenv("INDEXED_CHANNEL_IDS", "100, 200")
    monkeypatch.setenv("OCR_CHANNEL_IDS", "200, 300")
    monkeypatch.setenv("OCR_MAX_IMAGE_MB", "12")
    monkeypatch.setenv("OCR_MIN_TEXT_CHARS", "15")
    monkeypatch.setenv("OCR_MAX_IMAGES_PER_MESSAGE", "5")

    settings = load_settings()
    assert settings.ocr_channel_ids == frozenset({200, 300})
    assert settings.ocr_max_image_mb == 12
    assert settings.ocr_min_text_chars == 15
    assert settings.ocr_max_images_per_message == 5
