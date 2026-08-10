import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from bot.services.academic_schedule import AcademicScheduleService
from bot.services.class_tools import ClassTools
from bot.services.embeddings import EmbeddingError


HOMEWORK_CHANNEL = 1531615193786876063
ANNOUNCEMENT_CHANNEL = 1531615193786876064


def _tools() -> ClassTools:
    embedding = MagicMock()
    vector_store = MagicMock()
    schedule = AcademicScheduleService(Path("data/academics"), "2026-2027", 1, "Asia/Manila")
    return ClassTools(
        embedding,
        vector_store,
        schedule,
        frozenset({HOMEWORK_CHANNEL, ANNOUNCEMENT_CHANNEL}),
        frozenset({HOMEWORK_CHANNEL}),
    )


def test_schedule_tool_still_works_when_embeddings_fail() -> None:
    async def run() -> None:
        tools = _tools()
        tools.embedding_service.embed = AsyncMock(side_effect=EmbeddingError("offline"))

        search = await tools.execute("search_class_messages", {"query": "quiz"}, 1)
        schedule = await tools.execute("get_class_schedule", {"when": "Friday"}, 1)

        assert search["ok"] is False
        assert schedule["ok"] is True
        assert schedule["day"] == "Friday"

    asyncio.run(run())


def test_authoritative_structured_post_outranks_newer_casual_message() -> None:
    tools = _tools()
    now = datetime.now(ZoneInfo("Asia/Manila"))
    casual = {
        "score": 1.0,
        "payload": {
            "channel_id": str(ANNOUNCEMENT_CHANNEL),
            "created_at": now.isoformat(),
            "content": "any homework?",
        },
    }
    structured = {
        "score": 1.0,
        "payload": {
            "channel_id": str(HOMEWORK_CHANNEL),
            "created_at": (now - timedelta(days=2)).isoformat(),
            "content": "STS\n- Read chapter 2\n\nMMW\n- Answer pages 10-12",
        },
    }

    ranked = tools._rank([casual, structured], semantic=False)

    assert ranked[0] is structured


def test_relative_date_resolution_uses_manila_time() -> None:
    tools = _tools()
    today = datetime.now(ZoneInfo("Asia/Manila")).date()
    assert tools._resolve_date("tomorrow").date() == today + timedelta(days=1)
