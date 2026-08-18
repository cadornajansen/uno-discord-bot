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
        assert "Uno Points" in embed.fields[0].value
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

        # 1. /admin-inspect (as Admin)
        interaction = MagicMock()
        interaction.user.guild_permissions.administrator = True
        interaction.response.send_message = AsyncMock()
        await cog.admin_inspect.callback(cog, interaction, member=target_member)
        interaction.response.send_message.assert_awaited_once()
        inspect_embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "Admin Inspection" in inspect_embed.title

        # Non-admin rejection test
        non_admin = MagicMock()
        non_admin.user.guild_permissions.administrator = False
        non_admin.user.guild_permissions.manage_guild = False
        non_admin.guild.owner_id = 999999
        non_admin.user.id = 123456
        non_admin.response.send_message = AsyncMock()
        await cog.admin_inspect.callback(cog, non_admin, member=target_member)
        assert "Access Denied" in non_admin.response.send_message.call_args.args[0]

        # 2. /admin-points add (as Admin)
        interaction2 = MagicMock()
        interaction2.user.guild_permissions.administrator = True
        interaction2.user.display_name = "Admin Jansen"
        interaction2.response.send_message = AsyncMock()
        action_choice = MagicMock()
        action_choice.value = "add"

        await cog.admin_points.callback(cog, interaction2, action=action_choice, member=target_member, amount=200, reason="Quiz Bee")
        interaction2.response.send_message.assert_awaited_once()
        assert service.get_balance(555) == 700

        # 3. /admin-export (as Admin)
        interaction3 = MagicMock()
        interaction3.user.guild_permissions.administrator = True
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
        assert len(view.children) in (2, 4)

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


def test_airdrop_command_and_catch_view():
    """Test /use airdrop creates interactive view and users catch points."""
    async def _test():
        cog, service, _ = _make_rewards_cog()
        service.add_item(555, "airdrop", 1)

        # 1. /use airdrop
        interaction = MagicMock()
        interaction.user.id = 555
        interaction.user.display_name = "Launcher"
        interaction.response.send_message = AsyncMock()

        item_choice = MagicMock()
        item_choice.name = "🌧️ Point Airdrop"
        item_choice.value = "airdrop"

        await cog.use.callback(cog, interaction, item=item_choice)
        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        view = interaction.response.send_message.call_args.kwargs["view"]
        assert "POINT AIRDROP" in embed.title

        # 2. Catcher 1 clicks catch button (+25 pts)
        btn = view.children[0]
        interaction_c1 = MagicMock()
        interaction_c1.user.id = 888
        interaction_c1.user.display_name = "Catcher1"
        interaction_c1.response.edit_message = AsyncMock()
        interaction_c1.followup.send = AsyncMock()

        await btn.callback(interaction_c1)
        interaction_c1.response.edit_message.assert_awaited_once()
        assert service.get_balance(888) == 25

    asyncio.run(_test())


def test_steal_reversed_by_uno():
    """Test that /steal against a defender with Uno Reverse returns the REVERSED embed."""
    async def _test():
        cog, service, _ = _make_rewards_cog()
        service.add_points(111, 200, "THIEF")
        service.add_points(222, 300, "DEFENDER")
        service.add_item(111, "pickpocket", 1)
        service.add_item(222, "uno_reverse", 1)

        interaction = MagicMock()
        interaction.user.id = 111
        interaction.user.display_name = "Thief"
        interaction.response.send_message = AsyncMock()

        target_member = MagicMock()
        target_member.id = 222
        target_member.display_name = "Defender"
        target_member.bot = False

        await cog.steal.callback(cog, interaction, target=target_member)
        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "UNO REVERSED" in embed.title

    asyncio.run(_test())


def test_interactive_shop_view():
    """Test ShopView category button switching and Quick-Buy select menu purchase."""
    async def _test():
        from bot.cogs.rewards import ShopView, ShopCategoryButton, ShopQuickBuySelect
        cog, service, _ = _make_rewards_cog()
        service.add_points(999, 1000, "TEST")

        view = ShopView(service, 999, cog=cog)
        assert view.current_category == "home"

        # 1. Switch to 'offense' category button
        offense_btn = next(b for b in view.children if isinstance(b, ShopCategoryButton) and b.category_key == "offense")
        interaction_cat = MagicMock()
        interaction_cat.user.id = 999
        interaction_cat.response.edit_message = AsyncMock()

        await offense_btn.callback(interaction_cat)
        interaction_cat.response.edit_message.assert_awaited_once()
        assert view.current_category == "offense"

        # 2. Use Quick-Buy to buy 'pickpocket' card (100 pts)
        quick_buy = next(s for s in view.children if isinstance(s, ShopQuickBuySelect))
        quick_buy._values = ["pickpocket"]

        interaction_buy = MagicMock()
        interaction_buy.user.id = 999
        interaction_buy.response.send_message = AsyncMock()
        interaction_buy.message.edit = AsyncMock()

        await quick_buy.callback(interaction_buy)
        interaction_buy.response.send_message.assert_awaited_once()
        assert service.get_balance(999) == 900
        assert service.get_inventory(999)["pickpocket"] == 1

    asyncio.run(_test())


def test_pet_slash_commands_and_profile():
    """Test /pet adopt, /pet view, /pet switch, /pet rename, and pet in /profile."""
    async def _test():
        from bot.cogs.rewards import PetView, PetCareButton
        cog, service, _ = _make_rewards_cog()
        service.add_points(777, 2000, "TEST")

        # 1. /pet adopt
        interaction_adopt = MagicMock()
        interaction_adopt.user.id = 777
        interaction_adopt.user.display_name = "PetLover"
        interaction_adopt.response.send_message = AsyncMock()

        pet_choice = MagicMock()
        pet_choice.name = "🐱 Tuxedo Cat (500 pts)"
        pet_choice.value = "tuxedo_cat"

        await cog.pet_adopt.callback(cog, interaction_adopt, pet=pet_choice, nickname="Mittens")
        interaction_adopt.response.send_message.assert_awaited_once()
        adopt_embed = interaction_adopt.response.send_message.call_args.kwargs["embed"]
        assert "Adopted" in adopt_embed.title
        assert "Mittens" in adopt_embed.description

        # 2. /pet view
        interaction_view = MagicMock()
        interaction_view.user.id = 777
        interaction_view.user.display_name = "PetLover"
        interaction_view.response.send_message = AsyncMock()

        await cog.pet_view.callback(cog, interaction_view)
        interaction_view.response.send_message.assert_awaited_once()
        view_embed = interaction_view.response.send_message.call_args.kwargs["embed"]
        assert "Mittens" in view_embed.title

        # 3. Test Pet Care Buttons (Feed)
        all_pets = service.get_user_pets(777)
        pet_view = PetView(service, 777, all_pets)
        feed_btn = next(b for b in pet_view.children if isinstance(b, PetCareButton) and b.action == "feed")

        interaction_feed = MagicMock()
        interaction_feed.user.id = 777
        interaction_feed.user.display_name = "PetLover"
        interaction_feed.response.edit_message = AsyncMock()
        interaction_feed.followup.send = AsyncMock()

        await feed_btn.callback(interaction_feed)
        interaction_feed.response.edit_message.assert_awaited_once()
        interaction_feed.followup.send.assert_awaited_once()

        # 4. /profile with active companion
        interaction_prof = MagicMock()
        interaction_prof.user.id = 777
        interaction_prof.user.display_name = "PetLover"
        interaction_prof.response.send_message = AsyncMock()

        await cog.profile.callback(cog, interaction_prof)
        interaction_prof.response.send_message.assert_awaited_once()
        prof_embed = interaction_prof.response.send_message.call_args.kwargs["embed"]
        companion_field = next(f for f in prof_embed.fields if "Companion" in f.name)
        assert "Mittens" in companion_field.name

    asyncio.run(_test())


def test_pet_guide_and_drop_commands():
    """Test /pet guide and /pet drop commands."""
    async def _test():
        cog, service, _ = _make_rewards_cog()

        # 1. /pet guide
        interaction_guide = MagicMock()
        interaction_guide.user.id = 888
        interaction_guide.response.send_message = AsyncMock()

        await cog.pet_guide.callback(cog, interaction_guide)
        interaction_guide.response.send_message.assert_awaited_once()
        guide_embed = interaction_guide.response.send_message.call_args.kwargs["embed"]
        assert "Handbook & Guide" in guide_embed.title

        # 2. /pet drop
        interaction_drop = MagicMock()
        interaction_drop.user.id = 888
        interaction_drop.response.send_message = AsyncMock()

        await cog.pet_drop.callback(cog, interaction_drop)
        interaction_drop.response.send_message.assert_awaited_once()
        drop_embed = interaction_drop.response.send_message.call_args.kwargs["embed"]
        assert "NEW PET DROP" in drop_embed.title

    asyncio.run(_test())


def test_pet_sell_command_and_confirmation():
    """Test /pet sell command and confirmation button callback."""
    async def _test():
        from bot.cogs.rewards import PetSellConfirmView
        cog, service, _ = _make_rewards_cog()
        service.add_points(888, 1000, "START")
        service.adopt_pet(888, "tuxedo_cat")

        # 1. /pet sell triggers confirmation embed
        interaction_sell = MagicMock()
        interaction_sell.user.id = 888
        interaction_sell.user.display_name = "Seller"
        interaction_sell.response.send_message = AsyncMock()

        await cog.pet_sell.callback(cog, interaction_sell, pet="tuxedo_cat")
        interaction_sell.response.send_message.assert_awaited_once()
        sell_embed = interaction_sell.response.send_message.call_args.kwargs["embed"]
        assert "Confirm Selling" in sell_embed.title

        # 2. Click confirm button
        pet_rec = service.get_active_pet(888)
        confirm_view = PetSellConfirmView(service, 888, pet_rec)

        interaction_btn = MagicMock()
        interaction_btn.user.id = 888
        interaction_btn.response.edit_message = AsyncMock()

        await confirm_view.confirm.callback(interaction_btn)
        interaction_btn.response.edit_message.assert_awaited_once()
        final_embed = interaction_btn.response.edit_message.call_args.kwargs["embed"]
        assert "Refund Processed" in final_embed.title
        # Tuxedo cat (50 pts) refund is 30 pts. Starting points: 1000 - 50 + 30 = 980
        assert service.get_balance(888) == 980

    asyncio.run(_test())


def test_starter_pet_flow():
    """Test /pet view triggering starter modal for 0-pet users, and /pet starter choice."""
    async def _test():
        from discord import app_commands
        cog, service, _ = _make_rewards_cog()

        # 1. New user runs /pet view -> gets StarterPetSelectView
        i_view = MagicMock()
        i_view.user.id = 5555
        i_view.user.display_name = "Newbie"
        i_view.response.send_message = AsyncMock()

        await cog.pet_view.callback(cog, i_view)
        i_view.response.send_message.assert_awaited_once()
        view_arg = i_view.response.send_message.call_args.kwargs.get("view")
        assert view_arg is not None
        assert len(view_arg.children) == 3

        # 2. Click Tuxedo Cat button in StarterPetSelectView
        btn_cat = view_arg.children[0]
        i_click = MagicMock()
        i_click.user.id = 5555
        i_click.user.display_name = "Newbie"
        i_click.response.edit_message = AsyncMock()

        await btn_cat.callback(i_click)
        i_click.response.edit_message.assert_awaited_once()
        assert service.get_active_pet(5555).pet_id == "tuxedo_cat"
        assert service.get_or_create_user(5555).has_claimed_starter is True

        # 3. Direct slash command /pet starter by a second user
        i_cmd = MagicMock()
        i_cmd.user.id = 6666
        i_cmd.user.display_name = "DogLover"
        i_cmd.response.send_message = AsyncMock()

        dog_choice = app_commands.Choice(name="Golden Retriever", value="golden_dog")
        await cog.pet_starter.callback(cog, i_cmd, pet=dog_choice, nickname="Buddy")
        i_cmd.response.send_message.assert_awaited_once()
        assert service.get_active_pet(6666).nickname == "Buddy"

    asyncio.run(_test())


def test_casino_and_earning_commands():
    """Test /slots, /coinflip, /blackjack, /highlow, /work, /beg, /duel, and /bank slash commands."""
    async def _test():
        from discord import app_commands
        cog, service, _ = _make_rewards_cog()
        service.add_points(999, 5000, "START")
        service.add_points(888, 5000, "START")

        # 1. /slots
        i_slots = MagicMock()
        i_slots.user.id = 999
        i_slots.user.display_name = "SlotsSpinner"
        i_slots.response.send_message = AsyncMock()
        await cog.slots.callback(cog, i_slots, amount=100)
        i_slots.response.send_message.assert_awaited_once()

        # 2. /coinflip
        i_cf = MagicMock()
        i_cf.user.id = 999
        i_cf.user.display_name = "Flipper"
        i_cf.response.send_message = AsyncMock()
        choice_heads = app_commands.Choice(name="Heads", value="heads")
        await cog.coinflip.callback(cog, i_cf, choice=choice_heads, amount=50)
        i_cf.response.send_message.assert_awaited_once()

        # 3. /blackjack
        i_bj = MagicMock()
        i_bj.user.id = 999
        i_bj.user.display_name = "CardPlayer"
        i_bj.response.send_message = AsyncMock()
        await cog.blackjack.callback(cog, i_bj, amount=50)
        i_bj.response.send_message.assert_awaited_once()

        # 4. /highlow
        i_hl = MagicMock()
        i_hl.user.id = 999
        i_hl.user.display_name = "HighLowPlayer"
        i_hl.response.send_message = AsyncMock()
        await cog.highlow.callback(cog, i_hl, amount=50)
        i_hl.response.send_message.assert_awaited_once()

        # 5. /work
        i_work = MagicMock()
        i_work.user.id = 999
        i_work.user.display_name = "Worker"
        i_work.response.send_message = AsyncMock()
        await cog.work.callback(cog, i_work)
        i_work.response.send_message.assert_awaited_once()
        work_embed = i_work.response.send_message.call_args.kwargs["embed"]
        assert "Campus Shift Complete" in work_embed.title

        # 6. /beg
        i_beg = MagicMock()
        i_beg.user.id = 999
        i_beg.user.display_name = "Scavenger"
        i_beg.response.send_message = AsyncMock()
        await cog.beg.callback(cog, i_beg)
        i_beg.response.send_message.assert_awaited_once()
        scav_embed = i_beg.response.send_message.call_args.kwargs["embed"]
        assert "Campus Scavenge" in scav_embed.title

        # 7. /duel challenge
        i_duel = MagicMock()
        i_duel.user.id = 999
        i_duel.user.mention = "<@999>"
        i_duel.response.send_message = AsyncMock()
        target_m = MagicMock()
        target_m.id = 888
        target_m.bot = False
        target_m.display_name = "Challenged"
        target_m.mention = "<@888>"
        await cog.duel.callback(cog, i_duel, target=target_m, amount=100)
        i_duel.response.send_message.assert_awaited_once()

        # 8. /bank deposit and view
        i_bank_dep = MagicMock()
        i_bank_dep.user.id = 999
        i_bank_dep.response.send_message = AsyncMock()
        choice_dep = app_commands.Choice(name="Deposit", value="deposit")
        await cog.bank.callback(cog, i_bank_dep, action=choice_dep, amount=500)
        i_bank_dep.response.send_message.assert_awaited_once()
        dep_embed = i_bank_dep.response.send_message.call_args.kwargs["embed"]
        assert "Deposit Successful" in dep_embed.title

        i_bank_view = MagicMock()
        i_bank_view.user.id = 999
        i_bank_view.user.display_name = "Banker"
        i_bank_view.response.send_message = AsyncMock()
        choice_view = app_commands.Choice(name="View", value="view")
        await cog.bank.callback(cog, i_bank_view, action=choice_view)
        i_bank_view.response.send_message.assert_awaited_once()
        view_embed = i_bank_view.response.send_message.call_args.kwargs["embed"]
        assert "Piggy Bank" in view_embed.title

    asyncio.run(_test())


