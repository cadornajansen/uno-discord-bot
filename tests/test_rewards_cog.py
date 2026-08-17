import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.rewards import RewardsCog, LeaderboardView, build_leaderboard_embed
from bot.services.rewards_db import RewardsDBService


def _make_rewards_cog() -> tuple[RewardsCog, RewardsDBService, MagicMock]:
    bot = MagicMock()
    bot.settings.rewards_log_channel_id = 1538813495397589062
    rewards_service = RewardsDBService(db_path=":memory:")
    bot.rewards_service = rewards_service

    log_channel = MagicMock()
    log_channel.send = AsyncMock()
    bot.get_channel.return_value = log_channel

    cog = RewardsCog(bot)
    cog.rewards_service = rewards_service
    return cog, rewards_service, log_channel


def test_daily_command_success():
    """Test /daily slash command claims points, sends embed, and logs activity."""
    async def _test():
        cog, service, log_channel = _make_rewards_cog()

        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Charlie"
        interaction.response.send_message = AsyncMock()

        await cog.daily.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "Daily Attendance Claimed!" in embed.title
        assert service.get_balance(555) == 30

        # Verify activity log sent
        log_channel.send.assert_awaited_once()
        log_embed = log_channel.send.call_args.kwargs["embed"]
        assert "Daily Claim" in log_embed.title

    asyncio.run(_test())


def test_daily_command_already_claimed():
    """Test /daily slash command handles already claimed error with cooldown embed."""
    async def _test():
        cog, service, _ = _make_rewards_cog()

        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Charlie"
        interaction.response.send_message = AsyncMock()

        # Claim once
        service.claim_daily(555)

        # Claim second time
        await cog.daily.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "Already Claimed" in embed.title

    asyncio.run(_test())


def test_balance_command():
    """Test /balance slash command displays user balance and rank."""
    async def _test():
        cog, service, _ = _make_rewards_cog()
        service.add_points(555, 250, "TEST")

        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Charlie"
        interaction.user.display_avatar.url = "https://cdn.discordapp.com/avatar.png"
        interaction.response.send_message = AsyncMock()

        await cog.balance.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "250 pts" in embed.fields[0].value

    asyncio.run(_test())


def test_profile_command_with_badges_and_inventory():
    """Test /profile slash command displays badges and inventory items."""
    async def _test():
        cog, service, _ = _make_rewards_cog()
        service.add_points(555, 3200, "TEST")
        service.add_item(555, "pickpocket", 2)

        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Charlie"
        interaction.user.display_avatar.url = "https://cdn.discordapp.com/avatar.png"
        interaction.response.send_message = AsyncMock()

        await cog.profile.callback(cog, interaction, member=None)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "Student Profile" in embed.title
        # Check badge field
        badges_field = [f for f in embed.fields if f.name == "🏅 Badges & Milestones"][0]
        assert "🍫 Exam Survivor" in badges_field.value
        # Check inventory field
        inv_field = [f for f in embed.fields if f.name == "🎒 Inventory"][0]
        assert "pickpocket" in inv_field.value

    asyncio.run(_test())


def test_leaderboard_pagination_view():
    """Test LeaderboardView pagination buttons navigate pages correctly."""
    async def _test():
        cog, service, _ = _make_rewards_cog()
        for i in range(25):
            service.add_points(1000 + i, (i + 1) * 100, "TEST")

        guild = MagicMock()
        embed, total_pages = await build_leaderboard_embed(service, guild, page=1, per_page=10)
        assert total_pages == 3

        view = LeaderboardView(service, guild, page=1, per_page=10, total_pages=total_pages)
        assert view.prev_button.disabled is True
        assert view.next_button.disabled is False

        # Simulate Next button click
        interaction = MagicMock()
        interaction.response.edit_message = AsyncMock()
        await view.next_button.callback(interaction)

        assert view.page == 2
        assert view.prev_button.disabled is False
        interaction.response.edit_message.assert_awaited_once()

    asyncio.run(_test())
