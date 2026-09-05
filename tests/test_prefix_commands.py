import asyncio
from unittest.mock import AsyncMock, MagicMock

from discord import app_commands
from discord.ext import commands

from bot.cogs.prefix import PrefixCommandsCog, PrefixInteraction


class DummyAppCog(commands.Cog):
    """Small slash-command target for prefix adapter integration tests."""

    @app_commands.command(name="echo")
    async def echo(self, interaction, value: str) -> None:
        await interaction.response.send_message(value, ephemeral=True)


def make_context() -> MagicMock:
    """Create the Context subset used by the prefix compatibility layer."""
    context = MagicMock()
    context.author = MagicMock()
    context.guild = MagicMock()
    context.channel = MagicMock()
    context.send = AsyncMock(return_value=MagicMock())
    context.reply = AsyncMock(return_value=MagicMock())
    return context


def test_prefix_cog_registers_all_non_document_aliases():
    """Every normal slash feature has a global prefix command name."""
    command_names = {
        command.name for command in PrefixCommandsCog.__cog_commands__
    }

    assert {
        "ask",
        "search",
        "ping",
        "hello",
        "userinfo",
        "serverinfo",
        "help",
        "about",
        "today",
        "schedule",
        "nextclass",
        "prof",
        "weather",
        "countdown",
        "daily",
        "balance",
        "profile",
        "rank",
        "leaderboard",
        "bet",
        "steal",
        "inventory",
        "use",
        "shop",
        "redeem",
        "admin-inspect",
        "admin-points",
        "admin-export",
        "guide",
        "milestone",
        "trivia",
        "duel",
        "bounty",
        "give",
        "sue",
        "arrest",
        "martial_law",
    }.issubset(command_names)


def test_prefix_interaction_routes_response_and_followup_to_context():
    """Interaction-style responses become ordinary prefix replies."""
    async def _test():
        context = make_context()
        interaction = PrefixInteraction(context)

        await interaction.response.send_message("First", ephemeral=True)
        await interaction.followup.send("Second")
        await interaction.edit_original_response(content="Deferred")

        assert interaction.response.is_done() is True
        assert context.reply.await_args_list[0].kwargs == {"content": "First", "suppress_embeds": True}
        assert context.reply.await_args_list[1].kwargs == {"content": "Second", "suppress_embeds": True}
        assert context.reply.await_args_list[2].kwargs == {"content": "Deferred", "suppress_embeds": True}

    asyncio.run(_test())


def test_prefix_invocation_reuses_existing_app_command_callback():
    """The compatibility layer executes the original slash callback."""
    async def _test():
        bot = MagicMock()
        bot.get_cog.return_value = DummyAppCog()
        prefix_cog = PrefixCommandsCog(bot)
        context = make_context()

        await prefix_cog._invoke_app_command(
            context,
            "DummyAppCog",
            "echo",
            "Shared implementation",
        )

        context.reply.assert_awaited_once_with(content="Shared implementation", suppress_embeds=True)

    asyncio.run(_test())


def test_ask_prefix_forwards_entire_question():
    """Keyword-only prefix text is forwarded as one question string."""
    async def _test():
        prefix_cog = PrefixCommandsCog(MagicMock())
        prefix_cog._invoke_app_command = AsyncMock()
        context = make_context()

        await PrefixCommandsCog.ask_prefix.callback(
            prefix_cog,
            context,
            question="What are the latest homeworks?",
        )

        prefix_cog._invoke_app_command.assert_awaited_once_with(
            context,
            "AICog",
            "ask",
            "What are the latest homeworks?",
        )

    asyncio.run(_test())


def test_document_prefix_commands_redirect_to_slash_commands():
    """Document commands do not execute through the prefix interface."""
    async def _test():
        prefix_cog = PrefixCommandsCog(MagicMock())
        analyze_context = make_context()
        docask_context = make_context()

        await PrefixCommandsCog.analyze_slash_only.callback(
            prefix_cog,
            analyze_context,
            ignored="notes.pdf",
        )
        await PrefixCommandsCog.docask_slash_only.callback(
            prefix_cog,
            docask_context,
            ignored="What is chapter one?",
        )

        assert "/analyze" in analyze_context.reply.await_args.args[0]
        assert "/docask" in docask_context.reply.await_args.args[0]

    asyncio.run(_test())


def test_rewards_prefix_commands_forward_correctly():
    """Verify prefix commands forward correctly to RewardsCog."""
    async def _test():
        prefix_cog = PrefixCommandsCog(MagicMock())
        prefix_cog._invoke_app_command = AsyncMock()
        context = make_context()

        # 1. !daily
        await PrefixCommandsCog.daily_prefix.callback(prefix_cog, context)
        prefix_cog._invoke_app_command.assert_awaited_with(context, "RewardsCog", "daily")

        # 2. !balance
        await PrefixCommandsCog.balance_prefix.callback(prefix_cog, context)
        prefix_cog._invoke_app_command.assert_awaited_with(context, "RewardsCog", "balance")

        # 3. !bet
        await PrefixCommandsCog.bet_prefix.callback(prefix_cog, context)
        prefix_cog._invoke_app_command.assert_awaited_with(context, "RewardsCog", "bet", 50)

        # 4. !shop
        await PrefixCommandsCog.shop_prefix.callback(prefix_cog, context)
        prefix_cog._invoke_app_command.assert_awaited_with(context, "RewardsCog", "shop")

        # 5. !countdown
        await PrefixCommandsCog.countdown_prefix.callback(prefix_cog, context)
        prefix_cog._invoke_app_command.assert_awaited_with(context, "AcademicsCog", "countdown")

        # 6. !use shield_1w
        await PrefixCommandsCog.use_prefix.callback(prefix_cog, context, item="shield_1w")
        assert prefix_cog._invoke_app_command.await_args[0][1] == "RewardsCog"
        assert prefix_cog._invoke_app_command.await_args[0][2] == "use"
        assert prefix_cog._invoke_app_command.await_args[0][3].value == "shield_1w"

        # 7. !redeem coffee
        await PrefixCommandsCog.redeem_prefix.callback(prefix_cog, context, item="coffee")
        assert prefix_cog._invoke_app_command.await_args[0][1] == "RewardsCog"
        assert prefix_cog._invoke_app_command.await_args[0][2] == "redeem"
        assert prefix_cog._invoke_app_command.await_args[0][3].value == "coffee"

        # 8. !admin-points add @user 500 Quiz
        member = MagicMock()
        await PrefixCommandsCog.admin_points_prefix.callback(prefix_cog, context, action="add", member=member, amount=500, reason="Quiz")
        assert prefix_cog._invoke_app_command.await_args[0][1] == "RewardsCog"
        assert prefix_cog._invoke_app_command.await_args[0][2] == "admin_points"
        assert prefix_cog._invoke_app_command.await_args[0][3].value == "add"

        # 9. !trivia
        await PrefixCommandsCog.trivia_prefix.callback(prefix_cog, context)
        prefix_cog._invoke_app_command.assert_awaited_with(context, "RewardsCog", "trivia")

        # 10. !give @user 50
        recipient = MagicMock()
        await PrefixCommandsCog.give_prefix.callback(prefix_cog, context, member=recipient, amount=50)
        prefix_cog._invoke_app_command.assert_awaited_with(context, "RewardsCog", "give", recipient, 50)

    asyncio.run(_test())
