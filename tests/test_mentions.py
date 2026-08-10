import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.cogs.mentions import (
    MentionsCog,
    choose_context_mode,
    style_feedback_acknowledgement,
)
from bot.services.chat_orchestrator import ChatResponse


class _TypingContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _make_cog() -> MentionsCog:
    cog = MentionsCog.__new__(MentionsCog)
    cog.chat_orchestrator = MagicMock()
    cog.chat_orchestrator.chat = AsyncMock(
        return_value=ChatResponse(content="Got it. Keeping it chill.")
    )
    cog._fetch_recent_channel_history = AsyncMock(return_value="[User]: Earlier message")
    return cog


def _make_message() -> MagicMock:
    message = MagicMock()
    message.guild.id = 777
    message.author.display_name = "Jasnen"
    message.author.id = 123
    message.channel.id = 456
    message.channel.name = "bot-channel"
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
        cog.chat_orchestrator.chat.assert_not_awaited()
        message.reply.assert_awaited_once_with("Got it. Keeping it chill.")

    asyncio.run(_test())


def test_direct_conversation_uses_only_reply_target_and_current_message():
    async def _test():
        cog = _make_cog()
        message = _make_message()
        reference = _make_reference("I can help with that.")

        await cog._respond_with_adaptive_context(message, "thanks", reference)

        cog._fetch_recent_channel_history.assert_not_awaited()
        kwargs = cog.chat_orchestrator.chat.await_args.kwargs
        assert kwargs["reply_context"] == "I can help with that."
        assert kwargs["nearby_context"] is None
        assert cog.chat_orchestrator.chat.await_args.args == ("thanks",)

    asyncio.run(_test())


def test_class_followup_delegates_retrieval_without_channel_history_dump():
    async def _test():
        cog = _make_cog()
        message = _make_message()
        reference = _make_reference("The assignment is due Friday.")

        await cog._respond_with_adaptive_context(
            message,
            "are you sure the assignment is due Friday?",
            reference,
        )

        cog._fetch_recent_channel_history.assert_not_awaited()
        kwargs = cog.chat_orchestrator.chat.await_args.kwargs
        assert kwargs["reply_context"] == "The assignment is due Friday."
        assert kwargs["nearby_context"] is None

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
        assert cog.chat_orchestrator.chat.await_args.kwargs["nearby_context"] == "[User]: Earlier message"

    asyncio.run(_test())


def test_latest_assignments_mention_replies_with_embed() -> None:
    async def _test() -> None:
        cog = _make_cog()
        message = _make_message()
        content = (
            "**Latest Homework & Requirements**\n\n"
            "**ITC — Introduction to Computing**\n"
            "- Finish Activity 1"
        )
        cog.chat_orchestrator.chat.return_value = ChatResponse(
            content=content,
            assignment_items=({"content": content},),
        )

        await cog._respond_with_adaptive_context(message, "latest assignments", None)

        call = message.reply.await_args
        assert call.kwargs["embed"].title == "Latest Assignments"

    asyncio.run(_test())


def test_mention_reply_does_not_add_a_reaction() -> None:
    async def _test() -> None:
        cog = _make_cog()
        bot_user = MagicMock()
        bot_user.id = 999
        bot_user.name = "Uno AI"
        cog.bot = MagicMock(user=bot_user)
        cog._get_referenced_message = AsyncMock(return_value=None)
        cog._respond_with_adaptive_context = AsyncMock()
        message = _make_message()
        message.author.bot = False
        message.mentions = [bot_user]
        message.clean_content = "@Uno AI hello"
        message.add_reaction = AsyncMock()

        await cog.on_message(message)

        message.add_reaction.assert_not_awaited()
        cog._respond_with_adaptive_context.assert_awaited_once()

    asyncio.run(_test())
