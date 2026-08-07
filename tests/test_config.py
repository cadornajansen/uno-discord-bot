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
