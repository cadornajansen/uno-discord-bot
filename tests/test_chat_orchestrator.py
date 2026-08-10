import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.services.ai import AIResponse, AIUsage
from bot.services.chat_orchestrator import (
    ChatResponse,
    ChatOrchestrator,
    choose_initial_tool,
    tool_arguments_for,
)
from bot.services.conversation_memory import ConversationMemory


def _response(content=None, tool_calls=()):
    return AIResponse(content=content, tool_calls=tuple(tool_calls), request_id="req", usage=AIUsage())


def test_clear_assignment_intent_forces_assignment_tool() -> None:
    assert choose_initial_tool("what's the latest assignment?") == "get_latest_assignments"
    assert choose_initial_tool("yo") is None
    assert tool_arguments_for("get_class_schedule", "classes Friday?") == {
        "when": "classes Friday?"
    }


def test_orchestrator_executes_tool_then_saves_only_final_turn() -> None:
    async def run() -> None:
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_response(content="Here are the latest assignments."))
        tools = MagicMock()
        tools.execute = AsyncMock(return_value={"ok": True, "items": []})
        memory = ConversationMemory()
        orchestrator = ChatOrchestrator(ai, tools, memory)

        result = await orchestrator.chat(
            "latest assignment?", guild_id=1, channel_id=2, user_id=3,
            user_display_name="Student", channel_name="bot-channel",
        )

        assert result == ChatResponse(content="Here are the latest assignments.")
        tools.execute.assert_awaited_once_with(
            "get_latest_assignments",
            {"query": "latest assignment?"},
            1,
        )
        ai.complete.assert_awaited_once()
        request = ai.complete.await_args.kwargs
        assert "tools" not in request
        assert "tool_choice" not in request
        assert "Read-only class lookup result" in request["messages"][-1]["content"]
        saved = memory.get_messages(1, 2, 3)
        assert saved == [
            {"role": "user", "content": "latest assignment?"},
            {"role": "assistant", "content": "Here are the latest assignments."},
        ]

    asyncio.run(run())


def test_latest_structured_assignments_skip_ai_and_return_render_data() -> None:
    async def run() -> None:
        structured = (
            "**Latest Homework & Requirements**\n\n"
            "**ITC — Introduction to Computing**\n"
            "*Professor · Lecture · Room 1*\n"
            "- Finish Activity 1 — No due date stated"
        )
        ai = MagicMock()
        ai.complete = AsyncMock()
        tools = MagicMock()
        tools.execute = AsyncMock(
            return_value={
                "ok": True,
                "items": [{"content": structured, "channel_kind": "homework"}],
                "current_datetime": "2026-08-10T20:00+08:00",
            }
        )
        memory = ConversationMemory()
        orchestrator = ChatOrchestrator(ai, tools, memory)

        result = await orchestrator.chat(
            "what are the latest assignments?",
            guild_id=1,
            channel_id=2,
            user_id=3,
            user_display_name="Student",
            channel_name="bot-channel",
        )

        assert result.content == structured
        assert result.assignment_items[0]["content"] == structured
        assert result.current_datetime == "2026-08-10T20:00+08:00"
        ai.complete.assert_not_awaited()
        assert memory.get_messages(1, 2, 3)[-1]["content"] == structured

    asyncio.run(run())


def test_plain_chat_does_not_run_a_class_tool() -> None:
    async def run() -> None:
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_response(content="Not much."))
        tools = MagicMock()
        tools.execute = AsyncMock()
        orchestrator = ChatOrchestrator(ai, tools, ConversationMemory())

        await orchestrator.chat(
            "what's up?", guild_id=1, channel_id=2, user_id=3,
            user_display_name="Student", channel_name="bot-channel",
        )

        tools.execute.assert_not_awaited()
        assert "Read-only class lookup result" not in ai.complete.await_args.kwargs["messages"][-1]["content"]

    asyncio.run(run())
