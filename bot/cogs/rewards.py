from datetime import datetime, timezone
import logging
import math
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.rewards_db import (
    BetOutcome,
    DailyAlreadyClaimedError,
    InsufficientPointsError,
    ItemNotFoundError,
    MaxBetsReachedError,
    RewardsDBService,
    RewardsError,
    ShieldActiveError,
    ITEM_DEFINITIONS,
)

logger = logging.getLogger(__name__)


async def build_leaderboard_embed(
    rewards_service: RewardsDBService,
    guild: Optional[discord.Guild],
    page: int = 1,
    per_page: int = 10,
) -> tuple[discord.Embed, int]:
    """Construct paginated leaderboard embed and return total pages."""
    offset = (page - 1) * per_page
    entries, total_count = rewards_service.get_leaderboard(limit=per_page, offset=offset)
    total_pages = max(1, math.ceil(total_count / per_page))

    embed = discord.Embed(
        title="🏆 BSCS 1-4 — Uno Points Leaderboard",
        color=discord.Color.gold(),
        description="Rankings based on total accumulated Uno Points & Daily Streaks.",
    )

    if not entries:
        embed.description = "No members have earned points yet. Run `/daily` to get started!"
        embed.set_footer(text=f"Page {page} of {total_pages} • Total Members: {total_count}")
        return embed, total_pages

    lines = []
    for entry in entries:
        # Resolve display name
        display_name = f"User {entry.user_id}"
        if guild:
            member = guild.get_member(entry.user_id)
            if member:
                display_name = member.display_name

        # Rank badge
        if entry.rank == 1:
            rank_str = "🥇 **#1**"
        elif entry.rank == 2:
            rank_str = "🥈 **#2**"
        elif entry.rank == 3:
            rank_str = "🥉 **#3**"
        else:
            rank_str = f"**#{entry.rank}**"

        streak_str = f" · 🔥 {entry.daily_streak}d" if entry.daily_streak > 0 else ""
        lines.append(f"{rank_str} **{display_name}** — `{entry.points:,} pts`{streak_str}")

    embed.add_field(name="Class Leaderboard", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"Page {page} of {total_pages} • Total Members: {total_count}")
    return embed, total_pages


class LeaderboardView(discord.ui.View):
    """Interactive Discord UI View with buttons for paginated leaderboard browsing."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        guild: Optional[discord.Guild],
        page: int = 1,
        per_page: int = 10,
        total_pages: int = 1,
    ):
        super().__init__(timeout=180.0)
        self.rewards_service = rewards_service
        self.guild = guild
        self.page = page
        self.per_page = per_page
        self.total_pages = total_pages
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_button.disabled = (self.page <= 1)
        self.page_indicator.label = f"Page {self.page}/{self.total_pages}"
        self.next_button.disabled = (self.page >= self.total_pages)

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, custom_id="lb_prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.page > 1:
            self.page -= 1
            embed, self.total_pages = await build_leaderboard_embed(
                self.rewards_service, self.guild, self.page, self.per_page
            )
            self._update_buttons()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.primary, disabled=True, custom_id="lb_indicator")
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="lb_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.page < self.total_pages:
            self.page += 1
            embed, self.total_pages = await build_leaderboard_embed(
                self.rewards_service, self.guild, self.page, self.per_page
            )
            self._update_buttons()
            await interaction.response.edit_message(embed=embed, view=self)


class RewardsCog(commands.Cog):
    """Cog managing student economy, daily attendance streaks, profiles, and leaderboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rewards_service: RewardsDBService = getattr(
            bot, "rewards_service", RewardsDBService(getattr(bot.settings, "rewards_db_path", "data/rewards.db"))
        )

    async def _log_activity(
        self,
        title: str,
        description: str,
        color: discord.Color = discord.Color.blue(),
        fields: Optional[list[tuple[str, str, bool]]] = None,
    ) -> None:
        """Helper to post real-time rewards activity to the configured private log channel."""
        log_channel_id = getattr(self.bot.settings, "rewards_log_channel_id", None)
        if not log_channel_id:
            return

        channel = self.bot.get_channel(log_channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(log_channel_id)
            except Exception as e:
                logger.debug(f"[rewards_log] Could not fetch log channel {log_channel_id}: {e}")
                return

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if fields:
            for name, val, inline in fields:
                embed.add_field(name=name, value=val, inline=inline)

        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.warning(f"[rewards_log] Failed to send log to channel {log_channel_id}: {e}")

    @app_commands.command(name="daily", description="Claim your daily attendance Uno Points & build your streak!")
    async def daily(self, interaction: discord.Interaction) -> None:
        """Claim daily points with consecutive streak multipliers."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.claim_daily(user_id)

            embed = discord.Embed(
                title="📅 Daily Attendance Claimed!",
                color=discord.Color.green(),
                description=f"You earned **+{res.points_awarded} Uno Points** today!",
            )
            embed.add_field(name="Base Reward", value=f"+{res.base_points} pts", inline=True)
            embed.add_field(
                name="Streak Bonus",
                value=f"+{res.streak_bonus} pts (Day {res.streak} 🔥)",
                inline=True,
            )
            embed.add_field(name="Total Balance", value=f"**{res.new_balance:,} pts**", inline=True)

            if res.milestone_3k_unlocked:
                embed.add_field(
                    name="🎉 MILESTONE UNLOCKED!",
                    value="You crossed **3,000 Lifetime Points**! You earned the **`[🍫 Exam Survivor]`** badge and unlocked the physical **Exams Survival Kit**!",
                    inline=False,
                )

            embed.set_footer(text="Come back tomorrow after midnight PHT to continue your streak!")
            await interaction.response.send_message(embed=embed)

            # Post to log channel
            await self._log_activity(
                title="📅 Daily Claim",
                description=f"**{interaction.user.display_name}** (`{interaction.user.id}`) claimed their daily reward.",
                color=discord.Color.green(),
                fields=[
                    ("Points Earned", f"+{res.points_awarded} pts", True),
                    ("Daily Streak", f"{res.streak} days 🔥", True),
                    ("New Balance", f"{res.new_balance:,} pts", True),
                ],
            )

        except DailyAlreadyClaimedError as e:
            cooldown_str = f"<t:{int(e.next_claim_time.timestamp())}:R>" if e.next_claim_time else "tomorrow"
            embed = discord.Embed(
                title="⏳ Already Claimed Today",
                color=discord.Color.orange(),
                description=f"You've already claimed your daily reward today!\nNext claim available: **{cooldown_str}**",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="balance", description="Check your Uno Points balance, daily streak, and shield status.")
    async def balance(self, interaction: discord.Interaction) -> None:
        """Display caller's points, streak, and 1-week shield status."""
        profile = self.rewards_service.get_profile(interaction.user.id)

        shield_status = (
            f"🛡️ Active (<t:{int(profile.shield_until.timestamp())}:R>)"
            if profile.has_shield and profile.shield_until
            else "❌ No Active Shield"
        )

        embed = discord.Embed(
            title=f"💰 Balance — {interaction.user.display_name}",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Current Points", value=f"**{profile.points:,} pts**", inline=True)
        embed.add_field(name="Daily Streak", value=f"**{profile.daily_streak} days** 🔥", inline=True)
        embed.add_field(name="Server Rank", value=f"**#{profile.rank}** 🏆", inline=True)
        embed.add_field(name="Immunity Shield", value=shield_status, inline=False)
        embed.set_footer(text="Use /daily to earn points • /bet to gamble • /shop to redeem prizes")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="View a student's full Uno profile, rank, badges, and inventory.")
    @app_commands.describe(member="The classmate to view (defaults to you).")
    async def profile(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        """Display rich profile card with points, badges, and inventory."""
        target = member or interaction.user
        profile = self.rewards_service.get_profile(target.id)

        shield_status = (
            f"🛡️ Active (<t:{int(profile.shield_until.timestamp())}:R>)"
            if profile.has_shield and profile.shield_until
            else "❌ None"
        )

        embed = discord.Embed(
            title=f"👤 Student Profile — {target.display_name}",
            color=discord.Color.purple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Wallet Balance", value=f"**{profile.points:,} pts**", inline=True)
        embed.add_field(name="Lifetime Earned", value=f"**{profile.lifetime_points:,} pts**", inline=True)
        embed.add_field(name="Daily Streak", value=f"**{profile.daily_streak}d** 🔥", inline=True)
        embed.add_field(name="Server Rank", value=f"**#{profile.rank}** 🏆", inline=True)
        embed.add_field(name="1-Week Shield", value=shield_status, inline=True)

        badges_str = " · ".join(profile.badges) if profile.badges else "No badges unlocked yet."
        embed.add_field(name="🏅 Badges & Milestones", value=badges_str, inline=False)

        if profile.inventory:
            inv_lines = [f"• `{qty}x` **{item_id}**" for item_id, qty in profile.inventory.items()]
            embed.add_field(name="🎒 Inventory", value="\n".join(inv_lines), inline=False)
        else:
            embed.add_field(name="🎒 Inventory", value="Bag is empty.", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rank", description="View the top 10 highest-ranked BSCS 1-4 members.")
    async def rank(self, interaction: discord.Interaction) -> None:
        """Display quick Top 10 leaderboard."""
        embed, _ = await build_leaderboard_embed(self.rewards_service, interaction.guild, page=1, per_page=10)
        embed.title = "📊 Top 10 Scholars — Uno Rankings"
        await interaction.response.send_message(embed=embed)

    @commands.command(name="rank")
    async def rank_prefix(self, ctx: commands.Context) -> None:
        """Prefix command !rank to view top 10 members."""
        embed, _ = await build_leaderboard_embed(self.rewards_service, ctx.guild, page=1, per_page=10)
        embed.title = "📊 Top 10 Scholars — Uno Rankings"
        await ctx.send(embed=embed)

    @app_commands.command(name="leaderboard", description="Browse the full paginated class leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        """Browse the full class leaderboard with interactive pagination buttons."""
        embed, total_pages = await build_leaderboard_embed(
            self.rewards_service, interaction.guild, page=1, per_page=10
        )
        view = LeaderboardView(
            self.rewards_service,
            interaction.guild,
            page=1,
            per_page=10,
            total_pages=total_pages,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="bet", description="Gamble 50 Uno Points for double points, skill drops, or bust! (Max 3/day)")
    async def bet(self, interaction: discord.Interaction) -> None:
        """Play 50 pt roulette minigame."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.play_bet(user_id)

            if res.outcome == BetOutcome.DOUBLE:
                title = "🎰 JACKPOT! Double Points!"
                desc = f"You won **+100 Uno Points**! (Net Gain: **+50 pts**)"
                color = discord.Color.gold()
            elif res.outcome == BetOutcome.SKILL_DROP:
                title = "🃏 Skill Card Dropped!"
                desc = f"You won a rare consumable item: **{res.reward_item_name}**!\n*Check `/inventory` or activate with `/use`!*"
                color = discord.Color.purple()
            elif res.outcome == BetOutcome.REFUND:
                title = "🪙 Break-Even / Refund"
                desc = "You rolled a safe break-even! Your **50 Uno Points** were refunded."
                color = discord.Color.blue()
            else:
                title = "❌ Busted! (House Wins)"
                desc = "The house took your bet. You lost **50 Uno Points**."
                color = discord.Color.red()

            embed = discord.Embed(title=title, description=desc, color=color)
            embed.add_field(name="Current Balance", value=f"**{res.new_balance:,} pts**", inline=True)
            embed.add_field(name="Bets Remaining Today", value=f"**{res.bets_remaining} / 3**", inline=True)
            embed.set_footer(text="Gamble responsibly • Max 3 bets per day • Resets midnight PHT")

            await interaction.response.send_message(embed=embed)

            # Log to admin channel
            await self._log_activity(
                title=f"🎰 Bet: {res.outcome.value}",
                description=f"**{interaction.user.display_name}** placed a 50 pt bet.",
                color=color,
                fields=[
                    ("Outcome", res.outcome.value, True),
                    (
                        "Reward / Change",
                        f"{'+' if res.points_delta > 0 else ''}{res.points_delta} pts"
                        + (f" ({res.reward_item_name})" if res.reward_item_name else ""),
                        True,
                    ),
                    ("New Balance", f"{res.new_balance:,} pts", True),
                ],
            )
        except InsufficientPointsError:
            await interaction.response.send_message(
                "❌ You need at least **50 Uno Points** to place a bet! Earn more with `/daily`.",
                ephemeral=True,
            )
        except MaxBetsReachedError:
            await interaction.response.send_message(
                "⏳ You've reached your daily limit of **3 bets** today! Come back tomorrow after midnight PHT.",
                ephemeral=True,
            )

    @app_commands.command(name="steal", description="Consume a Pickpocket Card to attempt stealing 10%-15% points from a classmate!")
    @app_commands.describe(target="The classmate you want to pickpocket.")
    async def steal(self, interaction: discord.Interaction, target: discord.Member) -> None:
        """Attempt pickpocketing a classmate."""
        if target.bot:
            await interaction.response.send_message("❌ You cannot steal from a bot!", ephemeral=True)
            return

        if target.id == interaction.user.id:
            await interaction.response.send_message("❌ You cannot pickpocket yourself!", ephemeral=True)
            return

        try:
            res = self.rewards_service.execute_steal(interaction.user.id, target.id)

            if res.blocked_by_shield:
                embed = discord.Embed(
                    title="🛡️ BLOCKED by Immunity Shield!",
                    description=(
                        f"**{target.display_name}** is protected by an active **1-Week Immunity Shield**!\n"
                        f"Your steal was deflected and your **🦹 Pickpocket Card** was consumed."
                    ),
                    color=discord.Color.blue(),
                )
                await interaction.response.send_message(embed=embed)
                await self._log_activity(
                    title="🛡️ Steal Blocked by Shield",
                    description=f"**{interaction.user.display_name}** attempted to steal from **{target.display_name}**, but was blocked by shield.",
                    color=discord.Color.blue(),
                )
                return

            if res.success:
                embed = discord.Embed(
                    title="🦹 Robbery Successful!",
                    description=(
                        f"You sneaked up on **{target.display_name}** and stole **+{res.points_stolen:,} Uno Points**!\n"
                        f"Your **🦹 Pickpocket Card** was consumed."
                    ),
                    color=discord.Color.green(),
                )
                embed.add_field(name="Your New Balance", value=f"**{res.thief_new_balance:,} pts**", inline=True)
                embed.add_field(name=f"{target.display_name}'s Balance", value=f"**{res.target_new_balance:,} pts**", inline=True)
                await interaction.response.send_message(embed=embed)

                await self._log_activity(
                    title="🦹 Steal Success",
                    description=f"**{interaction.user.display_name}** stole **{res.points_stolen:,} pts** from **{target.display_name}**.",
                    color=discord.Color.green(),
                    fields=[
                        ("Stolen Amount", f"{res.points_stolen:,} pts", True),
                        ("Thief Balance", f"{res.thief_new_balance:,} pts", True),
                        ("Victim Balance", f"{res.target_new_balance:,} pts", True),
                    ],
                )
            else:
                embed = discord.Embed(
                    title="🚨 BUSTED! Caught Red-Handed!",
                    description=(
                        f"**{target.display_name}** caught you trying to pickpocket them!\n"
                        f"You were fined **-{res.fine_paid:,} Uno Points** which was transferred to them as compensation!"
                    ),
                    color=discord.Color.red(),
                )
                embed.add_field(name="Your Balance", value=f"**{res.thief_new_balance:,} pts**", inline=True)
                embed.add_field(name=f"{target.display_name}'s Balance", value=f"**{res.target_new_balance:,} pts**", inline=True)
                await interaction.response.send_message(embed=embed)

                await self._log_activity(
                    title="🚨 Steal Busted",
                    description=f"**{interaction.user.display_name}** got caught stealing from **{target.display_name}** and paid a **{res.fine_paid:,} pt** fine.",
                    color=discord.Color.red(),
                )

        except ItemNotFoundError:
            await interaction.response.send_message(
                "❌ You do not have a **🦹 Pickpocket Card** in your inventory! Win one from `/bet` or buy from `/shop`.",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="inventory", description="View your owned skill cards and consumables.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        """Display caller's inventory cards."""
        inv = self.rewards_service.get_inventory(interaction.user.id)
        embed = discord.Embed(
            title=f"🎒 Inventory — {interaction.user.display_name}",
            color=discord.Color.purple(),
        )
        if not inv:
            embed.description = "Your inventory is currently empty! Win items from `/bet` or buy from `/shop`."
        else:
            lines = []
            for item_id, qty in inv.items():
                item_info = ITEM_DEFINITIONS.get(item_id, {"name": item_id, "description": ""})
                lines.append(f"• `{qty}x` **{item_info['name']}**\n  *{item_info['description']}*")
            embed.description = "\n\n".join(lines)
            embed.set_footer(text="Use /use to activate consumable cards!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="use", description="Activate a consumable item from your inventory (e.g. 1-Week Shield).")
    @app_commands.describe(item="The consumable item to activate.")
    @app_commands.choices(item=[
        app_commands.Choice(name="🛡️ 1-Week Immunity Shield", value="shield_1w"),
        app_commands.Choice(name="⚡ 2x Daily Booster Card", value="double_daily"),
    ])
    async def use(self, interaction: discord.Interaction, item: app_commands.Choice[str]) -> None:
        """Activate an item from inventory."""
        try:
            res = self.rewards_service.use_item(interaction.user.id, item.value)
            embed = discord.Embed(
                title=f"✨ {res.item_name} Activated!",
                description=res.description,
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)

            await self._log_activity(
                title="✨ Item Activated",
                description=f"**{interaction.user.display_name}** activated **{res.item_name}**.",
                color=discord.Color.blue(),
            )
        except ItemNotFoundError:
            await interaction.response.send_message(
                f"❌ You do not have **{item.name}** in your inventory!",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RewardsCog(bot))
