import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.forum import ForumCog
from bot.services.chat_orchestrator import ChatResponse
from bot.services.ai import AISafetyBlockError, AITimeoutError


class _TypingContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _make_forum_cog() -> ForumCog:
    bot = MagicMock()
    bot.settings.forum_channel_ids = frozenset({1538209328018886676})
    bot.chat_orchestrator = MagicMock()
    bot.chat_orchestrator.chat = AsyncMock(
        return_value=ChatResponse(content="Here is some quick advice on that topic.")
    )
    cog = ForumCog(bot)
    return cog


def _make_thread(
    *,
    parent_id: int = 1538209328018886676,
    thread_name: str = "How do we implement Dijkstra?",
    is_bot: bool = False,
    tag_names: list[str] = None,
) -> MagicMock:
    thread = MagicMock()
    thread.id = 999111222
    thread.name = thread_name
    thread.parent_id = parent_id
    thread.guild.id = 777
    thread.parent.name = "open-forum"
    thread.typing.return_value = _TypingContext()
    thread.send = AsyncMock()

    # Applied tags
    applied_tags = []
    for tag_name in (tag_names or ["Help"]):
        tag = MagicMock()
        tag.name = tag_name
        applied_tags.append(tag)
    thread.applied_tags = applied_tags

    # Starter message
    starter_msg = MagicMock()
    starter_msg.id = thread.id
    starter_msg.author.bot = is_bot
    starter_msg.author.id = 10101
    starter_msg.author.display_name = "Alex"
    starter_msg.clean_content = "Need some guidance for our data structures project."
    thread.fetch_message = AsyncMock(return_value=starter_msg)

    return thread


def test_forum_cog_responds_to_new_thread_in_allowlisted_channel():
    """ForumCog triggers chat_orchestrator and posts initial comment in new forum thread."""
    async def _test():
        cog = _make_forum_cog()
        thread = _make_thread(parent_id=1538209328018886676, tag_names=["Help", "DataStructures"])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await cog.on_thread_create(thread)

        cog.chat_orchestrator.chat.assert_awaited_once()
        call_prompt = cog.chat_orchestrator.chat.await_args.args[0]
        assert "Forum Post Title: How do we implement Dijkstra?" in call_prompt
        assert "Tags: Help, DataStructures" in call_prompt
        assert "Alex" in call_prompt
        thread.send.assert_awaited_once_with("Here is some quick advice on that topic.")

    asyncio.run(_test())


def test_forum_cog_ignores_threads_outside_allowlisted_forum():
    """ForumCog ignores threads created in non-forum channels."""
    async def _test():
        cog = _make_forum_cog()
        thread = _make_thread(parent_id=999999999999)  # Not in allowlist

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await cog.on_thread_create(thread)

        cog.chat_orchestrator.chat.assert_not_awaited()
        thread.send.assert_not_awaited()

    asyncio.run(_test())


def test_forum_cog_ignores_bot_created_threads():
    """ForumCog ignores threads started by a bot to prevent feedback loops."""
    async def _test():
        cog = _make_forum_cog()
        thread = _make_thread(is_bot=True)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await cog.on_thread_create(thread)

        cog.chat_orchestrator.chat.assert_not_awaited()
        thread.send.assert_not_awaited()

    asyncio.run(_test())


def test_forum_cog_handles_safety_block_gracefully():
    """ForumCog catches AISafetyBlockError and logs without crashing."""
    async def _test():
        cog = _make_forum_cog()
        cog.chat_orchestrator.chat = AsyncMock(side_effect=AISafetyBlockError("Blocked"))
        thread = _make_thread()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await cog.on_thread_create(thread)

        thread.send.assert_not_awaited()

    asyncio.run(_test())
