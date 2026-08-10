import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.cogs.mentions import (
    CONVERSATION_SYSTEM_PROMPT,
    MentionsCog,
    choose_context_mode,
    style_feedback_acknowledgement,
)


class _TypingContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _make_cog() -> MentionsCog:
    cog = MentionsCog.__new__(MentionsCog)
    cog.ai_service = MagicMock()
    cog.ai_service.ask = AsyncMock(return_value="Got it. Keeping it chill.")
    cog.embedding_service = MagicMock()
    cog.embedding_service.embed = AsyncMock(return_value=[0.1])
    cog.vector_store = MagicMock()
    cog.vector_store.search_similar = AsyncMock(return_value=[])
    cog.rag_service = MagicMock(min_score=0.5, max_context_results=3)
    cog._fetch_recent_channel_history = AsyncMock(return_value="[User]: Earlier message")
    return cog


def _make_message() -> MagicMock:
    message = MagicMock()
    message.guild.id = 777
    message.author.display_name = "Jasnen"
    message.channel.typing.return_value = _TypingContext()
    message.reply = AsyncMock()
    return message


def _make_reference(content: str) -> MagicMock:
    reference = MagicMock()
    reference.clean_content = content
    return reference


def test_context_mode_uses_direct_path_for_style_feedback():
    assert choose_context_mode("act more nonchalant") == "direct"
    assert choose_context_mode("reply shorter next time") == "direct"


def test_style_feedback_has_short_deterministic_acknowledgements():
    assert style_feedback_acknowledgement("act more nonchalant") == (
        "Got it. Keeping it chill."
    )
    assert style_feedback_acknowledgement("use fewer emojis") == "Got it. Fewer emojis."
    assert style_feedback_acknowledgement("thanks") is None


def test_context_mode_limits_rag_to_class_information():
    assert choose_context_mode("when is the homework due?") == "rag"
    assert choose_context_mode("what do you mean by that?") == "nearby"


def test_style_feedback_skips_history_vector_search_and_ai():
    async def _test():
        cog = _make_cog()
        message = _make_message()
        reference = _make_reference("A long overly enthusiastic response")

        await cog._respond_with_adaptive_context(
            message,
            "act more nonchalant",
            reference,
        )

        cog._fetch_recent_channel_history.assert_not_awaited()
        cog.embedding_service.embed.assert_not_awaited()
        cog.vector_store.search_similar.assert_not_awaited()
        cog.ai_service.ask.assert_not_awaited()
        message.reply.assert_awaited_once_with("Got it. Keeping it chill.")

    asyncio.run(_test())


def test_direct_conversation_uses_only_reply_target_and_current_message():
    async def _test():
        cog = _make_cog()
        message = _make_message()
        reference = _make_reference("I can help with that.")

        await cog._respond_with_adaptive_context(message, "thanks", reference)

        cog._fetch_recent_channel_history.assert_not_awaited()
        cog.embedding_service.embed.assert_not_awaited()
        prompt = cog.ai_service.ask.await_args.kwargs["question"]
        assert "Replying to:" in prompt
        assert "thanks" in prompt
        assert cog.ai_service.ask.await_args.kwargs["system_prompt"] == CONVERSATION_SYSTEM_PROMPT
        assert cog.ai_service.ask.await_args.kwargs["max_tokens"] == 120

    asyncio.run(_test())


def test_class_followup_uses_three_messages_and_rag():
    async def _test():
        cog = _make_cog()
        message = _make_message()
        reference = _make_reference("The assignment is due Friday.")

        await cog._respond_with_adaptive_context(
            message,
            "are you sure the assignment is due Friday?",
            reference,
        )

        cog._fetch_recent_channel_history.assert_awaited_once_with(
            message,
            limit=3,
            before=reference,
        )
        cog.embedding_service.embed.assert_awaited_once()
        cog.vector_store.search_similar.assert_awaited_once()
        assert cog.ai_service.ask.await_args.kwargs["max_tokens"] == 220

    asyncio.run(_test())


def test_referential_followup_uses_nearby_messages_without_rag():
    """Ambiguous follow-ups get a small conversation window but no vector search."""
    async def _test():
        cog = _make_cog()
        message = _make_message()
        reference = _make_reference("That approach is safer.")

        await cog._respond_with_adaptive_context(
            message,
            "what do you mean by that?",
            reference,
        )

        cog._fetch_recent_channel_history.assert_awaited_once_with(
            message,
            limit=3,
            before=reference,
        )
        cog.embedding_service.embed.assert_not_awaited()
        cog.vector_store.search_similar.assert_not_awaited()
        assert cog.ai_service.ask.await_args.kwargs["max_tokens"] == 120

    asyncio.run(_test())
