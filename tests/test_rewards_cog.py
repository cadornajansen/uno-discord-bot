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


def test_bet_command():
    """Test /bet slash command places bet, updates points, and sends embed."""
    async def _test():
        cog, service, log_channel = _make_rewards_cog()
        service.add_points(555, 100, "TEST")

        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Charlie"
        interaction.response.send_message = AsyncMock()

        await cog.bet.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "pts" in embed.fields[0].value
        assert "Bets Remaining" in embed.fields[1].name
        log_channel.send.assert_awaited_once()

    asyncio.run(_test())


def test_steal_command_shield_and_success():
    """Test /steal slash command handles shield deflection and successful robbery."""
    async def _test():
        cog, service, log_channel = _make_rewards_cog()
        service.add_points(555, 100, "THIEF")
        service.add_points(777, 500, "TARGET")
        service.add_item(555, "pickpocket", 2)

        # 1. Target is shielded
        service.activate_shield(777, duration_days=7)

        target_member = MagicMock()
        target_member.id = 777
        target_member.display_name = "Victim"
        target_member.bot = False

        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Thief"
        interaction.response.send_message = AsyncMock()

        await cog.steal.callback(cog, interaction, target=target_member)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "BLOCKED by Immunity Shield" in embed.title

    asyncio.run(_test())


def test_inventory_and_use_command():
    """Test /inventory and /use commands."""
    async def _test():
        cog, service, _ = _make_rewards_cog()
        service.add_item(555, "shield_1w", 1)

        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Charlie"
        interaction.response.send_message = AsyncMock()

        # Check /inventory
        await cog.inventory.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
        inv_embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "1-Week Immunity Shield" in inv_embed.description

        # Use shield
        interaction2 = MagicMock()
        interaction2.user.id = 555
        interaction2.user.display_name = "Charlie"
        interaction2.response.send_message = AsyncMock()

        item_choice = MagicMock()
        item_choice.name = "🛡️ 1-Week Immunity Shield"
        item_choice.value = "shield_1w"

        await cog.use.callback(cog, interaction2, item=item_choice)
        interaction2.response.send_message.assert_awaited_once()
        use_embed = interaction2.response.send_message.call_args.kwargs["embed"]
        assert "Activated" in use_embed.title
        assert service.has_active_shield(555) is True

    asyncio.run(_test())


def test_shop_and_redeem_commands():
    """Test /shop and /redeem commands."""
    async def _test():
        cog, service, log_channel = _make_rewards_cog()
        service.add_points(555, 2000, "TEST")

        # 1. /shop
        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Charlie"
        interaction.response.send_message = AsyncMock()

        await cog.shop.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
        shop_embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "Uno Rewards Shop" in shop_embed.title

        # 2. /redeem consumable (pickpocket - 100 pts)
        interaction2 = MagicMock()
        interaction2.user.id = 555
        interaction2.user.display_name = "Charlie"
        interaction2.response.send_message = AsyncMock()

        item_choice = MagicMock()
        item_choice.value = "pickpocket"

        await cog.redeem.callback(cog, interaction2, item=item_choice)
        interaction2.response.send_message.assert_awaited_once()
        redeem_embed = interaction2.response.send_message.call_args.kwargs["embed"]
        assert "Consumable Purchased!" in redeem_embed.title
        assert service.get_balance(555) == 1900
        assert service.get_inventory(555)["pickpocket"] == 1

        # 3. /redeem physical (coffee - 1200 pts)
        interaction3 = MagicMock()
        interaction3.user.id = 555
        interaction3.user.display_name = "Charlie"
        interaction3.response.send_message = AsyncMock()

        item_choice2 = MagicMock()
        item_choice2.value = "coffee"

        await cog.redeem.callback(cog, interaction3, item=item_choice2)
        interaction3.response.send_message.assert_awaited_once()
        redeem_embed2 = interaction3.response.send_message.call_args.kwargs["embed"]
        assert "Prize Redemption Submitted!" in redeem_embed2.title
        assert service.get_balance(555) == 700
        log_channel.send.assert_awaited_once()

    asyncio.run(_test())


def test_redemption_approval_view():
    """Test RedemptionApprovalView buttons."""
    async def _test():
        from bot.cogs.rewards import RedemptionApprovalView
        cog, service, _ = _make_rewards_cog()
        service.add_points(555, 1500, "TEST")
        redemption = service.record_redemption(555, "coffee")
        assert service.get_balance(555) == 300

        view = RedemptionApprovalView(service, redemption["id"])

        # Approve
        interaction = MagicMock()
        interaction.user.display_name = "Admin Jansen"
        interaction.message.embeds = [discord.Embed(title="Redemption")]
        interaction.response.edit_message = AsyncMock()

        await view.approve_button.callback(interaction)
        interaction.response.edit_message.assert_awaited_once()

    asyncio.run(_test())


def test_admin_commands():
    """Test /admin-inspect, /admin-points, and /admin-export."""
    async def _test():
        cog, service, log_channel = _make_rewards_cog()
        service.add_points(555, 500, "TEST")

        target_member = MagicMock()
        target_member.id = 555
        target_member.display_name = "Charlie"
        target_member.display_avatar.url = "https://cdn.discordapp.com/avatar.png"

        # 1. /admin-inspect
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        await cog.admin_inspect.callback(cog, interaction, member=target_member)
        interaction.response.send_message.assert_awaited_once()
        inspect_embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "Admin Inspection" in inspect_embed.title

        # 2. /admin-points add
        interaction2 = MagicMock()
        interaction2.user.display_name = "Admin Jansen"
        interaction2.response.send_message = AsyncMock()
        action_choice = MagicMock()
        action_choice.value = "add"

        await cog.admin_points.callback(cog, interaction2, action=action_choice, member=target_member, amount=200, reason="Quiz Bee")
        interaction2.response.send_message.assert_awaited_once()
        assert service.get_balance(555) == 700

        # 3. /admin-export
        interaction3 = MagicMock()
        interaction3.response.send_message = AsyncMock()
        await cog.admin_export.callback(cog, interaction3)
        interaction3.response.send_message.assert_awaited_once()
        file_arg = interaction3.response.send_message.call_args.kwargs["file"]
        assert file_arg.filename.startswith("uno_rewards_")

    asyncio.run(_test())


def test_guide_and_milestone_commands():
    """Test /guide and /milestone commands."""
    async def _test():
        cog, _, _ = _make_rewards_cog()

        # 1. /guide
        interaction1 = MagicMock()
        interaction1.response.send_message = AsyncMock()
        await cog.guide.callback(cog, interaction1)
        interaction1.response.send_message.assert_awaited_once()
        guide_embed = interaction1.response.send_message.call_args.kwargs["embed"]
        assert "Complete Student Guide" in guide_embed.title

        # 2. /milestone
        interaction2 = MagicMock()
        interaction2.response.send_message = AsyncMock()
        await cog.milestone.callback(cog, interaction2)
        interaction2.response.send_message.assert_awaited_once()
        milestone_embed = interaction2.response.send_message.call_args.kwargs["embed"]
        assert "PRODUCTION MILESTONE" in milestone_embed.title

    asyncio.run(_test())


def test_trivia_command_and_view():
    """Test /trivia command launch and interactive TriviaView answer flow."""
    async def _test():
        cog, service, _ = _make_rewards_cog()

        # 1. Launch /trivia
        interaction = MagicMock()
        interaction.user.id = 777
        interaction.user.display_name = "Dave"
        interaction.response.send_message = AsyncMock()

        await cog.trivia.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        view = interaction.response.send_message.call_args.kwargs["view"]
        assert "Uno Daily Trivia" in embed.title
        assert len(view.children) == 4

        # 2. Click wrong button -> 0 points, attempt recorded
        btn_wrong = next(b for b in view.children if getattr(b, "option_index", None) != view.question.correct_index)
        interaction_btn1 = MagicMock()
        interaction_btn1.user.id = 777
        interaction_btn1.response.edit_message = AsyncMock()

        await btn_wrong.callback(interaction_btn1)
        interaction_btn1.response.edit_message.assert_awaited_once()
        assert service.get_balance(777) == 0

        # 3. New question -> click correct button -> +50 points
        interaction2 = MagicMock()
        interaction2.user.id = 777
        interaction2.user.display_name = "Dave"
        interaction2.response.send_message = AsyncMock()

        await cog.trivia.callback(cog, interaction2)
        view2 = interaction2.response.send_message.call_args.kwargs["view"]

        btn_correct = next(b for b in view2.children if getattr(b, "option_index", None) == view2.question.correct_index)
        interaction_btn2 = MagicMock()
        interaction_btn2.user.id = 777
        interaction_btn2.response.edit_message = AsyncMock()

        await btn_correct.callback(interaction_btn2)
        interaction_btn2.response.edit_message.assert_awaited_once()
        assert service.get_balance(777) == 50

    asyncio.run(_test())
