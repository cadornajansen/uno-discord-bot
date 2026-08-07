import pytest
from config.settings import load_settings, ConfigError


def test_valid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading valid DISCORD_TOKEN and numeric DEV_GUILD_ID."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_secret_token_123")
    monkeypatch.setenv("DEV_GUILD_ID", "987654321098765432")

    settings = load_settings()
    assert settings.discord_token == "mock_secret_token_123"
    assert settings.dev_guild_id == 987654321098765432


def test_optional_dev_guild_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading settings when DEV_GUILD_ID is omitted or empty."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_secret_token_123")
    monkeypatch.delenv("DEV_GUILD_ID", raising=False)

    settings = load_settings()
    assert settings.discord_token == "mock_secret_token_123"
    assert settings.dev_guild_id is None


def test_missing_discord_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that ConfigError is raised when DISCORD_TOKEN is missing or empty."""
    monkeypatch.setenv("DISCORD_TOKEN", "")

    with pytest.raises(ConfigError, match="DISCORD_TOKEN is missing"):
        load_settings()


def test_invalid_dev_guild_id_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that ConfigError is raised when DEV_GUILD_ID is non-numeric."""
    monkeypatch.setenv("DISCORD_TOKEN", "mock_secret_token_123")
    monkeypatch.setenv("DEV_GUILD_ID", "invalid_not_a_number")

    with pytest.raises(ConfigError, match="Invalid DEV_GUILD_ID"):
        load_settings()
