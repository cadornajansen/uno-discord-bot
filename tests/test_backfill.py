import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from scripts.backfill_discord_history import run_backfill


def test_backfill_unapproved_channel_rejected(monkeypatch: pytest.MonkeyPatch):
    """Test that specifying an unapproved channel ID causes backfill to exit with code 1."""
    async def _test():
        monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
        monkeypatch.setenv("INDEXED_CHANNEL_IDS", "123456789")

        code = await run_backfill(channel_id_filter=999999999, limit=10)
        assert code == 1

    asyncio.run(_test())


def test_backfill_empty_allowlist_rejected(monkeypatch: pytest.MonkeyPatch):
    """Test that empty INDEXED_CHANNEL_IDS causes backfill to exit with code 1."""
    async def _test():
        monkeypatch.setenv("DISCORD_TOKEN", "mock_token")
        monkeypatch.setenv("INDEXED_CHANNEL_IDS", "")

        code = await run_backfill(channel_id_filter=None, limit=10)
        assert code == 1

    asyncio.run(_test())
