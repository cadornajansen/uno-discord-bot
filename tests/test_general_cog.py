import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.cogs.general import GeneralCog


def _interaction() -> MagicMock:
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def test_help_describes_mentions_memory_and_document_boundary() -> None:
    async def run() -> None:
        cog = GeneralCog(MagicMock())
        interaction = _interaction()

        await GeneralCog.help_command.callback(cog, interaction)

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        rendered = "\n".join(field.value for field in embed.fields)
        assert "@Uno AI what's due Friday?" in rendered
        assert "Private short-term memory" in rendered
        assert "Document questions are slash-only" not in rendered
        assert "Document commands remain slash-only" in embed.description

    asyncio.run(run())


def test_about_matches_shared_tool_and_privacy_architecture() -> None:
    async def run() -> None:
        cog = GeneralCog(MagicMock())
        interaction = _interaction()

        await GeneralCog.about_command.callback(cog, interaction)

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        rendered = "\n".join(field.value for field in embed.fields)
        assert "read-only class tools" in rendered
        assert "Asia/Manila" in rendered
        assert "four completed turns" in rendered
        assert "never message content or API keys" in rendered
        assert "Schedule, subject, and professor lookups continue" in rendered

    asyncio.run(run())
