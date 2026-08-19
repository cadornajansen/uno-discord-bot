from datetime import datetime, timezone
import io
import logging
import math
from pathlib import Path
import random
from typing import Any, Optional, Union
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.services.rewards_db import (
    BetOutcome,
    DailyAlreadyClaimedError,
    InsufficientPointsError,
    ItemNotFoundError,
    MaxBetsReachedError,
    MaxTriviaReachedError,
    RewardsDBService,
    RewardsError,
    ShieldActiveError,
    TriviaQuestion,
    TriviaResult,
    PetRecord,
    PET_CATALOG,
    ITEM_DEFINITIONS,
    SHOP_CATALOG,
    PHT,
    BlackjackGame,
    HighLowGame,
    calculate_blackjack_score,
    WorkResult,
    ScavengeResult,
    DuelResult,
    STARTER_PET_CHOICES,
    BountyRecord,
    RPSDuelGame,
    RouletteDuelGame,
    RPGCombatGame,
)

logger = logging.getLogger(__name__)


def resolve_pet_image_path(image_file: Optional[str]) -> Optional[Path]:
    """Robustly locate absolute path for pet pixel-art image across local, bundled assets, and Docker environments."""
    if not image_file:
        return None

    cogs_dir = Path(__file__).resolve().parent
    bot_dir = cogs_dir.parent
    repo_root = bot_dir.parent

    candidates = [
        bot_dir / "assets" / "pets" / image_file,
        repo_root / "data" / "pets" / image_file,
        Path.cwd() / "bot" / "assets" / "pets" / image_file,
        Path.cwd() / "data" / "pets" / image_file,
        Path("data/pets") / image_file,
        Path(__file__).resolve().parent.parent / "data" / "pets" / image_file,
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


async def build_leaderboard_embed(
    rewards_service: RewardsDBService,
    guild: Optional[discord.Guild],
    bot: Optional[commands.Bot] = None,
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
        # Resolve display name or username
        display_name = None
        if guild:
            member = guild.get_member(entry.user_id)
            if not member:
                try:
                    member = await guild.fetch_member(entry.user_id)
                except Exception:
                    member = None
            if member:
                display_name = member.display_name

        if not display_name and bot:
            user = bot.get_user(entry.user_id)
            if not user:
                try:
                    user = await bot.fetch_user(entry.user_id)
                except Exception:
                    user = None
            if user:
                display_name = user.display_name or user.name

        if not display_name:
            display_name = f"<@{entry.user_id}>"

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
        bot: Optional[commands.Bot] = None,
        page: int = 1,
        per_page: int = 10,
        total_pages: int = 1,
    ):
        super().__init__(timeout=180.0)
        self.rewards_service = rewards_service
        self.guild = guild
        self.bot = bot
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
                self.rewards_service, self.guild, bot=self.bot, page=self.page, per_page=self.per_page
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
                self.rewards_service, self.guild, bot=self.bot, page=self.page, per_page=self.per_page
            )
            self._update_buttons()
            await interaction.response.edit_message(embed=embed, view=self)


class TriviaAnswerButton(discord.ui.Button):
    """Button for a single trivia answer choice."""

    def __init__(self, option_index: int, label: str, is_true_false: bool = False):
        if is_true_false:
            emoji = "✅" if label.lower() == "true" else "❌"
            display_label = f"{emoji} {label}"
        else:
            letters = ["A", "B", "C", "D"]
            prefix = f"{letters[option_index]}: " if option_index < len(letters) else ""
            display_label = f"{prefix}{label}"[:80]

        super().__init__(
            label=display_label,
            style=discord.ButtonStyle.secondary,
            custom_id=f"trivia_ans_{option_index}",
        )
        self.option_index = option_index

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "TriviaView" = self.view  # type: ignore
        if interaction.user.id != view.user_id:
            await interaction.response.send_message(
                "❌ Only the student who started this trivia quiz can answer it!", ephemeral=True
            )
            return

        is_correct = (self.option_index == view.question.correct_index)

        try:
            result = view.rewards_service.record_trivia_attempt(view.user_id, is_correct)
        except MaxTriviaReachedError as e:
            await interaction.response.send_message(f"⏳ {e}", ephemeral=True)
            return

        # Disable all buttons & highlight correct (green) and clicked (red if wrong)
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                if getattr(child, "option_index", None) == view.question.correct_index:
                    child.style = discord.ButtonStyle.success
                elif child == self and not is_correct:
                    child.style = discord.ButtonStyle.danger

        letters = ["A", "B", "C", "D"]
        correct_answer_text = view.question.options[view.question.correct_index]
        is_tf = set(opt.lower() for opt in view.question.options) == {"true", "false"}
        ans_prefix = "" if is_tf else f"{letters[view.question.correct_index]}: "

        embed = discord.Embed()
        if is_correct:
            embed.title = "🎉 Correct Answer! (+50 Uno Points)"
            embed.color = discord.Color.green()
            embed.description = (
                f"**You nailed it!**\n\n"
                f"**Question:** {view.question.question}\n"
                f"**Answer:** `{ans_prefix}{correct_answer_text}`\n\n"
                f"💡 **Explanation:** {view.question.explanation}\n\n"
                f"💰 **Reward:** `+50 Uno Points`\n"
                f"💳 **New Balance:** `{result.new_balance:,} pts`\n"
                f"🎯 **Quizzes Remaining Today:** `{result.trivia_remaining} / 3`"
            )
            if view.cog:
                await view.cog._log_activity(
                    title="🧠 Trivia Quiz Success (+50 pts)",
                    description=f"**{interaction.user.display_name}** correctly answered a **{view.question.category}** question!",
                    color=discord.Color.green(),
                    fields=[
                        ("Question", view.question.question, False),
                        ("Reward", "+50 Uno Points", True),
                        ("Balance", f"{result.new_balance:,} pts", True),
                    ],
                )
        else:
            embed.title = "❌ Incorrect Answer!"
            embed.color = discord.Color.red()
            embed.description = (
                f"**Nice try!** Better luck on your next question.\n\n"
                f"**Question:** {view.question.question}\n"
                f"**Correct Answer:** `{ans_prefix}{correct_answer_text}`\n\n"
                f"💡 **Explanation:** {view.question.explanation}\n\n"
                f"💳 **Current Balance:** `{result.new_balance:,} pts`\n"
                f"🎯 **Quizzes Remaining Today:** `{result.trivia_remaining} / 3`"
            )

        embed.set_footer(text=f"{view.question.category} • BSCS 1-4 Trivia Quiz")
        await interaction.response.edit_message(embed=embed, view=view)


class TriviaView(discord.ui.View):
    """Interactive Discord view for answering a trivia quiz."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        user_id: int,
        question: TriviaQuestion,
        cog: Optional[Any] = None,
    ):
        super().__init__(timeout=120.0)
        self.rewards_service = rewards_service
        self.user_id = user_id
        self.question = question
        self.cog = cog

        is_tf = set(opt.lower() for opt in question.options) == {"true", "false"}
        for idx, opt in enumerate(question.options):
            self.add_item(TriviaAnswerButton(option_index=idx, label=opt, is_true_false=is_tf))


class AirdropCatchButton(discord.ui.Button):
    """Button for catching a portion of a public point airdrop."""

    def __init__(self):
        super().__init__(
            label="🎁 Catch Points! (4/4 Left)",
            style=discord.ButtonStyle.success,
            custom_id="airdrop_catch",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "AirdropCatchView" = self.view  # type: ignore
        user_id = interaction.user.id
        if user_id in view.claimers:
            await interaction.response.send_message(
                "❌ You already caught a portion of this airdrop! Leave some for your classmates.",
                ephemeral=True,
            )
            return

        view.claimers.append(user_id)
        active_pet = view.rewards_service.get_active_pet(user_id)
        pts_per_claim = 35 if (active_pet and active_pet.species == "fox") else 25
        view.claimers.append(user_id)
        view.claimer_names.append(interaction.user.display_name)
        new_bal = view.rewards_service.add_points(
            user_id, pts_per_claim, "AIRDROP_CATCH", f"Caught airdrop from user {view.launcher_id}"
        )
        remaining = view.max_claims - len(view.claimers)

        if remaining <= 0:
            self.disabled = True
            self.label = "🎁 Airdrop Fully Claimed!"
            self.style = discord.ButtonStyle.secondary
            view.embed.title = "🌧️ Point Airdrop — FULLY CLAIMED!"
            view.embed.color = discord.Color.dark_grey()
            winners = ", ".join(f"**{n}**" for n in view.claimer_names)
            view.embed.description = (
                f"**Care package dropped by <@{view.launcher_id}> has been completely caught!**\n\n"
                f"🎉 **Lucky Catchers:** {winners} (+25 pts each!)"
            )
            await interaction.response.edit_message(embed=view.embed, view=view)
        else:
            self.label = f"🎁 Catch Points! ({remaining}/{view.max_claims} Left)"
            await interaction.response.edit_message(embed=view.embed, view=view)
            fox_tag = " [🦊 Fox Scavenger Bonus!]" if pts_per_claim == 35 else ""
            await interaction.followup.send(
                f"🎉 You caught **+{pts_per_claim} Uno Points**{fox_tag} from the airdrop! Your new balance: **{new_bal:,} pts**.",
                ephemeral=True,
            )


class AirdropCatchView(discord.ui.View):
    """Interactive view for public point airdrops."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        launcher_id: int,
        embed: discord.Embed,
    ):
        super().__init__(timeout=180.0)
        self.rewards_service = rewards_service
        self.launcher_id = launcher_id
        self.embed = embed
        self.max_claims = 4
        self.claimers: list[int] = []
        self.claimer_names: list[str] = []
        self.add_item(AirdropCatchButton())


def build_pet_guide_embed() -> discord.Embed:
    """Build comprehensive student handbook for the Pet Companion System."""
    embed = discord.Embed(
        title="📖 Uno Bot — Pet Companion Handbook & Guide",
        description=(
            "Welcome to the **Pet Companion System**! Adopt loyal pixel-art companions that provide "
            "**permanent passive economic multipliers**, **PvP duel battle perks**, daily care rewards, and vibrant profile aesthetics."
        ),
        color=discord.Color.teal(),
    )

    embed.add_field(
        name="🎁 1. FREE Starter Companion (0 pts)",
        value=(
            "• Every student can claim **1 Free Starter Pet** using **`/pet starter`** or by opening **`/pet`**!\n"
            "• Choose between **🐱 Tuxedo Cat**, **🐶 Golden Retriever**, or **🐰 Lop-Eared Bunny** at **0 pts cost** with 100% happiness!"
        ),
        inline=False,
    )

    embed.add_field(
        name="🐾 2. How Companions Work & 50%+ Discount Catalog",
        value=(
            "• Each pet variant grants a **permanent passive buff** while equipped as your active companion.\n"
            "• **🐱 Cats**: Tuxedo (`50 pts`), Calico (`100 pts`)\n"
            "• **🐶 Dogs**: Golden (`50 pts`), Shiba Inu (`100 pts`)\n"
            "• **🐰 Bunnies**: Brown (`150 pts`), White (`200 pts`)\n"
            "• **🦉 Owls**: Scholar (`150 pts`), Ice Owl (`200 pts`)\n"
            "• **🐢 Turtles**: Master Oogway (`200 pts`)\n"
            "• **🦊 Foxes**: Orange Trickster (`200 pts`), Arctic (`250 pts`)\n"
            "• **🦎 Axolotls**: Pink (`150 pts`), Rainbow (`250 pts`)\n"
            "• **🐠 Goldfish**: Fiery Goldfish (`150 pts`)\n"
            "• Adopt via **`/pet adopt <species>`** or in the **`/shop`** Pet Shelter tab!"
        ),
        inline=False,
    )

    embed.add_field(
        name="🌟 3. Passive Economic Perks",
        value=(
            "• 🐱 **Cats** — **2x Daily Attendance Points** on `/daily` permanently.\n"
            "• 🐶 **Dogs** — **Guard Dog**: 75% thief catch rate & inflicts a 50 pt bite fine on pickpockets.\n"
            "• 🐰 **Bunnies** — **Lucky Gambler**: +15% Jackpot & Double win rates in `/bet` and `/slots`.\n"
            "• 🦉 **Owls** — **Quiz Master**: +75 pts per correct trivia quiz and 4th attempt/day.\n"
            "• 🐢 **Turtles** — **Streak Freeze**: Prevents daily streak resets on missed days & +2d shield boost.\n"
            "• 🦊 **Foxes** — **Pickpocket Master**: +15% steal rate & +10 pt bonus per airdrop catch.\n"
            "• 🦎/🐠 **Axolotls & Goldfish** — **5% Cashback**: Instant 5% refund on all shop redemptions."
        ),
        inline=False,
    )

    embed.add_field(
        name="⚔️ 4. PvP Duel Combat Perks (`/duel`)",
        value=(
            "• 🐶 **Dogs** (*Intimidating Bark*) — 20% chance to bark fiercely, reducing opponent's roll/damage by 15.\n"
            "• 🐰 **Bunnies** (*Lucky Reroll*) — Automatically rerolls duel dice if under 30, and +15% hit rate on RPG Ultimates.\n"
            "• 🦉 **Owls** (*Calculated Strike*) — +10 clutch roll bonus when roll is within 5 points of the opponent.\n"
            "• 🦊 **Foxes** (*Consolation Siphon*) — 25% chance on losing a duel to sneakily siphon back 20% of your lost wager."
        ),
        inline=False,
    )

    embed.add_field(
        name="🍖 5. Care, Happiness & Leveling Up",
        value=(
            "• Open your pet dashboard with **`/pet`** (or `/pet view`).\n"
            "• Use **`[ 🍖 Feed Snack ]`** & **`[ 💖 Cuddle & Pet ]`** to increase happiness (up to 100%) and gain +15 XP.\n"
            "• Level up your companion to unlock higher resale value and stronger bond!"
        ),
        inline=False,
    )

    embed.add_field(
        name="🪙 6. Selling & Rotating Drops",
        value=(
            "• **Sell Companion**: `/pet sell <species>` refunds `60% base cost` + `+25 pts` per level above Level 1!\n"
            "• **Rotating 3-Day Drops**: Use **`/pet drop`** to view the currently featured drop, its timer, and 1-click adoption."
        ),
        inline=False,
    )

    embed.set_footer(text="Adopt from /shop (Pet Shelter) • View your pet with /pet • /pet starter for free claim")
    return embed


class PetDropAdoptButton(discord.ui.Button):
    """1-click adoption button on drop announcements."""

    def __init__(self, pet_id: str, cost: int, display_name: str):
        super().__init__(
            label=f"Adopt {display_name} ({cost:,} pts)",
            emoji="🐾",
            style=discord.ButtonStyle.success,
            custom_id=f"pet_drop_adopt_{pet_id}",
        )
        self.pet_id = pet_id
        self.cost = cost
        self.display_name = display_name

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "PetDropAnnouncementView" = self.view  # type: ignore
        user_id = interaction.user.id
        try:
            res = view.rewards_service.adopt_pet(user_id, self.pet_id)
            new_bal = view.rewards_service.get_balance(user_id)
            embed = discord.Embed(
                title="🎉 Pet Companion Adopted!",
                description=(
                    f"Congratulations! You adopted **{res.nickname}** ({res.display_name})!\n\n"
                    f"🌟 **Active Perk:** **{res.perk_title}**\n"
                    f"*{res.perk_desc}*\n\n"
                    f"💬 *\"{res.quote}\"*"
                ),
                color=discord.Color.green(),
            )
            embed.add_field(name="Remaining Balance", value=f"**{new_bal:,} Uno Points**", inline=True)

            pet_img_path = resolve_pet_image_path(res.image_file)
            if pet_img_path:
                file_att = discord.File(str(pet_img_path), filename=f"adopt_{res.image_file}")
                embed.set_thumbnail(url=f"attachment://adopt_{res.image_file}")
                await interaction.response.send_message(embed=embed, file=file_att, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

        except InsufficientPointsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class PetDropAnnouncementView(discord.ui.View):
    """View for spotlight pet drop announcement."""

    def __init__(self, rewards_service: RewardsDBService, pet_id: str, cost: int, display_name: str):
        super().__init__(timeout=None)
        self.rewards_service = rewards_service
        self.add_item(PetDropAdoptButton(pet_id, cost, display_name))


def build_pet_drop_announcement_embed(rewards_service: RewardsDBService, pet_id: Optional[str] = None) -> tuple[discord.Embed, Optional[discord.File], PetDropAnnouncementView]:
    """Build a rich spotlight announcement embed for the 3-day rotating pet drop."""
    drop_info = rewards_service.get_featured_pet()
    if pet_id and pet_id in PET_CATALOG:
        chosen_id = pet_id
        pet_data = PET_CATALOG[pet_id]
    else:
        chosen_id = drop_info["pet_id"]
        pet_data = drop_info["pet_info"]

    embed = discord.Embed(
        title=f"🌟 NEW PET DROP: {pet_data['name']} is in the Spotlight!",
        description=(
            f"**Cycle Schedule:** Day {drop_info['cycle_day']} of 3 • Next rotation: <t:{drop_info['next_drop_timestamp']}:R>\n\n"
            f"*{pet_data['title']}*\n\n"
            f"🌟 **Perk:** **{pet_data['perk_title']}**\n"
            f"*{pet_data['perk_desc']}*\n\n"
            f"💬 *\"{random.choice(pet_data['quotes'])}\"*\n\n"
            f"💰 **Adoption Cost:** `{pet_data['cost']:,} Uno Points`"
        ),
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="📖 How to Adopt or Switch",
        value=(
            f"• Click the **Adopt button below** or type `/pet adopt pet:{chosen_id}`\n"
            "• To switch your active companion: `/pet switch <pet>`\n"
            "• Care for your pet & feed snacks: `/pet`\n"
            "• Release or sell companions anytime: `/pet sell <pet>`"
        ),
        inline=False,
    )

    file_attachment = None
    pet_img_path = resolve_pet_image_path(pet_data.get("image_file"))
    if pet_img_path:
        file_attachment = discord.File(str(pet_img_path), filename=pet_data["image_file"])
        embed.set_image(url=f"attachment://{pet_data['image_file']}")

    embed.set_footer(text="Every 3 days a new companion is spotlighted • /pet guide for full handbook")
    view = PetDropAnnouncementView(rewards_service, chosen_id, pet_data["cost"], pet_data["name"])
    return embed, file_attachment, view


class PetSellConfirmView(discord.ui.View):
    """Confirmation view for releasing/selling a pet companion."""

    def __init__(self, rewards_service: RewardsDBService, user_id: int, pet_rec: PetRecord):
        super().__init__(timeout=60.0)
        self.rewards_service = rewards_service
        self.user_id = user_id
        self.pet_rec = pet_rec

    @discord.ui.button(label="Confirm Sell & Release", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your pet companion!", ephemeral=True)
            return

        try:
            res = self.rewards_service.sell_pet(self.user_id, self.pet_rec.pet_id)
            embed = discord.Embed(
                title="🪙 Companion Released & Refund Processed",
                description=(
                    f"You safely released **{res['nickname']}** ({res['pet_name']}) back to the Pet Shelter.\n\n"
                    f"💰 **Points Refunded:** `+{res['refund_amount']:,} Uno Points`\n"
                    f"• Base Refund (60%): `+{res['base_refund']:,} pts`\n"
                    f"• Level {res['level']} Bonus: `+{res['level_bonus']:,} pts`\n\n"
                    f"💳 **New Balance:** `{res['new_balance']:,} Uno Points`"
                ),
                color=discord.Color.green(),
            )
            if res["new_active_pet"]:
                embed.add_field(
                    name="New Active Companion",
                    value=f"🐾 **{res['new_active_pet'].nickname}** ({res['new_active_pet'].display_name}) is now equipped!",
                    inline=False,
                )
            self.stop()
            await interaction.response.edit_message(embed=embed, view=None)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Cancel", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your confirmation!", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="❌ Pet sale cancelled. Your companion remains safe with you!", embed=None, view=None)


def build_starter_pet_embed(user_name: str) -> discord.Embed:
    """Build welcoming embed showcasing free starter pet options."""
    embed = discord.Embed(
        title=f"🐾 Welcome to the Pet Shelter, {user_name}!",
        description=(
            f"Every student in BSCS 1-4 is gifted **1 Free Starter Companion (0 pts)** to assist in your academic journey!\n\n"
            "Choose your loyal starter companion below:\n\n"
            "🐱 **Tuxedo Cat** (*The Serene Feline*)\n"
            "• **Perk**: `2x Daily Attendance Points` (Permanently doubles `/daily` points!)\n"
            "• **Best for**: Consistent daily point accumulation & peaceful study vibes.\n\n"
            "🐶 **Golden Retriever** (*The Faithful Guard Pup*)\n"
            "• **Perk**: `Guard Dog Defense` (75% chance to catch & bite pickpockets!)\n"
            "• **Best for**: Protecting your hard-earned wallet from classmate robbers.\n\n"
            "🐰 **Lop-Eared Bunny** (*The Lucky Rabbit*)\n"
            "• **Perk**: `Lucky Gambler` (+5% win rate in coinflips & boosted slots/bet odds!)\n"
            "• **Best for**: Risk-takers and casino gamblers.\n\n"
            "*(You can adopt other pets and variants later from the `/shop` or 3-day `/pet drop` rotation!)*"
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="Click a button below to adopt your free companion immediately!")
    return embed


class StarterPetSelectView(discord.ui.View):
    """Interactive Discord UI view for picking a free starter pet."""

    def __init__(self, rewards_service: RewardsDBService, user_id: int):
        super().__init__(timeout=120.0)
        self.rewards_service = rewards_service
        self.user_id = user_id

    async def _handle_starter_claim(self, interaction: discord.Interaction, pet_id: str) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This starter selection menu is not for you!", ephemeral=True)
            return

        try:
            pet_rec = self.rewards_service.claim_starter_pet(self.user_id, pet_id)
            self.stop()

            embed = discord.Embed(
                title=f"🎉 Welcome Your New Companion: {pet_rec.nickname}!",
                description=(
                    f"You have adopted **{pet_rec.nickname}** ({pet_rec.display_name}) for **FREE**!\n\n"
                    f"🌟 **Active Perk:** **{pet_rec.perk_title}**\n"
                    f"*{pet_rec.perk_desc}*\n\n"
                    f"💬 *\"{pet_rec.quote}\"*\n\n"
                    "Your companion is now equipped and ready for your daily campus adventures! Use `/pet` to care for them!"
                ),
                color=discord.Color.green(),
            )
            file_att = None
            pet_img_path = resolve_pet_image_path(pet_rec.image_file)
            if pet_img_path:
                file_att = discord.File(str(pet_img_path), filename=pet_rec.image_file)
                embed.set_thumbnail(url=f"attachment://{pet_rec.image_file}")

            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=None)
            else:
                await interaction.response.edit_message(embed=embed, view=None)

        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Adopt Tuxedo Cat", emoji="🐱", style=discord.ButtonStyle.primary, custom_id="starter_cat")
    async def choose_cat(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_starter_claim(interaction, "tuxedo_cat")

    @discord.ui.button(label="Adopt Golden Retriever", emoji="🐶", style=discord.ButtonStyle.success, custom_id="starter_dog")
    async def choose_dog(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_starter_claim(interaction, "golden_dog")

    @discord.ui.button(label="Adopt Lop-Eared Bunny", emoji="🐰", style=discord.ButtonStyle.secondary, custom_id="starter_bunny")
    async def choose_bunny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_starter_claim(interaction, "brown_bunny")


def build_blackjack_embed(game: BlackjackGame, player_name: str) -> discord.Embed:
    """Build rich embed for Blackjack 21 game state."""
    p_score = calculate_blackjack_score(game.player_hand)
    p_cards_str = "  ".join(f"`{c}`" for c in game.player_hand)

    if game.status == "IN_PROGRESS":
        d_cards_str = f"`{game.dealer_hand[0]}`  `🎴 ?`"
        d_score_str = f"{game.dealer_hand[0].value} + ?"
        color = discord.Color.blue()
        title = "🃏 Blackjack 21 — Hand in Progress"
    else:
        d_score = calculate_blackjack_score(game.dealer_hand)
        d_cards_str = "  ".join(f"`{c}`" for c in game.dealer_hand)
        d_score_str = str(d_score)

        if game.status in ("PLAYER_WIN", "BLACKJACK"):
            color = discord.Color.green()
            title = "🎉 Blackjack 21 — WIN!"
        elif game.status == "PUSH":
            color = discord.Color.gold()
            title = "🤝 Blackjack 21 — Push / Tie"
        else:
            color = discord.Color.red()
            title = "❌ Blackjack 21 — House Wins"

    embed = discord.Embed(title=title, description=f"💰 **Wager:** `{game.wager:,} Uno Points`\n\n{game.message}", color=color)
    embed.add_field(name=f"👤 {player_name}'s Hand ({p_score})", value=p_cards_str, inline=False)
    embed.add_field(name=f"🎩 Dealer's Hand ({d_score_str})", value=d_cards_str, inline=False)

    if game.status != "IN_PROGRESS":
        embed.add_field(name="Wallet Balance", value=f"**{game.new_balance:,} Uno Points**", inline=False)

    embed.set_footer(text="Blackjack pays 3:2 • Dealer hits on soft 17")
    return embed


class BlackjackView(discord.ui.View):
    """Interactive Discord UI view for Blackjack 21."""

    def __init__(self, rewards_service: RewardsDBService, user_id: int, player_name: str):
        super().__init__(timeout=120.0)
        self.rewards_service = rewards_service
        self.user_id = user_id
        self.player_name = player_name

    @discord.ui.button(label="Hit", emoji="🃏", style=discord.ButtonStyle.primary, custom_id="bj_hit")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your blackjack table!", ephemeral=True)
            return

        try:
            game = self.rewards_service.hit_blackjack(self.user_id)
            if game.status != "IN_PROGRESS":
                for child in self.children:
                    child.disabled = True  # type: ignore
                self.stop()
            embed = build_blackjack_embed(game, self.player_name)
            await interaction.response.edit_message(embed=embed, view=self if game.status == "IN_PROGRESS" else None)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Stand", emoji="🛑", style=discord.ButtonStyle.secondary, custom_id="bj_stand")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your blackjack table!", ephemeral=True)
            return

        try:
            game = self.rewards_service.stand_blackjack(self.user_id)
            for child in self.children:
                child.disabled = True  # type: ignore
            self.stop()
            embed = build_blackjack_embed(game, self.player_name)
            await interaction.response.edit_message(embed=embed, view=None)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Double Down", emoji="✌️", style=discord.ButtonStyle.success, custom_id="bj_double")
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your blackjack table!", ephemeral=True)
            return

        try:
            game = self.rewards_service.double_down_blackjack(self.user_id)
            for child in self.children:
                child.disabled = True  # type: ignore
            self.stop()
            embed = build_blackjack_embed(game, self.player_name)
            await interaction.response.edit_message(embed=embed, view=None)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


def build_highlow_embed(game: HighLowGame, player_name: str) -> discord.Embed:
    """Build rich embed for High-Low streak game."""
    pot_payout = int(game.wager * game.current_multiplier)
    if game.status in ("IN_PROGRESS", "WON_ROUND"):
        color = discord.Color.purple()
        title = f"📈 High-Low Streak — Round {game.streak + 1}"
    elif game.status == "CASHED_OUT":
        color = discord.Color.green()
        title = "💰 High-Low — Cashed Out!"
    else:
        color = discord.Color.red()
        title = "💥 High-Low — Busted!"

    embed = discord.Embed(
        title=title,
        description=(
            f"👤 **Player:** {player_name}\n"
            f"💰 **Initial Wager:** `{game.wager:,} pts`\n\n"
            f"{game.message}"
        ),
        color=color,
    )
    embed.add_field(name="Current Card", value=f"# `{game.current_card}`", inline=True)
    embed.add_field(name="Streak & Multiplier", value=f"🔥 **{game.streak} Streak**\n⚡ **{game.current_multiplier:.1f}x**", inline=True)
    embed.add_field(name="Current Pot Value", value=f"💎 **{pot_payout:,} pts**", inline=True)

    if game.status != "IN_PROGRESS" and game.status != "WON_ROUND":
        embed.add_field(name="New Wallet Balance", value=f"**{game.new_balance:,} Uno Points**", inline=False)

    embed.set_footer(text="Guess Higher or Lower • Cash out anytime after 1 win • Max 6 streak = 30x!")
    return embed


class HighLowView(discord.ui.View):
    """Interactive Discord UI view for High-Low Card Streak."""

    def __init__(self, rewards_service: RewardsDBService, user_id: int, player_name: str):
        super().__init__(timeout=120.0)
        self.rewards_service = rewards_service
        self.user_id = user_id
        self.player_name = player_name

    @discord.ui.button(label="Higher", emoji="🔼", style=discord.ButtonStyle.primary, custom_id="hl_higher")
    async def higher(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your High-Low game!", ephemeral=True)
            return

        try:
            game = self.rewards_service.guess_highlow(self.user_id, guess="higher")
            if game.status not in ("IN_PROGRESS", "WON_ROUND"):
                self.stop()
            embed = build_highlow_embed(game, self.player_name)
            await interaction.response.edit_message(embed=embed, view=self if game.status in ("IN_PROGRESS", "WON_ROUND") else None)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Lower", emoji="🔽", style=discord.ButtonStyle.primary, custom_id="hl_lower")
    async def lower(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your High-Low game!", ephemeral=True)
            return

        try:
            game = self.rewards_service.guess_highlow(self.user_id, guess="lower")
            if game.status not in ("IN_PROGRESS", "WON_ROUND"):
                self.stop()
            embed = build_highlow_embed(game, self.player_name)
            await interaction.response.edit_message(embed=embed, view=self if game.status in ("IN_PROGRESS", "WON_ROUND") else None)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Cash Out", emoji="💰", style=discord.ButtonStyle.success, custom_id="hl_cashout")
    async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your High-Low game!", ephemeral=True)
            return

        try:
            game = self.rewards_service.cashout_highlow(self.user_id)
            self.stop()
            embed = build_highlow_embed(game, self.player_name)
            await interaction.response.edit_message(embed=embed, view=None)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class DoubleOrNothingView(discord.ui.View):
    """Instant rematch button for loser of a duel."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        loser: discord.Member | discord.User,
        winner: discord.Member | discord.User,
        previous_wager: int,
        mode: str = "dice",
    ):
        super().__init__(timeout=20.0)
        self.rewards_service = rewards_service
        self.loser = loser
        self.winner = winner
        self.new_wager = previous_wager * 2
        self.mode = mode

    @discord.ui.button(label="🔁 Double or Nothing Rematch!", style=discord.ButtonStyle.danger, custom_id="rematch_btn")
    async def rematch(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.loser.id:
            await interaction.response.send_message("❌ Only the defeated duelist can request a Double-or-Nothing rematch!", ephemeral=True)
            return

        l_bal = self.rewards_service.get_balance(self.loser.id)
        w_bal = self.rewards_service.get_balance(self.winner.id)
        if l_bal < self.new_wager:
            await interaction.response.send_message(f"❌ You need at least `{self.new_wager:,} pts` for a double-or-nothing rematch (you have `{l_bal:,} pts`)!", ephemeral=True)
            return
        if w_bal < self.new_wager:
            await interaction.response.send_message(f"❌ {self.winner.display_name} does not have `{self.new_wager:,} pts` in their wallet!", ephemeral=True)
            return

        self.stop()
        embed = discord.Embed(
            title="⚔️ DOUBLE OR NOTHING DUEL REMATCH!",
            description=(
                f"**{self.loser.mention}** has doubled the stakes against **{self.winner.mention}**!\n\n"
                f"💰 **New Wager per Player:** `{self.new_wager:,} Uno Points`\n"
                f"🏆 **Total Rematch Pot:** `{self.new_wager * 2:,} Uno Points`\n"
                f"🎮 **Game Mode:** `{self.mode.upper()}`\n\n"
                f"{self.winner.mention}, click **[ Accept Duel ]** to clash again!"
            ),
            color=discord.Color.red(),
        )
        view = DuelAcceptView(self.rewards_service, self.loser, self.winner, self.new_wager, mode=self.mode)
        await interaction.response.send_message(content=f"{self.winner.mention}", embed=embed, view=view)


class RPSDuelView(discord.ui.View):
    """Interactive simultaneous Rock-Paper-Scissors selection UI."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        challenger: discord.Member | discord.User,
        target: discord.Member | discord.User,
        wager: int,
    ):
        super().__init__(timeout=60.0)
        self.rewards_service = rewards_service
        self.challenger = challenger
        self.target = target
        self.wager = wager
        self.c_choice: Optional[str] = None
        self.t_choice: Optional[str] = None

    async def _handle_choice(self, interaction: discord.Interaction, choice: str) -> None:
        user_id = interaction.user.id
        if user_id not in (self.challenger.id, self.target.id):
            await interaction.response.send_message("❌ You are not part of this duel!", ephemeral=True)
            return

        choice_names = {"rock": "🪨 Rock", "paper": "📄 Paper", "scissors": "✂️ Scissors"}

        if user_id == self.challenger.id:
            if self.c_choice is not None:
                await interaction.response.send_message("❌ You have already submitted your move!", ephemeral=True)
                return
            self.c_choice = choice
        elif user_id == self.target.id:
            if self.t_choice is not None:
                await interaction.response.send_message("❌ You have already submitted your move!", ephemeral=True)
                return
            self.t_choice = choice

        await interaction.response.send_message(f"✅ You chose **{choice_names[choice]}**! Waiting for your opponent...", ephemeral=True)

        if self.c_choice is not None and self.t_choice is not None:
            self.stop()
            try:
                res = self.rewards_service.resolve_rps_duel(
                    self.challenger.id, self.target.id, self.c_choice, self.t_choice, self.wager
                )
                if res.is_tie:
                    embed = discord.Embed(
                        title="🤝 Rock-Paper-Scissors — It's a Tie!",
                        description=(
                            f"**{self.challenger.display_name}**: {res.challenger_choice}\n"
                            f"**{self.target.display_name}**: {res.target_choice}\n\n"
                            f"Both players chose the same move! Wagers of `{self.wager:,} pts` refunded."
                        ),
                        color=discord.Color.gold(),
                    )
                    await interaction.message.edit(embed=embed, view=None)
                else:
                    winner = self.challenger if res.winner_id == self.challenger.id else self.target
                    loser = self.target if res.winner_id == self.challenger.id else self.challenger
                    w_choice = res.challenger_choice if res.winner_id == self.challenger.id else res.target_choice
                    l_choice = res.target_choice if res.winner_id == self.challenger.id else res.challenger_choice

                    desc = (
                        f"👑 **{winner.display_name}** ({w_choice}) defeated **{loser.display_name}** ({l_choice})!\n\n"
                        f"🏆 **{winner.mention} won the pot of `{res.pot_won:,} Uno Points`!**\n"
                    )
                    if res.bounty_won > 0:
                        desc += f"\n🎯 **BOUNTY CLAIMED!** Claimed an additional **+{res.bounty_won:,} pts** bounty on {loser.display_name}!"
                    if res.perk_msg:
                        desc += f"\n{res.perk_msg}"

                    embed = discord.Embed(
                        title=f"👑 {winner.display_name} WON THE RPS DUEL!",
                        description=desc,
                        color=discord.Color.green(),
                    )
                    rematch_view = DoubleOrNothingView(self.rewards_service, loser, winner, self.wager, mode="rps")
                    await interaction.message.edit(embed=embed, view=rematch_view)
            except RewardsError as e:
                await interaction.message.edit(content=f"❌ Error resolving duel: {e}", embed=None, view=None)

    @discord.ui.button(label="Rock", emoji="🪨", style=discord.ButtonStyle.primary, custom_id="rps_rock")
    async def btn_rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "rock")

    @discord.ui.button(label="Paper", emoji="📄", style=discord.ButtonStyle.success, custom_id="rps_paper")
    async def btn_paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "paper")

    @discord.ui.button(label="Scissors", emoji="✂️", style=discord.ButtonStyle.danger, custom_id="rps_scissors")
    async def btn_scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "scissors")


class RouletteDuelView(discord.ui.View):
    """Interactive Uno Russian Roulette chamber UI."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        challenger: discord.Member | discord.User,
        target: discord.Member | discord.User,
        wager: int,
    ):
        super().__init__(timeout=60.0)
        self.rewards_service = rewards_service
        self.challenger = challenger
        self.target = target
        self.wager = wager
        self.game = self.rewards_service.start_roulette_game(challenger.id, target.id, wager)

    def _render_embed(self) -> discord.Embed:
        curr_player = self.challenger if self.game.current_turn_id == self.challenger.id else self.target
        chamber_display = " ".join("🎴" if i < self.game.current_index else "⚪" for i in range(6))

        embed = discord.Embed(
            title="🃏 Uno Russian Roulette — Chamber Deck",
            description=(
                f"**Challenger:** {self.challenger.mention}\n"
                f"**Target:** {self.target.mention}\n"
                f"💰 **Total Pot:** `{self.wager * 2:,} Uno Points`\n\n"
                f"Deck Chamber: `{chamber_display}` (Card {self.game.current_index + 1}/6)\n\n"
                f"👉 **It is {curr_player.mention}'s turn to draw a card!**"
            ),
            color=discord.Color.purple(),
        )
        embed.set_footer(text="5 Safe Cards • 1 Wild Draw 4 Bomb 💥 • Click below to draw")
        return embed

    @discord.ui.button(label="Draw Card / Pull Trigger", emoji="🎴", style=discord.ButtonStyle.danger, custom_id="roulette_draw")
    async def draw_card(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.game.current_turn_id:
            await interaction.response.send_message("❌ It is not your turn to draw!", ephemeral=True)
            return

        opp_id = self.target.id if self.game.current_turn_id == self.challenger.id else self.challenger.id
        try:
            game = self.rewards_service.pull_roulette_trigger(interaction.user.id, opp_id)
            if game.is_over:
                self.stop()
                winner = self.challenger if game.winner_id == self.challenger.id else self.target
                loser = self.target if game.winner_id == self.challenger.id else self.challenger

                desc = (
                    f"💥 **BOOM! {loser.mention} drew the Wild Draw 4 Bomb!**\n\n"
                    f"🏆 **{winner.mention} survived and won the pot of `{game.pot_won:,} Uno Points`!**\n"
                )
                if game.bounty_won > 0:
                    desc += f"\n🎯 **BOUNTY CLAIMED!** Claimed an additional **+{game.bounty_won:,} pts** bounty on {loser.display_name}!"
                if game.perk_msg:
                    desc += f"\n{game.perk_msg}"

                embed = discord.Embed(
                    title=f"💥 EXPLOSION! {winner.display_name} WINS ROULETTE!",
                    description=desc,
                    color=discord.Color.dark_red(),
                )
                rematch_view = DoubleOrNothingView(self.rewards_service, loser, winner, self.wager, mode="roulette")
                await interaction.response.edit_message(embed=embed, view=rematch_view)
            else:
                embed = self._render_embed()
                await interaction.response.edit_message(embed=embed, view=self)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class RPGDuelView(discord.ui.View):
    """Interactive Turn-Based 100 HP RPG Combat View."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        challenger: discord.Member | discord.User,
        target: discord.Member | discord.User,
        wager: int,
    ):
        super().__init__(timeout=90.0)
        self.rewards_service = rewards_service
        self.challenger = challenger
        self.target = target
        self.wager = wager
        self.game = self.rewards_service.start_rpg_game(challenger.id, target.id, wager)

    def _render_embed(self) -> discord.Embed:
        c_bars = int(self.game.c_hp / 10)
        t_bars = int(self.game.t_hp / 10)
        c_bar_str = "█" * c_bars + "░" * (10 - c_bars)
        t_bar_str = "█" * t_bars + "░" * (10 - t_bars)

        log_str = "\n".join(self.game.last_round_log) if self.game.last_round_log else "⚔️ *Round 1 has commenced! Select your combat action below.*"

        embed = discord.Embed(
            title=f"⚔️ RPG Arena Duel — Round {self.game.turn_number}",
            description=(
                f"**{self.challenger.display_name}**: `[{c_bar_str}]` **{self.game.c_hp}/100 HP**\n"
                f"**{self.target.display_name}**: `[{t_bar_str}]` **{self.game.t_hp}/100 HP**\n\n"
                f"💰 **Total Pot:** `{self.wager * 2:,} Uno Points`\n\n"
                f"📜 **Combat Log:**\n{log_str}\n\n"
                "👉 Both combatants must pick an action below!"
            ),
            color=discord.Color.red(),
        )
        return embed

    async def _handle_action(self, interaction: discord.Interaction, action: str) -> None:
        user_id = interaction.user.id
        if user_id not in (self.challenger.id, self.target.id):
            await interaction.response.send_message("❌ You are not a combatant in this RPG duel!", ephemeral=True)
            return

        opp_id = self.target.id if user_id == self.challenger.id else self.challenger.id
        try:
            game = self.rewards_service.submit_rpg_action(user_id, opp_id, action)
            act_names = {"strike": "⚔️ Strike", "block": "🛡️ Parry/Block", "ultimate": "⚡ Ultimate"}
            await interaction.response.send_message(f"✅ You selected **{act_names[action]}**! Waiting for opponent...", ephemeral=True)

            if game.is_over:
                self.stop()
                if game.winner_id is None:
                    embed = discord.Embed(
                        title="🤝 Mutual KO — RPG Duel Tie!",
                        description=f"Both combatants collapsed simultaneously! Wagers of `{self.wager:,} pts` refunded.",
                        color=discord.Color.gold(),
                    )
                    await interaction.message.edit(embed=embed, view=None)
                else:
                    winner = self.challenger if game.winner_id == self.challenger.id else self.target
                    loser = self.target if game.winner_id == self.challenger.id else self.challenger

                    desc = (
                        f"👑 **{winner.mention} emerged victorious in the RPG Arena!**\n\n"
                        f"🏆 **Winner takes the entire pot of `{game.pot_won:,} Uno Points`!**\n"
                    )
                    if game.bounty_won > 0:
                        desc += f"\n🎯 **BOUNTY CLAIMED!** Claimed an additional **+{game.bounty_won:,} pts** bounty on {loser.display_name}!"
                    if game.perk_msg:
                        desc += f"\n{game.perk_msg}"

                    embed = discord.Embed(
                        title=f"👑 {winner.display_name} WON THE RPG ARENA!",
                        description=desc,
                        color=discord.Color.green(),
                    )
                    rematch_view = DoubleOrNothingView(self.rewards_service, loser, winner, self.wager, mode="rpg")
                    await interaction.message.edit(embed=embed, view=rematch_view)

            elif len(game.last_round_log) > 0:
                embed = self._render_embed()
                await interaction.message.edit(embed=embed, view=self)

        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Strike (20-35 DMG)", emoji="⚔️", style=discord.ButtonStyle.primary, custom_id="rpg_strike")
    async def btn_strike(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_action(interaction, "strike")

    @discord.ui.button(label="Parry/Block", emoji="🛡️", style=discord.ButtonStyle.secondary, custom_id="rpg_block")
    async def btn_block(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_action(interaction, "block")

    @discord.ui.button(label="Ultimate (55 DMG / 50% Hit)", emoji="⚡", style=discord.ButtonStyle.danger, custom_id="rpg_ultimate")
    async def btn_ultimate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_action(interaction, "ultimate")


class DuelAcceptView(discord.ui.View):
    """Interactive confirmation view for 1v1 PvP Wager Duels."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        challenger: discord.Member | discord.User,
        target: discord.Member | discord.User,
        wager: int,
        mode: str = "dice",
    ):
        super().__init__(timeout=60.0)
        self.rewards_service = rewards_service
        self.challenger = challenger
        self.target = target
        self.wager = wager
        self.mode = mode.lower().strip()

    @discord.ui.button(label="Accept Duel", emoji="⚔️", style=discord.ButtonStyle.danger, custom_id="duel_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(f"❌ Only {self.target.mention} can accept this duel!", ephemeral=True)
            return

        self.stop()
        if self.mode == "rps":
            rps_view = RPSDuelView(self.rewards_service, self.challenger, self.target, self.wager)
            embed = discord.Embed(
                title="✂️ Rock-Paper-Scissors Duel — Clash of Minds!",
                description=(
                    f"**Challenger:** {self.challenger.mention}\n"
                    f"**Target:** {self.target.mention}\n"
                    f"💰 **Wager per Player:** `{self.wager:,} Uno Points`\n\n"
                    "Both combatants, click your secret move button below! Moves remain hidden until both have submitted."
                ),
                color=discord.Color.blue(),
            )
            embed.set_footer(text="Rock beats Scissors • Scissors beats Paper • Paper beats Rock")
            await interaction.response.edit_message(embed=embed, view=rps_view)

        elif self.mode == "roulette":
            roulette_view = RouletteDuelView(self.rewards_service, self.challenger, self.target, self.wager)
            embed = roulette_view._render_embed()
            await interaction.response.edit_message(embed=embed, view=roulette_view)

        elif self.mode == "rpg":
            rpg_view = RPGDuelView(self.rewards_service, self.challenger, self.target, self.wager)
            embed = rpg_view._render_embed()
            await interaction.response.edit_message(embed=embed, view=rpg_view)

        else:
            try:
                res = self.rewards_service.resolve_duel(self.challenger.id, self.target.id, self.wager)
                if res.is_tie:
                    title = "🤝 1v1 Duel — Draw / Tie!"
                    desc = (
                        f"**{self.challenger.display_name}** rolled `{res.challenger_roll}`\n"
                        f"**{self.target.display_name}** rolled `{res.target_roll}`\n\n"
                        f"It's a dead heat! Both wagers of `{self.wager:,} pts` were refunded."
                    )
                    color = discord.Color.gold()
                    embed = discord.Embed(title=title, description=desc, color=color)
                    await interaction.response.edit_message(embed=embed, view=None)
                else:
                    winner = self.challenger if res.winner_id == self.challenger.id else self.target
                    loser = self.target if res.winner_id == self.challenger.id else self.challenger
                    w_roll = res.challenger_roll if res.winner_id == self.challenger.id else res.target_roll
                    l_roll = res.target_roll if res.winner_id == self.challenger.id else res.challenger_roll

                    title = f"👑 {winner.display_name} WON THE DUEL!"
                    desc = (
                        f"⚔️ **{winner.display_name}** rolled 🎲 **`{w_roll}`**\n"
                        f"💀 **{loser.display_name}** rolled 🎲 `{l_roll}`\n\n"
                        f"🏆 **{winner.mention} took the entire pot of `{res.pot_won:,} Uno Points`!**"
                    )
                    if res.bounty_won > 0:
                        desc += f"\n\n🎯 **BOUNTY CLAIMED!** Claimed an additional **+{res.bounty_won:,} pts** bounty on {loser.display_name}!"
                    if res.pet_perk_activated:
                        desc += f"\n\n🐾 {res.pet_perk_activated}"

                    color = discord.Color.green()
                    embed = discord.Embed(title=title, description=desc, color=color)
                    embed.set_footer(text="1v1 High-Stakes Duel • Roll range 1-100")
                    rematch_view = DoubleOrNothingView(self.rewards_service, loser, winner, self.wager, mode="dice")
                    await interaction.response.edit_message(embed=embed, view=rematch_view)

            except RewardsError as e:
                await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.secondary, custom_id="duel_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id not in (self.challenger.id, self.target.id):
            await interaction.response.send_message("❌ This is not your duel challenge!", ephemeral=True)
            return

        self.stop()
        await interaction.response.edit_message(
            content=f"🏳️ Duel between {self.challenger.mention} and {self.target.mention} was cancelled.",
            embed=None,
            view=None,
        )


def build_pet_embed(pet: Optional[PetRecord], owner_name: str, all_pets: list[PetRecord]) -> tuple[discord.Embed, Optional[discord.File]]:
    """Build a rich embed showcasing the user's active pet companion with attached pixel art sprite."""
    if not pet:
        embed = discord.Embed(
            title=f"🐾 Pet Shelter — {owner_name}'s Companions",
            description=(
                f"**{owner_name}** does not have an active pet companion equipped yet!\n\n"
                "Adopt a loyal companion from the **`/shop`** (🐾 Pet Shelter tab) or with **`/pet adopt`**!\n"
                "Companions grant permanent passive economic perks, daily care rewards, and custom profile aesthetics!"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Browse companions with /shop or adopt with /pet adopt <species> • /pet guide")
        return embed, None

    embed = discord.Embed(
        title=f"🐾 {pet.nickname} — {owner_name}'s Companion",
        description=(
            f"**Species:** {pet.display_name}\n"
            f"🌟 **Perk:** **{pet.perk_title}**\n"
            f"*{pet.perk_desc}*\n\n"
            f"💬 *\"{pet.quote}\"*"
        ),
        color=discord.Color.teal(),
    )

    bar_len = 10
    filled = max(1, int(pet.happiness / 100 * bar_len))
    hp_bar = "💖" * filled + "🖤" * (bar_len - filled)
    embed.add_field(name=f"Happiness ({pet.happiness}%)", value=hp_bar, inline=True)

    xp_needed = pet.level * 50
    embed.add_field(name="Level & XP", value=f"⭐ **Level {pet.level}**\n({pet.xp}/{xp_needed} XP)", inline=True)
    embed.add_field(name="Collection", value=f"🏠 **{len(all_pets)}** Pet(s) Owned", inline=True)

    file_attachment = None
    pet_img_path = resolve_pet_image_path(pet.image_file)
    if pet_img_path:
        file_attachment = discord.File(str(pet_img_path), filename=pet.image_file)
        embed.set_thumbnail(url=f"attachment://{pet.image_file}")

    embed.set_footer(text="Feed/Pet companion • Switch active pet with dropdown • /pet guide")
    return embed, file_attachment


def build_pet_store_embed(
    rewards_service: RewardsDBService,
    user_id: int,
    selected_pet_id: str,
    user_name: str,
) -> tuple[discord.Embed, Optional[discord.File]]:
    """Build a minimal, clean, professional Pet Shelter & Companion Embed."""
    user = rewards_service.get_or_create_user(user_id)
    user_pets = rewards_service.get_user_pets(user_id)
    owned_dict = {p.pet_id: p for p in user_pets}
    pet_info = PET_CATALOG.get(selected_pet_id, PET_CATALOG["tuxedo_cat"])

    # Clean Title without repetitive species names
    if selected_pet_id in owned_dict:
        owned_pet = owned_dict[selected_pet_id]
        if owned_pet.nickname and owned_pet.nickname != pet_info["name"]:
            embed_title = f"{pet_info['name']} ({owned_pet.nickname})"
        else:
            embed_title = f"{pet_info['name']}"
    else:
        embed_title = f"{pet_info['name']}"

    perk_desc = pet_info.get("perk_desc", "")
    embed = discord.Embed(
        title=embed_title,
        description=f"*{pet_info.get('title', 'Companion')}*\n{perk_desc}",
        color=discord.Color.from_rgb(47, 49, 54),
    )

    # Status / Price field (compact)
    if selected_pet_id in owned_dict:
        owned_pet = owned_dict[selected_pet_id]
        if owned_pet.is_active:
            status_text = f"Equipped (Level {owned_pet.level} • {owned_pet.happiness}% Mood)"
        else:
            status_text = f"In Shelter (Level {owned_pet.level})"
        embed.add_field(name="Status", value=status_text, inline=True)
    else:
        if not user.has_claimed_starter and selected_pet_id in ("tuxedo_cat", "golden_dog", "brown_bunny"):
            price_text = "Free Starter (0 pts)"
        else:
            price_text = f"{pet_info['cost']:,} pts (Wallet: {user.points:,})"
        embed.add_field(name="Price", value=price_text, inline=True)

    # Combat Perk (compact)
    duel_perk = pet_info.get("duel_perk", "")
    if duel_perk:
        embed.add_field(name="Combat Perk", value=duel_perk, inline=True)

    # Friendly & Hostile relations (clean Dank Memer style)
    friendly = pet_info.get("friendly_with", "")
    rival = pet_info.get("rival_with", "")
    if friendly:
        embed.add_field(name="Friendly with:", value=friendly, inline=False)
    if rival:
        embed.add_field(name="Hostile with:", value=rival, inline=False)

    # Image sprite
    file_attachment = None
    pet_img_path = resolve_pet_image_path(pet_info.get("image_file"))
    if pet_img_path:
        file_attachment = discord.File(str(pet_img_path), filename=pet_info["image_file"])
        embed.set_thumbnail(url=f"attachment://{pet_info['image_file']}")

    embed.set_footer(text=f"Pet Shelter • {len(user_pets)}/14 Owned")
    return embed, file_attachment


class PetCareButton(discord.ui.Button):
    """Button to feed or cuddle active companion."""

    def __init__(self, action: str, label: str, emoji: str, style: discord.ButtonStyle = discord.ButtonStyle.primary):
        super().__init__(label=label, emoji=emoji, style=style, custom_id=f"pet_care_{action}")
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ This is not your pet companion!", ephemeral=True)
            return

        try:
            res = view.rewards_service.interact_pet(interaction.user.id, action=self.action)
            if hasattr(view, "selected_pet_id"):
                view.update_components()
                embed, file_att = build_pet_store_embed(
                    view.rewards_service, view.user_id, view.selected_pet_id, interaction.user.display_name
                )
            else:
                updated_pet = view.rewards_service.get_active_pet(interaction.user.id)
                all_pets = view.rewards_service.get_user_pets(interaction.user.id)
                embed, file_att = build_pet_embed(updated_pet, interaction.user.display_name, all_pets)
                if hasattr(view, "update_components"):
                    view.update_components(all_pets)

            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=view)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=view)
            await interaction.followup.send(res.message, ephemeral=True)

        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class PetSwitchSelect(discord.ui.Select):
    """Dropdown to switch between owned companions."""

    def __init__(self, user_pets: list[PetRecord]):
        options = [
            discord.SelectOption(
                label=f"{p.nickname} ({p.display_name})",
                value=p.pet_id,
                description=f"Level {p.level} • {p.perk_title}"[:95],
                default=p.is_active,
            )
            for p in user_pets
        ]
        super().__init__(
            placeholder="🔄 Switch active companion...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="pet_switch_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ This is not your pet companion!", ephemeral=True)
            return

        pet_id = self.values[0] if self.values else "tuxedo_cat"
        try:
            switched = view.rewards_service.switch_active_pet(interaction.user.id, pet_id)
            all_pets = view.rewards_service.get_user_pets(interaction.user.id)
            embed, file_att = build_pet_embed(switched, interaction.user.display_name, all_pets)
            if hasattr(view, "update_components"):
                view.update_components(all_pets)

            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=view)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=view)
            await interaction.followup.send(
                f"✨ Switched active companion to **{switched.nickname}** ({switched.display_name})!\n"
                f"Active Perk: **{switched.perk_title}**",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class PetGuideButton(discord.ui.Button):
    """Button to view the pet companion handbook."""

    def __init__(self):
        super().__init__(label="Companion Guide", emoji="📖", style=discord.ButtonStyle.secondary, custom_id="pet_guide_btn")

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = build_pet_guide_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PetStoreSelect(discord.ui.Select):
    """Dropdown menu to browse any pet in the catalog."""

    def __init__(self, rewards_service: RewardsDBService, user_id: int, selected_pet_id: str):
        user_pets = rewards_service.get_user_pets(user_id)
        owned_ids = {p.pet_id: p for p in user_pets}
        user = rewards_service.get_or_create_user(user_id)

        options = []
        for pid, pdata in PET_CATALOG.items():
            if pid in owned_ids:
                p_rec = owned_ids[pid]
                desc = f"Active (Lvl {p_rec.level})" if p_rec.is_active else f"Owned (Lvl {p_rec.level})"
            elif not user.has_claimed_starter and pid in ("tuxedo_cat", "golden_dog", "brown_bunny"):
                desc = "Free Starter Choice"
            else:
                desc = f"{pdata['cost']:,} pts"

            options.append(
                discord.SelectOption(
                    label=f"{pdata['name']}",
                    value=pid,
                    description=desc,
                    default=(pid == selected_pet_id),
                )
            )

        super().__init__(
            placeholder="Browse & select a pet companion...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="pet_store_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "PetStoreView" = self.view  # type: ignore
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ This pet menu is not for you!", ephemeral=True)
            return

        if not self.values:
            return

        view.selected_pet_id = self.values[0]
        view.update_components()
        embed, file_att = build_pet_store_embed(
            view.rewards_service, view.user_id, view.selected_pet_id, interaction.user.display_name
        )
        if file_att:
            await interaction.response.edit_message(embed=embed, attachments=[file_att], view=view)
        else:
            await interaction.response.edit_message(embed=embed, attachments=[], view=view)


class PetStoreView(discord.ui.View):
    """Interactive, full-featured Pet Shelter & Companion Management Dashboard."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        user_id: int,
        selected_pet_id: Optional[Union[str, list[PetRecord]]] = None,
        user_pets: Optional[list[PetRecord]] = None,
    ):
        super().__init__(timeout=180.0)
        self.rewards_service = rewards_service
        self.user_id = user_id

        if isinstance(selected_pet_id, list):
            pets_list = selected_pet_id
            sel_id = None
        elif isinstance(selected_pet_id, str):
            pets_list = user_pets
            sel_id = selected_pet_id
        else:
            pets_list = user_pets
            sel_id = None

        if not sel_id:
            active_pet = rewards_service.get_active_pet(user_id)
            if active_pet:
                self.selected_pet_id = active_pet.pet_id
            else:
                pets = pets_list if pets_list is not None else rewards_service.get_user_pets(user_id)
                self.selected_pet_id = pets[0].pet_id if pets else "tuxedo_cat"
        else:
            self.selected_pet_id = sel_id

        self.update_components(pets_list)

    def update_components(self, user_pets: Optional[list[PetRecord]] = None) -> None:
        self.clear_items()
        # Row 0: Full Pet Catalog Select Menu
        self.add_item(PetStoreSelect(self.rewards_service, self.user_id, self.selected_pet_id))

        user = self.rewards_service.get_or_create_user(self.user_id)
        pets = user_pets if user_pets is not None else self.rewards_service.get_user_pets(self.user_id)
        owned_dict = {p.pet_id: p for p in pets}
        pet_info = PET_CATALOG.get(self.selected_pet_id, PET_CATALOG["tuxedo_cat"])

        # Row 1: Action buttons based on ownership state
        if self.selected_pet_id not in owned_dict:
            if not user.has_claimed_starter and self.selected_pet_id in ("tuxedo_cat", "golden_dog", "brown_bunny"):
                btn_starter = discord.ui.Button(
                    label="Claim Starter",
                    style=discord.ButtonStyle.success,
                    custom_id="btn_adopt_starter",
                )
                btn_starter.callback = self._on_adopt_starter
                self.add_item(btn_starter)
            else:
                cost = pet_info["cost"]
                btn_adopt = discord.ui.Button(
                    label=f"Buy ({cost:,} pts)",
                    style=discord.ButtonStyle.success,
                    custom_id="btn_adopt_pet",
                )
                btn_adopt.callback = self._on_adopt_pet
                self.add_item(btn_adopt)
        else:
            owned_pet = owned_dict[self.selected_pet_id]
            if not owned_pet.is_active:
                btn_equip = discord.ui.Button(
                    label="Equip Companion",
                    style=discord.ButtonStyle.primary,
                    custom_id="btn_equip_pet",
                )
                btn_equip.callback = self._on_equip_pet
                self.add_item(btn_equip)
            else:
                self.add_item(PetCareButton("feed", "Feed (+15 XP)", "🍖", discord.ButtonStyle.primary))
                self.add_item(PetCareButton("pet", "Cuddle", "💖", discord.ButtonStyle.secondary))

            btn_sell = discord.ui.Button(
                label="Sell",
                style=discord.ButtonStyle.secondary,
                custom_id="btn_sell_pet",
            )
            btn_sell.callback = self._on_sell_pet
            self.add_item(btn_sell)

        self.add_item(PetGuideButton())

    async def _on_adopt_starter(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This menu is not for you!", ephemeral=True)
            return

        try:
            pet_rec = self.rewards_service.claim_starter_pet(self.user_id, self.selected_pet_id)
            self.update_components()
            embed, file_att = build_pet_store_embed(
                self.rewards_service, self.user_id, self.selected_pet_id, interaction.user.display_name
            )
            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=self)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=self)
            await interaction.followup.send(
                f"🎉 **Welcome {pet_rec.nickname} ({pet_rec.display_name})!** You adopted your FREE starter companion!\n"
                f"🌟 Active Perk: **{pet_rec.perk_title}**",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    async def _on_adopt_pet(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This menu is not for you!", ephemeral=True)
            return

        try:
            res = self.rewards_service.adopt_pet(self.user_id, self.selected_pet_id)
            self.update_components()
            embed, file_att = build_pet_store_embed(
                self.rewards_service, self.user_id, self.selected_pet_id, interaction.user.display_name
            )
            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=self)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=self)
            await interaction.followup.send(
                f"🎉 **Congratulations!** You adopted **{res.nickname}** ({res.display_name})!\n"
                f"🌟 Active Perk: **{res.perk_title}**",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    async def _on_equip_pet(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This menu is not for you!", ephemeral=True)
            return

        try:
            switched = self.rewards_service.switch_active_pet(self.user_id, self.selected_pet_id)
            self.update_components()
            embed, file_att = build_pet_store_embed(
                self.rewards_service, self.user_id, self.selected_pet_id, interaction.user.display_name
            )
            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=self)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=self)
            await interaction.followup.send(
                f"✨ Switched active companion to **{switched.nickname}** ({switched.display_name})!\n"
                f"Active Perk: **{switched.perk_title}**",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    async def _on_feed_pet(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This menu is not for you!", ephemeral=True)
            return

        try:
            res = self.rewards_service.interact_pet(self.user_id, action="feed")
            self.update_components()
            embed, file_att = build_pet_store_embed(
                self.rewards_service, self.user_id, self.selected_pet_id, interaction.user.display_name
            )
            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=self)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=self)
            await interaction.followup.send(res.message, ephemeral=True)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    async def _on_cuddle_pet(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This menu is not for you!", ephemeral=True)
            return

        try:
            res = self.rewards_service.interact_pet(self.user_id, action="pet")
            self.update_components()
            embed, file_att = build_pet_store_embed(
                self.rewards_service, self.user_id, self.selected_pet_id, interaction.user.display_name
            )
            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=self)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=self)
            await interaction.followup.send(res.message, ephemeral=True)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    async def _on_sell_pet(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This menu is not for you!", ephemeral=True)
            return

        try:
            res = self.rewards_service.sell_pet(self.user_id, self.selected_pet_id)
            active_pet = self.rewards_service.get_active_pet(self.user_id)
            self.selected_pet_id = active_pet.pet_id if active_pet else "tuxedo_cat"
            self.update_components()
            embed, file_att = build_pet_store_embed(
                self.rewards_service, self.user_id, self.selected_pet_id, interaction.user.display_name
            )
            if file_att:
                await interaction.response.edit_message(embed=embed, attachments=[file_att], view=self)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[], view=self)
            await interaction.followup.send(
                f"🪙 Released **{res['nickname']}** ({res['pet_name']}) back to shelter! Refunded **`+{res['refund_amount']:,} Uno Points`** (New Wallet: `{res['new_balance']:,} pts`)",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


# Compatibility alias
PetView = PetStoreView


def build_shop_embed(rewards_service: RewardsDBService, user_id: int, category: str = "home") -> discord.Embed:
    """Build a clean, structured, and interactive embed for the Uno Rewards Shop."""
    user_points = rewards_service.get_balance(user_id)

    if category == "home":
        embed = discord.Embed(
            title="🏪 BSCS 1-4 — Uno Rewards Shop",
            description=(
                f"💳 **Your Wallet:** `{user_points:,} Uno Points`\n\n"
                "Welcome to the **Uno Student Rewards Shop**! Navigate categories using the buttons below, "
                "or purchase directly with the **Quick-Buy dropdown**."
            ),
            color=discord.Color.gold(),
        )

        drop_info = rewards_service.get_featured_pet()
        feat_p = drop_info["pet_info"]
        featured_text = (
            f"• **⭐ 3-Day Drop Spotlight: {feat_p['name']}** (`{feat_p['cost']:,} pts`) — *{feat_p['perk_title']} (Rotation: <t:{drop_info['next_drop_timestamp']}:R>)*\n"
            "• **🔄 Uno Reverse Card** (`180 pts`) — *Passive trap! Counter-steals 40%–60% from pickpockets!*\n"
            "• **📦 Mystery Gacha Box** (`150 pts`) — *Win up to 1,000 pts & exclusive High Roller badge!*\n"
            "• **☕ Intramuros Coffee Treat** (`1,200 pts`) — *₱50–₱80 Lawson/7-Eleven drink treat around PLM!*"
        )
        embed.add_field(name="⭐ Featured Items Today", value=featured_text, inline=False)

        dept_text = (
            "• 🐾 **Pet Shelter** (14 pets) — Cats (2x Daily), Dogs (Guard), Bunnies (Bet Win), Owls (Trivia), Turtles, Foxes, Axolotls\n"
            "• ⚔️ **Offense & Traps** — Pickpocket, Uno Reverse, EMP Breaker, Tax Audit\n"
            "• 🛡️ **Defense & Boosters** — 1-Week Shield, 2x Daily Booster, Coffee Bribe\n"
            "• 🎲 **Events & Gacha** — Point Airdrop, Mystery Gacha Box\n"
            "• 🎁 **Real-World & Nitro** — Coffee Treat, GCash ₱100, Free Printing, Nitro 1M"
        )
        embed.add_field(name="📂 Shop Departments (Click Buttons Below)", value=dept_text, inline=False)

        embed.add_field(
            name="🍫 Free Milestone Unlock",
            value="*Exams Survival Kit auto-unlocks for **FREE** at **3,000 Lifetime Points**!*",
            inline=False,
        )
        embed.set_footer(text="Click a department button below • Earn points with /daily, /trivia & /bet")
        return embed

    categories_meta = {
        "pets": {
            "title": "🐾 Uno Shop — Pet Shelter & Companions",
            "desc": "Adopt loyal companions for permanent passive economic buffs and profile vibes!",
            "color": discord.Color.teal(),
        },
        "offense": {
            "title": "⚔️ Uno Shop — Offense & Trap Cards",
            "desc": "High-stakes cards to steal, counter-attack, and audit wealthy classmates!",
            "color": discord.Color.red(),
        },
        "defense": {
            "title": "🛡️ Uno Shop — Defense & Booster Cards",
            "desc": "Protect your wallet from thieves and boost your daily attendance earnings!",
            "color": discord.Color.blue(),
        },
        "events": {
            "title": "🎲 Uno Shop — Community Events & Gacha",
            "desc": "Launch community care packages in chat or roll for legendary lootbox rewards!",
            "color": discord.Color.purple(),
        },
        "prizes": {
            "title": "🎁 Uno Shop — Real-World & Server Prizes",
            "desc": "Redeem real-world treats, GCash rewards, and Discord Nitro perks fulfilled by Jansen!",
            "color": discord.Color.green(),
        },
    }

    meta = categories_meta.get(category, categories_meta["offense"])
    embed = discord.Embed(
        title=meta["title"],
        description=f"💳 **Your Wallet:** `{user_points:,} Uno Points`\n*{meta['desc']}*\n",
        color=meta["color"],
    )

    if category == "pets":
        drop_info = rewards_service.get_featured_pet()
        feat_p = drop_info["pet_info"]
        embed.add_field(
            name=f"⭐ 3-Day Drop Spotlight: {feat_p['name']} (`{feat_p['cost']:,} pts`)",
            value=(
                f"🌟 **Active Perk:** *{feat_p['perk_title']}*\n"
                f"⏳ **Next Rotation:** <t:{drop_info['next_drop_timestamp']}:R> (Cycle Day {drop_info['cycle_day']}/3)\n"
                f"`/pet adopt {drop_info['pet_id']}`"
            ),
            inline=False,
        )

    items_in_cat = [
        (item_id, item)
        for item_id, item in SHOP_CATALOG.items()
        if item.get("subcategory") == category
    ]

    for item_id, item in items_in_cat:
        cost = item["cost"]
        status_tag = "✅ Affordable" if user_points >= cost else f"🔒 Need {(cost - user_points):,} more pts"
        embed.add_field(
            name=f"{item['name']} — `{cost:,} pts` [{status_tag}]",
            value=f"{item['description']}\n`/redeem {item_id}`",
            inline=False,
        )

    embed.set_footer(text="Select an item in the Quick-Buy dropdown below or use /redeem <item> • /pet guide")
    return embed


class ShopCategoryButton(discord.ui.Button):
    """Button to switch active shop category."""

    def __init__(self, category_key: str, label: str, emoji: Optional[str] = None, row: int = 0):
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            row=row,
            custom_id=f"shop_cat_{category_key}",
        )
        self.category_key = category_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "ShopView" = self.view  # type: ignore
        view.current_category = self.category_key
        view.update_components()
        embed = build_shop_embed(view.rewards_service, interaction.user.id, self.category_key)
        await interaction.response.edit_message(embed=embed, view=view)


class ShopQuickBuySelect(discord.ui.Select):
    """Quick-buy dropdown menu for shop items."""

    def __init__(self, category: str = "home", row: int = 2):
        options = []
        if category == "home":
            featured_keys = ["tuxedo_cat", "golden_dog", "brown_bunny", "uno_reverse", "gacha_box", "coffee", "nitro_1m"]
            for k in featured_keys:
                if k in SHOP_CATALOG:
                    item = SHOP_CATALOG[k]
                    options.append(
                        discord.SelectOption(
                            label=f"{item['name']} ({item['cost']:,} pts)",
                            value=k,
                            description=item["description"][:95],
                        )
                    )
        else:
            for k, item in SHOP_CATALOG.items():
                if item.get("subcategory") == category:
                    options.append(
                        discord.SelectOption(
                            label=f"{item['name']} ({item['cost']:,} pts)",
                            value=k,
                            description=item["description"][:95],
                        )
                    )

        super().__init__(
            placeholder="⚡ Quick-Buy: Select an item to purchase...",
            min_values=1,
            max_values=1,
            options=options,
            row=row,
            custom_id="shop_quick_buy",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "ShopView" = self.view  # type: ignore
        item_id = self.values[0]
        user_id = interaction.user.id
        try:
            res = view.rewards_service.record_redemption(user_id, item_id)
            new_bal = view.rewards_service.get_balance(user_id)

            if res["category"] == "consumable":
                confirm_embed = discord.Embed(
                    title="🛍️ Consumable Purchased!",
                    description=f"You purchased **{res['item_name']}** for **{res['points_spent']:,} pts**!\nItem has been added to your `/inventory`.",
                    color=discord.Color.green(),
                )
                confirm_embed.add_field(name="Remaining Balance", value=f"**{new_bal:,} pts**", inline=True)
                await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
            elif res["category"] == "pet":
                confirm_embed = discord.Embed(
                    title="🎉 Pet Companion Adopted!",
                    description=(
                        f"You adopted **{res['item_name']}** for **{res['points_spent']:,} pts**!\n"
                        "Your new companion has been equipped! View and care for them using `/pet`."
                    ),
                    color=discord.Color.teal(),
                )
                confirm_embed.add_field(name="Remaining Balance", value=f"**{new_bal:,} pts**", inline=True)
                await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
            else:
                confirm_embed = discord.Embed(
                    title="🎉 Prize Redemption Submitted!",
                    description=(
                        f"You submitted a redemption for **{res['item_name']}** for **{res['points_spent']:,} pts**!\n"
                        f"Jansen has been notified in staff logs. You will receive your prize fulfillment shortly."
                    ),
                    color=discord.Color.gold(),
                )
                confirm_embed.add_field(name="Remaining Balance", value=f"**{new_bal:,} pts**", inline=True)
                await interaction.response.send_message(embed=confirm_embed, ephemeral=True)

                if view.cog:
                    await view.cog._log_activity(
                        title="🎁 Prize Redeemed",
                        description=f"**{interaction.user.display_name}** redeemed **{res['item_name']}** for **{res['points_spent']:,} pts**.",
                        color=discord.Color.gold(),
                    )

            embed = build_shop_embed(view.rewards_service, user_id, view.current_category)
            await interaction.message.edit(embed=embed, view=view)

        except InsufficientPointsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class ShopView(discord.ui.View):
    """Interactive categorized shop view with buttons and quick-buy."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        user_id: int,
        cog: Optional[Any] = None,
    ):
        super().__init__(timeout=180.0)
        self.rewards_service = rewards_service
        self.user_id = user_id
        self.cog = cog
        self.current_category = "home"
        self.update_components()

    def update_components(self) -> None:
        self.clear_items()
        buttons_data = [
            ("home", "Featured", "🏠", 0),
            ("pets", "Pet Shelter", "🐾", 0),
            ("offense", "Offense & Traps", "⚔️", 0),
            ("defense", "Defense & Boosters", "🛡️", 1),
            ("events", "Events & Gacha", "🎲", 1),
            ("prizes", "Real Prizes & Nitro", "🎁", 1),
        ]

        for cat_key, label, emoji, row in buttons_data:
            btn = ShopCategoryButton(cat_key, label, emoji, row=row)
            if cat_key == self.current_category:
                btn.style = discord.ButtonStyle.primary
            else:
                btn.style = discord.ButtonStyle.secondary
            self.add_item(btn)

        self.add_item(ShopQuickBuySelect(category=self.current_category, row=2))


class RewardsCog(commands.Cog):
    """Cog managing student economy, daily attendance streaks, profiles, and leaderboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        service = getattr(bot, "rewards_service", None)
        if isinstance(service, RewardsDBService):
            self.rewards_service = service
        else:
            db_path = "data/rewards.db"
            if hasattr(bot, "settings") and hasattr(bot.settings, "rewards_db_path"):
                p = bot.settings.rewards_db_path
                if isinstance(p, (str, Path)):
                    db_path = str(p)
            self.rewards_service = RewardsDBService(db_path)

    async def cog_load(self) -> None:
        self.daily_tax_loop.start()

    async def cog_unload(self) -> None:
        self.daily_tax_loop.cancel()

    @tasks.loop(hours=1)
    async def daily_tax_loop(self) -> None:
        """Periodic background task that collects 24-hr wealth taxes."""
        try:
            taxes = self.rewards_service.collect_all_pending_taxes()
            if taxes:
                total_tax_collected = sum(t["tax_amount"] for t in taxes)
                logger.info(f"[taxes] Collected {total_tax_collected:,} pts in wealth taxes from {len(taxes)} users.")
        except Exception as e:
            logger.error(f"[taxes] Error during daily wealth tax collection: {e}", exc_info=True)

    @daily_tax_loop.before_loop
    async def before_daily_tax_loop(self) -> None:
        await self.bot.wait_until_ready()

    def _check_admin_permissions(self, interaction: discord.Interaction) -> bool:
        """Verify whether caller is a server administrator or guild owner."""
        user = interaction.user
        guild = interaction.guild
        if not user:
            return False
        if guild and getattr(guild, "owner_id", None) == user.id:
            return True
        perms = getattr(user, "guild_permissions", None)
        if perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False)):
            return True
        return False

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

    @app_commands.command(name="profile", description="View a student's full Uno profile, companion, rank, badges, and inventory.")
    @app_commands.describe(member="The classmate to view (defaults to you).")
    async def profile(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        """Display rich profile card with points, active companion, badges, and inventory."""
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

        file_attachment = None
        if profile.active_pet:
            pet = profile.active_pet
            embed.add_field(
                name=f"🐾 Companion — {pet.nickname} ({pet.display_name})",
                value=(
                    f"⭐ **Level {pet.level}** (💖 {pet.happiness}% Happiness)\n"
                    f"🌟 **Perk:** {pet.perk_title}\n"
                    f"💬 *\"{pet.quote}\"*"
                ),
                inline=False,
            )
            pet_img_path = resolve_pet_image_path(pet.image_file)
            if pet_img_path:
                file_attachment = discord.File(str(pet_img_path), filename=pet.image_file)
                embed.set_thumbnail(url=f"attachment://{pet.image_file}")

        total_duels = profile.duel_wins + profile.duel_losses
        win_rate = (profile.duel_wins / total_duels * 100) if total_duels > 0 else 0.0
        pvp_str = f"⚔️ **{profile.duel_wins}W - {profile.duel_losses}L** ({win_rate:.1f}%)"
        if profile.duel_streak > 0:
            pvp_str += f" | 🔥 {profile.duel_streak} streak"
        if profile.bounties_claimed > 0:
            pvp_str += f" | 🎯 {profile.bounties_claimed} Bounties Claimed"
        embed.add_field(name="⚔️ PvP Combat Record", value=pvp_str, inline=False)

        badges_str = " · ".join(profile.badges) if profile.badges else "No badges unlocked yet."
        embed.add_field(name="🏅 Badges & Milestones", value=badges_str, inline=False)

        if profile.inventory:
            inv_lines = [f"• `{qty}x` **{item_id}**" for item_id, qty in profile.inventory.items()]
            embed.add_field(name="🎒 Inventory", value="\n".join(inv_lines), inline=False)
        else:
            embed.add_field(name="🎒 Inventory", value="Bag is empty.", inline=False)

        if file_attachment:
            await interaction.response.send_message(embed=embed, file=file_attachment)
        else:
            await interaction.response.send_message(embed=embed)

    pet_group = app_commands.Group(name="pet", description="Manage, care for, and adopt pet companions.")

    @pet_group.command(name="view", description="Open the interactive Pet Shelter & Companion Store.")
    async def pet_view(self, interaction: discord.Interaction) -> None:
        """Display comprehensive interactive pet shelter and companion dashboard."""
        all_pets = self.rewards_service.get_user_pets(interaction.user.id)
        user = self.rewards_service.get_or_create_user(interaction.user.id)
        if not all_pets and not user.has_claimed_starter:
            embed = build_starter_pet_embed(interaction.user.display_name)
            view = StarterPetSelectView(self.rewards_service, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view)
            return

        view = PetStoreView(self.rewards_service, interaction.user.id)
        embed, file_att = build_pet_store_embed(
            self.rewards_service, interaction.user.id, view.selected_pet_id, interaction.user.display_name
        )
        if file_att:
            await interaction.response.send_message(embed=embed, file=file_att, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @pet_group.command(name="starter", description="Claim your 1 Free Starter Pet Companion (Tuxedo Cat, Golden Retriever, Lop-Eared Bunny)!")
    @app_commands.describe(
        pet="Your choice of free starter companion.",
        nickname="Optional custom nickname for your starter companion.",
    )
    @app_commands.choices(
        pet=[
            app_commands.Choice(name="🐱 Tuxedo Cat (2x Daily Points)", value="tuxedo_cat"),
            app_commands.Choice(name="🐶 Golden Retriever (Anti-Theft Defense)", value="golden_dog"),
            app_commands.Choice(name="🐰 Lop-Eared Bunny (Casino & Coinflip Luck)", value="brown_bunny"),
        ]
    )
    async def pet_starter(
        self,
        interaction: discord.Interaction,
        pet: Optional[app_commands.Choice[str]] = None,
        nickname: Optional[str] = None,
    ) -> None:
        """Claim free starter pet."""
        user_id = interaction.user.id
        user = self.rewards_service.get_or_create_user(user_id)
        if user.has_claimed_starter:
            await interaction.response.send_message("❌ You have already claimed your free starter companion! Adopt more companions from `/shop` or `/pet adopt`.", ephemeral=True)
            return

        if not pet:
            embed = build_starter_pet_embed(interaction.user.display_name)
            view = StarterPetSelectView(self.rewards_service, user_id)
            await interaction.response.send_message(embed=embed, view=view)
            return

        try:
            pet_rec = self.rewards_service.claim_starter_pet(user_id, pet.value, nickname=nickname)
            embed = discord.Embed(
                title=f"🎉 Welcome Your New Companion: {pet_rec.nickname}!",
                description=(
                    f"You have adopted **{pet_rec.nickname}** ({pet_rec.display_name}) for **FREE**!\n\n"
                    f"🌟 **Active Perk:** **{pet_rec.perk_title}**\n"
                    f"*{pet_rec.perk_desc}*\n\n"
                    f"💬 *\"{pet_rec.quote}\"*\n\n"
                    "Your companion is now equipped and ready for your daily campus adventures! Use `/pet` to care for them!"
                ),
                color=discord.Color.green(),
            )
            file_att = None
            pet_img_path = resolve_pet_image_path(pet_rec.image_file)
            if pet_img_path:
                file_att = discord.File(str(pet_img_path), filename=pet_rec.image_file)
                embed.set_thumbnail(url=f"attachment://{pet_rec.image_file}")

            if file_att:
                await interaction.response.send_message(embed=embed, file=file_att)
            else:
                await interaction.response.send_message(embed=embed)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @pet_group.command(name="adopt", description="Adopt a new pet companion from the shelter.")
    @app_commands.describe(
        pet="The species/variant of pet you want to adopt.",
        nickname="Optional custom nickname for your pet.",
    )
    @app_commands.choices(pet=[
        app_commands.Choice(name="🐱 Tuxedo Cat (50 pts)", value="tuxedo_cat"),
        app_commands.Choice(name="🐱 Fluffy Calico Cat (100 pts)", value="calico_cat"),
        app_commands.Choice(name="🐶 Golden Retriever (50 pts)", value="golden_dog"),
        app_commands.Choice(name="🐶 Shiba Inu (100 pts)", value="shiba_dog"),
        app_commands.Choice(name="🐰 Lop-Eared Bunny (150 pts)", value="brown_bunny"),
        app_commands.Choice(name="🐰 Moon Rabbit (200 pts)", value="white_bunny"),
        app_commands.Choice(name="🦉 Scholar Owl (150 pts)", value="scholar_owl"),
        app_commands.Choice(name="🦉 Frost Owl (200 pts)", value="ice_owl"),
        app_commands.Choice(name="🐢 Master Oogway Turtle (200 pts)", value="oogway_turtle"),
        app_commands.Choice(name="🦊 Trickster Fox (200 pts)", value="orange_fox"),
        app_commands.Choice(name="🦊 Arctic Ice Fox (250 pts)", value="ice_fox"),
        app_commands.Choice(name="🦎 Pastel Pink Axolotl (150 pts)", value="pink_axolotl"),
        app_commands.Choice(name="🦎 Rainbow Axolotl (250 pts)", value="rainbow_axolotl"),
        app_commands.Choice(name="🐠 Fiery Lucky Goldfish (150 pts)", value="fiery_goldfish"),
    ])
    async def pet_adopt(
        self,
        interaction: discord.Interaction,
        pet: app_commands.Choice[str],
        nickname: Optional[str] = None,
    ) -> None:
        """Adopt a pet companion."""
        try:
            res = self.rewards_service.adopt_pet(interaction.user.id, pet.value, nickname=nickname)
            new_bal = self.rewards_service.get_balance(interaction.user.id)
            embed = discord.Embed(
                title="🎉 Pet Companion Adopted!",
                description=(
                    f"Congratulations! You adopted **{res.nickname}** ({res.display_name})!\n\n"
                    f"🌟 **Active Perk:** **{res.perk_title}**\n"
                    f"*{res.perk_desc}*\n\n"
                    f"💬 *\"{res.quote}\"*"
                ),
                color=discord.Color.green(),
            )
            embed.add_field(name="Remaining Balance", value=f"**{new_bal:,} Uno Points**", inline=True)

            pet_img_path = resolve_pet_image_path(res.image_file)
            if pet_img_path:
                file_att = discord.File(str(pet_img_path), filename=res.image_file)
                embed.set_thumbnail(url=f"attachment://{res.image_file}")
                await interaction.response.send_message(embed=embed, file=file_att)
            else:
                await interaction.response.send_message(embed=embed)

            await self._log_activity(
                title="🐾 Pet Adopted",
                description=f"**{interaction.user.display_name}** adopted **{res.nickname}** ({res.display_name}) for **{PET_CATALOG[pet.value]['cost']:,} pts**.",
                color=discord.Color.green(),
            )
        except InsufficientPointsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @pet_group.command(name="switch", description="Switch your currently active equipped companion.")
    @app_commands.describe(pet="The owned pet you want to equip.")
    async def pet_switch(self, interaction: discord.Interaction, pet: str) -> None:
        """Switch active pet companion."""
        try:
            switched = self.rewards_service.switch_active_pet(interaction.user.id, pet)
            await interaction.response.send_message(
                f"✨ Switched active companion to **{switched.nickname}** ({switched.display_name})!\n"
                f"Active Perk: **{switched.perk_title}**",
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @pet_group.command(name="list", description="View all pets in your collection.")
    async def pet_list(self, interaction: discord.Interaction) -> None:
        """List all owned pets."""
        pets = self.rewards_service.get_user_pets(interaction.user.id)
        if not pets:
            await interaction.response.send_message(
                "🏠 You haven't adopted any pet companions yet! Adopt one with `/pet adopt` or in `/shop`.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"🏠 {interaction.user.display_name}'s Pet Collection",
            description=f"Total Companions: **{len(pets)}**",
            color=discord.Color.blue(),
        )
        for p in pets:
            status = "🌟 **ACTIVE**" if p.is_active else "💤 In Kennel"
            embed.add_field(
                name=f"{p.nickname} ({p.display_name}) — Level {p.level} [{status}]",
                value=f"Perk: *{p.perk_title}*\nHappiness: 💖 {p.happiness}%\n`/pet switch {p.pet_id}`",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="rename", description="Give your pet companion a custom nickname.")
    @app_commands.describe(pet="The pet ID you want to rename.", name="The new nickname.")
    async def pet_rename(self, interaction: discord.Interaction, pet: str, name: str) -> None:
        """Rename an owned pet."""
        try:
            res = self.rewards_service.rename_pet(interaction.user.id, pet, name)
            await interaction.response.send_message(
                f"🏷️ Renamed your {res.display_name} to **{res.nickname}**!",
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @pet_group.command(name="guide", description="View the full Pet Companion Handbook and perk guide.")
    async def pet_guide(self, interaction: discord.Interaction) -> None:
        """Display comprehensive companion guide."""
        embed = build_pet_guide_embed()
        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="drop", description="View the currently spotlighted 3-day rotating pet drop.")
    async def pet_drop(self, interaction: discord.Interaction) -> None:
        """Display the active 3-day pet spotlight."""
        embed, file_att, view = build_pet_drop_announcement_embed(self.rewards_service)
        if file_att:
            await interaction.response.send_message(embed=embed, file=file_att, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @pet_group.command(name="sell", description="Sell an owned pet companion back to the shelter for a points refund.")
    @app_commands.describe(pet="The species or ID of the pet you want to sell.")
    async def pet_sell(self, interaction: discord.Interaction, pet: str) -> None:
        """Initiate companion sale confirmation."""
        clean_id = pet.strip().lower()
        user_pets = self.rewards_service.get_user_pets(interaction.user.id)
        target_pet = next((p for p in user_pets if p.pet_id == clean_id), None)
        if not target_pet:
            await interaction.response.send_message(
                f"❌ You do not own the pet `{pet}`! Check your collection with `/pet list`.",
                ephemeral=True,
            )
            return

        base_cost = PET_CATALOG.get(clean_id, {}).get("cost", 500)
        base_ref = int(base_cost * 0.60)
        lvl_bonus = (target_pet.level - 1) * 25
        total_ref = base_ref + lvl_bonus

        embed = discord.Embed(
            title=f"⚠️ Confirm Selling {target_pet.nickname}?",
            description=(
                f"Are you sure you want to release **{target_pet.nickname}** ({target_pet.display_name})?\n\n"
                f"💰 **Refund Amount:** `+{total_ref:,} Uno Points`\n"
                f"• Base Refund (60%): `+{base_ref:,} pts`\n"
                f"• Level {target_pet.level} Bonus: `+{lvl_bonus:,} pts`\n\n"
                "⚠️ *This action is irreversible. The pet will return to the shelter.*"
            ),
            color=discord.Color.orange(),
        )
        view = PetSellConfirmView(self.rewards_service, interaction.user.id, target_pet)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @pet_group.command(name="force-drop", description="[Admin] Broadcast a pet drop announcement in this channel.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(pet="Specific pet to spotlight (optional, defaults to current rotation).")
    async def pet_force_drop(self, interaction: discord.Interaction, pet: Optional[str] = None) -> None:
        """Broadcast pet drop announcement."""
        if not self._check_admin_permissions(interaction):
            await interaction.response.send_message("⛔ Access Denied: Admin only.", ephemeral=True)
            return

        pet_val = pet.strip().lower() if pet else None
        if pet_val and pet_val not in PET_CATALOG:
            await interaction.response.send_message(f"❌ Unknown pet `{pet}`.", ephemeral=True)
            return

        embed, file_att, view = build_pet_drop_announcement_embed(self.rewards_service, pet_id=pet_val)
        if file_att:
            await interaction.response.send_message(embed=embed, file=file_att, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="rank", description="View the top 10 highest-ranked BSCS 1-4 members.")
    async def rank(self, interaction: discord.Interaction) -> None:
        """Display quick Top 10 leaderboard."""
        embed, _ = await build_leaderboard_embed(
            self.rewards_service, interaction.guild, bot=self.bot, page=1, per_page=10
        )
        embed.title = "📊 Top 10 Scholars — Uno Rankings"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Browse the full paginated class leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        """Browse the full class leaderboard with interactive pagination buttons."""
        embed, total_pages = await build_leaderboard_embed(
            self.rewards_service, interaction.guild, bot=self.bot, page=1, per_page=10
        )
        view = LeaderboardView(
            self.rewards_service,
            interaction.guild,
            bot=self.bot,
            page=1,
            per_page=10,
            total_pages=total_pages,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="bet", description="Gamble Uno Points on roulette with dynamic multipliers! (Limit: 10 bets/day)")
    @app_commands.describe(amount="The amount of Uno Points to wager (minimum 10, default 50).")
    async def bet(self, interaction: discord.Interaction, amount: int = 50) -> None:
        """Play roulette with custom wager (limit 10 bets/day)."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.play_bet(user_id, wager=amount)

            if res.outcome in (BetOutcome.JACKPOT, BetOutcome.DOUBLE):
                if res.outcome == BetOutcome.JACKPOT:
                    title = f"🎰 MEGA JACKPOT! (5x Return: +{res.points_delta:,} pts)"
                    desc = (
                        f"🎉 **JACKPOT!** You wagered **{res.wager:,} pts** and won a **5x payout**!\n"
                        f"💰 **Total Return:** `{res.total_payout:,} pts` (Net Profit: **+{res.points_delta:,} pts**)"
                    )
                else:
                    title = f"⚡ DOUBLE WIN! (2x Return: +{res.points_delta:,} pts)"
                    desc = (
                        f"🎉 **DOUBLE!** You wagered **{res.wager:,} pts** and won a **2x payout**!\n"
                        f"💰 **Total Return:** `{res.total_payout:,} pts` (Net Profit: **+{res.points_delta:,} pts**)"
                    )
                color = discord.Color.gold()
            elif res.outcome == BetOutcome.SKILL_DROP:
                title = "🃏 Skill Card Dropped!"
                desc = (
                    f"You wagered **{res.wager:,} pts** and won a rare consumable item: **{res.reward_item_name}**!\n"
                    f"🪙 Your **{res.wager:,} pts** wager was reimbursed.\n*Check `/inventory` or activate with `/use`!*"
                )
                color = discord.Color.purple()
            elif res.outcome == BetOutcome.REFUND:
                title = "🪙 Break-Even / Refund"
                desc = f"You rolled a safe break-even! Your **{res.wager:,} Uno Points** were refunded."
                color = discord.Color.blue()
            else:
                title = "❌ Busted! (House Wins)"
                desc = f"The house took your bet. You lost **{res.wager:,} Uno Points**."
                color = discord.Color.red()

            embed = discord.Embed(title=title, description=desc, color=color)
            embed.add_field(name="Current Balance", value=f"**{res.new_balance:,} Uno Points**", inline=True)
            embed.set_footer(text=f"Gamble responsibly • {res.bets_remaining}/10 bets remaining today • 🐰 Bunny pet boosts luck")

            await interaction.response.send_message(embed=embed)

            await self._log_activity(
                title=f"🎰 Bet: {res.outcome.value}",
                description=f"**{interaction.user.display_name}** placed a {res.wager:,} pt bet.",
                color=color,
                fields=[
                    ("Wager", f"{res.wager:,} pts", True),
                    (
                        "Reward / Change",
                        f"{'+' if res.points_delta > 0 else ''}{res.points_delta:,} pts"
                        + (f" ({res.reward_item_name})" if res.reward_item_name else ""),
                        True,
                    ),
                    ("New Balance", f"{res.new_balance:,} pts", True),
                ],
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="slots", description="Spin the 3-reel slot machine (max 100 pts, limit 15 casino games/day).")
    @app_commands.describe(amount="The amount of Uno Points to wager (minimum 10, max 100, default 50).")
    async def slots(self, interaction: discord.Interaction, amount: int = 50) -> None:
        """Spin 3-reel slot machine."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.play_slots(user_id, wager=amount)

            reels_display = "  ".join(f"` {r} `" for r in res.reels)
            if res.is_jackpot:
                title = "👑 20x UNO WILD MEGA JACKPOT!"
                color = discord.Color.gold()
            elif res.multiplier >= 2.5:
                title = f"🎉 TRIPLE MATCH! ({res.multiplier:.1f}x Payout)"
                color = discord.Color.green()
            elif res.multiplier > 0:
                title = f"✨ DOUBLE MATCH! ({res.multiplier:.1f}x Consolation)"
                color = discord.Color.blue()
            else:
                title = "❌ Busted! (No Match)"
                color = discord.Color.red()

            embed = discord.Embed(
                title=title,
                description=(
                    f"🎰 **Reels:**\n# {reels_display}\n\n"
                    f"{res.description}\n\n"
                    f"💰 **Wager:** `{res.wager:,} pts`\n"
                    f"🏆 **Payout:** `{res.points_won:,} pts` ({'+' if res.points_delta > 0 else ''}{res.points_delta:,} pts net)\n"
                    f"💳 **Wallet Balance:** `{res.new_balance:,} Uno Points`"
                ),
                color=color,
            )
            embed.set_footer(text=f"🍒 2.5x | 🍋 3x | 🍇 4.5x | 💎 7x | 👑 12x | 🃏 20x • {res.games_remaining}/15 games left today")
            await interaction.response.send_message(embed=embed)

            await self._log_activity(
                title="🎰 Slots Spin",
                description=f"**{interaction.user.display_name}** spun the slot machine: [{' '.join(res.reels)}]",
                color=color,
                fields=[
                    ("Wager", f"{res.wager:,} pts", True),
                    ("Payout", f"{res.points_won:,} pts", True),
                    ("New Balance", f"{res.new_balance:,} pts", True),
                ],
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="coinflip", description="Flip a coin for instant 1.70x payout (max 100 pts, limit 15 games/day)!")
    @app_commands.describe(choice="Choose Heads or Tails.", amount="The amount of Uno Points to wager (minimum 10, max 100, default 50).")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="🪙 Heads", value="heads"),
            app_commands.Choice(name="🪙 Tails", value="tails"),
        ]
    )
    async def coinflip(self, interaction: discord.Interaction, choice: app_commands.Choice[str], amount: int = 50) -> None:
        """Play 1.70x payout coinflip."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.play_coinflip(user_id, choice=choice.value, wager=amount)

            if res.won:
                title = "🎉 COINFLIP WON! (1.70x Return)"
                desc = (
                    f"🪙 The coin landed on **{res.result.upper()}**!\n\n"
                    f"Your guess was **CORRECT**! You won **+{res.points_delta:,} Uno Points** ({int(res.wager * 1.70):,} pts total payout)!"
                )
                color = discord.Color.green()
            else:
                title = "❌ COINFLIP LOST!"
                desc = (
                    f"🪙 The coin landed on **{res.result.upper()}**!\n\n"
                    f"You guessed **{res.choice.upper()}**. You lost **{res.wager:,} Uno Points**."
                )
                color = discord.Color.red()

            embed = discord.Embed(title=title, description=desc, color=color)
            embed.add_field(name="Wager", value=f"`{res.wager:,} pts`", inline=True)
            embed.add_field(name="Current Balance", value=f"**{res.new_balance:,} pts**", inline=True)
            embed.set_footer(text=f"1.70x Multiplier • {res.games_remaining}/15 games left today • 🐰 Bunny pet increases odds")
            await interaction.response.send_message(embed=embed)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="blackjack", description="Play classic Blackjack 21 vs the Dealer with Hit, Stand, and Double Down!")
    @app_commands.describe(amount="The amount of Uno Points to wager (minimum 10, default 50).")
    async def blackjack(self, interaction: discord.Interaction, amount: int = 50) -> None:
        """Start a Blackjack 21 table."""
        user_id = interaction.user.id
        try:
            game = self.rewards_service.start_blackjack(user_id, wager=amount)
            embed = build_blackjack_embed(game, interaction.user.display_name)
            if game.status == "IN_PROGRESS":
                view = BlackjackView(self.rewards_service, user_id, interaction.user.display_name)
                await interaction.response.send_message(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="highlow", description="Guess if the next card is Higher or Lower. Cash out streaks for up to 30x!")
    @app_commands.describe(amount="The amount of Uno Points to wager (minimum 10, default 50).")
    async def highlow(self, interaction: discord.Interaction, amount: int = 50) -> None:
        """Start a High-Low streak game."""
        user_id = interaction.user.id
        try:
            game = self.rewards_service.start_highlow(user_id, wager=amount)
            embed = build_highlow_embed(game, interaction.user.display_name)
            view = HighLowView(self.rewards_service, user_id, interaction.user.display_name)
            await interaction.response.send_message(embed=embed, view=view)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="cups", description="Play the Intramuros 3-Cup Shell Game! Guess which cup hides the gold coin (Unlimited bets!).")
    @app_commands.describe(
        cup="Choose Cup 1, 2, or 3.",
        amount="The amount of Uno Points to wager (min 10, max 250, default 50).",
    )
    @app_commands.choices(
        cup=[
            app_commands.Choice(name="🥤 Cup 1", value=1),
            app_commands.Choice(name="🥤 Cup 2", value=2),
            app_commands.Choice(name="🥤 Cup 3", value=3),
        ]
    )
    async def cups(self, interaction: discord.Interaction, cup: app_commands.Choice[int], amount: int = 50) -> None:
        """Play the 3-Cup Shell Game."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.play_cups(user_id, chosen_cup=cup.value, wager=amount)

            if res.won:
                title = "🎉 GOLD COIN FOUND! Winner!"
                color = discord.Color.gold()
            else:
                title = "❌ EMPTY CUP! The Dealer Took Your Bet!"
                color = discord.Color.red()

            embed = discord.Embed(
                title=title,
                description=(
                    f"🎩 **Intramuros Street Shell Game**\n\n"
                    f"{res.display_cups}\n\n"
                    f"{res.flavor_text}\n\n"
                    f"💬 **Shady Dealer:**\n{res.dealer_comment}\n\n"
                    f"💰 **Wager:** `{res.wager:,} pts`\n"
                    f"🏆 **Payout:** `{res.payout:,} pts` ({'+' if res.points_delta > 0 else ''}{res.points_delta:,} pts net)\n"
                    f"💳 **Wallet Balance:** `{res.new_balance:,} Uno Points`"
                ),
                color=color,
            )
            embed.set_footer(text="Intramuros Back-Alley Street Hustle • Unlimited Wagers • Play at your own risk")
            await interaction.response.send_message(embed=embed)

            await self._log_activity(
                title="🎩 Shell Game",
                description=f"**{interaction.user.display_name}** played Cups (Picked {res.chosen_cup}, Ball under {res.winning_cup}) -> {'WON' if res.won else 'LOST'}",
                color=color,
                fields=[
                    ("Wager", f"{res.wager:,} pts", True),
                    ("Payout", f"{res.payout:,} pts", True),
                    ("New Balance", f"{res.new_balance:,} pts", True),
                ],
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="work", description="Work an odd job on campus to earn 40–120 Uno Points and skill cards! (1h cooldown)")
    async def work(self, interaction: discord.Interaction) -> None:
        """Work a campus odd job."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.execute_work(user_id)
            embed = discord.Embed(
                title=f"💼 Campus Shift Complete — {res.job_title}",
                description=(
                    f"🏢 **Client:** {res.company_or_prof}\n\n"
                    f"📝 *{res.description}*\n\n"
                    f"💰 **Earned:** `+{res.points_earned:,} Uno Points`\n"
                    f"💳 **Wallet Balance:** `{res.new_balance:,} Uno Points`"
                ),
                color=discord.Color.green(),
            )
            if res.bonus_item_name:
                embed.add_field(
                    name="🎁 Rare Bonus Drop!",
                    value=f"Your boss gave you a free **{res.bonus_item_name}**!\n*Check `/inventory`!*",
                    inline=False,
                )
            embed.set_footer(text="Work cooldown: 1 hour • Resets automatically")
            await interaction.response.send_message(embed=embed)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="beg", description="Scavenge around campus for pocket change (10–40 pts). (30m cooldown)")
    async def beg(self, interaction: discord.Interaction) -> None:
        """Scavenge around campus."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.execute_scavenge(user_id)
            embed = discord.Embed(
                title=f"🎒 Campus Scavenge — {res.location}",
                description=(
                    f"*{res.description}*\n\n"
                    f"💰 **Found:** `+{res.points_earned:,} Uno Points`\n"
                    f"💳 **Wallet Balance:** `{res.new_balance:,} Uno Points`"
                ),
                color=discord.Color.teal(),
            )
            embed.set_footer(text="Scavenge cooldown: 30 minutes • Look around Intramuros!")
            await interaction.response.send_message(embed=embed)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="duel", description="Challenge a classmate to a 1v1 wager duel with selectable game modes!")
    @app_commands.describe(
        target="The classmate to duel against.",
        amount="Wager amount in Uno Points (min 10 pts, winner takes double).",
        mode="Game mode: Dice Roll (default), Rock-Paper-Scissors, Uno Russian Roulette, or RPG Arena Combat.",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="🎲 Dice High-Roll Showdown", value="dice"),
            app_commands.Choice(name="✂️ Rock-Paper-Scissors (RPS)", value="rps"),
            app_commands.Choice(name="🃏 Uno Russian Roulette (6-Card Chamber)", value="roulette"),
            app_commands.Choice(name="⚔️ Turn-Based RPG Combat (100 HP)", value="rpg"),
        ]
    )
    async def duel(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: int = 50,
        mode: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        """Challenge a classmate to a 1v1 wager duel."""
        if target.bot:
            await interaction.response.send_message("❌ You cannot duel a bot!", ephemeral=True)
            return
        if target.id == interaction.user.id:
            await interaction.response.send_message("❌ You cannot duel yourself!", ephemeral=True)
            return
        if amount < 10:
            await interaction.response.send_message("❌ Minimum duel wager is 10 Uno Points!", ephemeral=True)
            return

        c_bal = self.rewards_service.get_balance(interaction.user.id)
        t_bal = self.rewards_service.get_balance(target.id)

        if c_bal < amount:
            await interaction.response.send_message(f"❌ You don't have enough points! (Wallet: `{c_bal:,} pts`)", ephemeral=True)
            return
        if t_bal < amount:
            await interaction.response.send_message(f"❌ {target.display_name} doesn't have enough points for this duel! (Wallet: `{t_bal:,} pts`)", ephemeral=True)
            return

        chosen_mode = mode.value if mode else "dice"
        mode_titles = {
            "dice": "🎲 Dice High-Roll Clash",
            "rps": "✂️ Rock-Paper-Scissors",
            "roulette": "🃏 Uno Russian Roulette",
            "rpg": "⚔️ RPG Arena Combat",
        }

        embed = discord.Embed(
            title="⚔️ 1v1 PvP DUEL CHALLENGE!",
            description=(
                f"**{interaction.user.mention}** has challenged **{target.mention}** to a high-stakes duel!\n\n"
                f"🎮 **Game Mode:** `{mode_titles.get(chosen_mode, chosen_mode.upper())}`\n"
                f"💰 **Wager per Player:** `{amount:,} Uno Points`\n"
                f"🏆 **Total Winner's Pot:** `{amount * 2:,} Uno Points`\n\n"
                f"{target.mention}, click **[ Accept Duel ]** below to roll the dice!"
            ),
            color=discord.Color.red(),
        )
        embed.set_footer(text="Winner takes all • 60s timeout to accept")
        view = DuelAcceptView(self.rewards_service, interaction.user, target, amount, mode=chosen_mode)
        await interaction.response.send_message(content=f"{target.mention}", embed=embed, view=view)

    @app_commands.command(name="bank", description="Manage your campus Piggy Bank to protect points from thieves and audits!")
    @app_commands.describe(action="Deposit, withdraw, or view bank balance.", amount="Amount of points to deposit or withdraw.")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🏦 View Bank Balance", value="view"),
            app_commands.Choice(name="📥 Deposit Points", value="deposit"),
            app_commands.Choice(name="📤 Withdraw Points", value="withdraw"),
        ]
    )
    async def bank(self, interaction: discord.Interaction, action: app_commands.Choice[str], amount: Optional[int] = None) -> None:
        """Deposit or withdraw points from protected bank account."""
        user_id = interaction.user.id
        try:
            if action.value == "deposit":
                if amount is None or amount <= 0:
                    await interaction.response.send_message("❌ Please specify a positive amount to deposit.", ephemeral=True)
                    return
                res = self.rewards_service.bank_deposit(user_id, amount)
                embed = discord.Embed(
                    title="📥 Piggy Bank Deposit Successful",
                    description=(
                        f"Deposited **{res['amount_deposited']:,} Uno Points**\n"
                        f"🏷️ **10% Banking Fee:** `-{res['fee']:,} pts`\n"
                        f"✨ **Credited to Vault:** `+{res['amount_credited']:,} pts`\n\n"
                        f"💳 **Wallet Balance:** `{res['new_wallet']:,} pts`\n"
                        f"🏦 **Bank Vault:** `{res['new_bank']:,} pts`"
                    ),
                    color=discord.Color.green(),
                )
                embed.set_footer(text="Bank vault points are 100% immune to pickpockets! • 10% deposit fee")
                await interaction.response.send_message(embed=embed, ephemeral=True)

            elif action.value == "withdraw":
                if amount is None or amount <= 0:
                    await interaction.response.send_message("❌ Please specify a positive amount to withdraw.", ephemeral=True)
                    return
                res = self.rewards_service.bank_withdraw(user_id, amount)
                embed = discord.Embed(
                    title="📤 Piggy Bank Withdrawal Successful",
                    description=(
                        f"Withdrew **{res['amount_withdrawn']:,} Uno Points**\n"
                        f"🏷️ **10% ATM Fee:** `-{res['fee']:,} pts`\n"
                        f"✨ **Credited to Wallet:** `+{res['amount_credited']:,} pts`\n\n"
                        f"💳 **Wallet Balance:** `{res['new_wallet']:,} pts`\n"
                        f"🏦 **Bank Vault:** `{res['new_bank']:,} pts`"
                    ),
                    color=discord.Color.blue(),
                )
                embed.set_footer(text="10% withdrawal fee applied • Wallet points are vulnerable to pickpockets")
                await interaction.response.send_message(embed=embed, ephemeral=True)

            else:  # view
                prof = self.rewards_service.get_profile(user_id)
                net_worth = prof.points + prof.bank_points
                tax_rate_str = "10%" if net_worth >= 1000 else "8%"
                embed = discord.Embed(
                    title=f"🏦 {interaction.user.display_name}'s Campus Piggy Bank",
                    description=(
                        f"🔒 **Vault Status:** Protected & Insured\n\n"
                        f"🏦 **Bank Vault Balance:** `{prof.bank_points:,} Uno Points`\n"
                        f"💳 **Active Wallet:** `{prof.points:,} Uno Points`\n"
                        f"💎 **Total Net Worth:** `{net_worth:,} Uno Points`\n\n"
                        f"🏛️ **Daily Tax Bracket:** `{tax_rate_str}` every 24hrs\n"
                        f"🏷️ **Banking Fees:** `10%` on deposits and withdrawals"
                    ),
                    color=discord.Color.gold(),
                )
                embed.set_footer(text="Use /bank deposit <amount> or /bank withdraw <amount>")
                await interaction.response.send_message(embed=embed, ephemeral=True)

        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    bounty_group = app_commands.Group(name="bounty", description="Place and view classroom wanted bounties.")

    @bounty_group.command(name="place", description="Place a wanted bounty on a classmate (awarded to whoever defeats them in a duel)!")
    @app_commands.describe(
        target="The classmate to place a bounty on.",
        amount="Amount of Uno Points to put on their head (min 50 pts).",
    )
    async def bounty_place(self, interaction: discord.Interaction, target: discord.Member, amount: int) -> None:
        """Place a bounty on a student."""
        if target.bot:
            await interaction.response.send_message("❌ You cannot place a bounty on a bot!", ephemeral=True)
            return
        if target.id == interaction.user.id:
            await interaction.response.send_message("❌ You cannot place a bounty on yourself!", ephemeral=True)
            return

        try:
            res = self.rewards_service.place_bounty(interaction.user.id, target.id, amount)
            embed = discord.Embed(
                title=f"🎯 WANTED: {target.display_name}!",
                description=(
                    f"**{interaction.user.mention}** placed a **`{amount:,} Uno Points`** bounty on **{target.mention}**!\n\n"
                    f"💰 **Total Bounty Pool on {target.display_name}:** **`{res['total_pool']:,} pts`**\n\n"
                    f"⚔️ Defeat {target.mention} in any `/duel` to claim this bounty pot!"
                ),
                color=discord.Color.dark_gold(),
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            await interaction.response.send_message(embed=embed)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @bounty_group.command(name="list", description="View the classroom Most Wanted bounty board.")
    async def bounty_list(self, interaction: discord.Interaction) -> None:
        """Display active wanted bounties."""
        board = self.rewards_service.get_bounty_board()
        if not board:
            embed = discord.Embed(
                title="🎯 Classroom Wanted Board",
                description="There are currently no active bounties! Place one with `/bounty place @classmate <amount>`.",
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            title="🎯 Classroom Most Wanted Bounty Board",
            description="Defeat these targets in any `/duel` to claim their bounty pool!\n",
            color=discord.Color.gold(),
        )
        for i, item in enumerate(board, start=1):
            t_user = interaction.guild.get_member(item["target_id"]) if interaction.guild else None
            name = t_user.display_name if t_user else f"User {item['target_id']}"
            embed.add_field(
                name=f"#{i} WANTED: {name}",
                value=f"💰 **`{item['total_bounty']:,} pts`** ({item['bounty_count']} active bounty claims)",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="steal", description="Consume a Pickpocket Card to attempt stealing 40%-60% points from a classmate!")
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

            if res.reversed_by_uno:
                embed = discord.Embed(
                    title="🔄 UNO REVERSED! Steal Countered!",
                    description=(
                        f"💥 **{target.display_name}** held an active **🔄 Uno Reverse Card**!\n\n"
                        f"Your robbery was **REVERSED**! **{target.display_name}** counter-stole **{res.points_stolen:,} Uno Points** from your wallet!"
                    ),
                    color=discord.Color.magenta(),
                )
                embed.add_field(name="Your Balance", value=f"**{res.thief_new_balance:,} pts**", inline=True)
                embed.add_field(name=f"{target.display_name}'s Balance", value=f"**{res.target_new_balance:,} pts**", inline=True)
                await interaction.response.send_message(embed=embed)
                await self._log_activity(
                    title="🔄 Uno Reverse Triggered",
                    description=f"**{target.display_name}** reversed **{interaction.user.display_name}**'s steal and counter-stole **{res.points_stolen:,} pts**!",
                    color=discord.Color.magenta(),
                )
                return

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

    @app_commands.command(name="give", description="Give Uno Points to a classmate from your wallet (15% transfer fee).")
    @app_commands.describe(
        target="The classmate to send points to.",
        amount="How many Uno Points to give (minimum 15, requires 100 pt wallet balance).",
    )
    async def give(self, interaction: discord.Interaction, target: discord.Member, amount: int) -> None:
        """Transfer points from the caller's wallet to another member."""
        if target.bot:
            await interaction.response.send_message("❌ You cannot give points to a bot!", ephemeral=True)
            return

        if target.id == interaction.user.id:
            await interaction.response.send_message("❌ You cannot give points to yourself!", ephemeral=True)
            return

        try:
            res = self.rewards_service.transfer_points(interaction.user.id, target.id, amount)

            embed = discord.Embed(
                title="💸 Points Transferred!",
                description=(
                    f"**{interaction.user.display_name}** sent **{res['amount_sent']:,} Uno Points** "
                    f"to **{target.display_name}**!\n"
                    f"🏛️ **Campus Treasury Fee (15%):** `-{res['fee']:,} pts`\n"
                    f"📥 **Credited to {target.display_name}:** `+{res['amount_received']:,} pts`"
                ),
                color=discord.Color.green(),
            )
            embed.add_field(name=f"{interaction.user.display_name}'s Balance", value=f"`{res['sender_new_balance']:,} pts`", inline=True)
            embed.add_field(name=f"{target.display_name}'s Balance", value=f"`{res['receiver_new_balance']:,} pts`", inline=True)
            embed.set_footer(text="15% Treasury Transfer Fee applies to all peer transfers.")
            await interaction.response.send_message(embed=embed)

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

    @app_commands.command(name="use", description="Activate a consumable item from your inventory (e.g. Shield, Airdrop, Gacha, EMP).")
    @app_commands.describe(
        item="The consumable item to activate.",
        target="Target classmate (required for EMP Shield Breaker or Class Treasurer Audit).",
    )
    @app_commands.choices(item=[
        app_commands.Choice(name="🛡️ 1-Week Immunity Shield", value="shield_1w"),
        app_commands.Choice(name="⚡ 2x Daily Booster Card", value="double_daily"),
        app_commands.Choice(name="🌧️ Point Airdrop", value="airdrop"),
        app_commands.Choice(name="📦 Mystery Gacha Box", value="gacha_box"),
        app_commands.Choice(name="🔨 EMP Shield Breaker", value="shield_breaker"),
        app_commands.Choice(name="🕵️ Class Treasurer Audit", value="tax_audit"),
        app_commands.Choice(name="☕ Dean's Coffee Bribe", value="coffee_bribe"),
    ])
    async def use(
        self,
        interaction: discord.Interaction,
        item: app_commands.Choice[str],
        target: Optional[discord.Member] = None,
    ) -> None:
        """Activate an item from inventory."""
        target_id = target.id if target else None
        try:
            res = self.rewards_service.use_item(
                user_id=interaction.user.id,
                item_id=item.value,
                target_id=target_id,
            )

            # Special UI for Point Airdrop
            if item.value == "airdrop":
                embed = discord.Embed(
                    title="🌧️ POINT AIRDROP INCOMING!",
                    description=(
                        f"**{interaction.user.display_name}** just dropped a **100-Point Care Package** in the channel!\n\n"
                        f"⚡ The first **4 classmates** to smash the button below get **+25 Uno Points** each!"
                    ),
                    color=discord.Color.gold(),
                )
                view = AirdropCatchView(
                    rewards_service=self.rewards_service,
                    launcher_id=interaction.user.id,
                    embed=embed,
                )
                await interaction.response.send_message(embed=embed, view=view)
                await self._log_activity(
                    title="🌧️ Point Airdrop Launched",
                    description=f"**{interaction.user.display_name}** launched a 100 pt community airdrop!",
                    color=discord.Color.gold(),
                )
                return

            embed = discord.Embed(
                title=f"✨ {res.item_name} Activated!",
                description=res.description,
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)

            await self._log_activity(
                title="✨ Item Activated",
                description=f"**{interaction.user.display_name}** activated **{res.item_name}**" + (f" on {target.display_name}" if target else "") + ".",
                color=discord.Color.blue(),
            )
        except ItemNotFoundError:
            await interaction.response.send_message(
                f"❌ You do not have **{item.name}** in your inventory! Buy one from `/shop` or win from `/bet`.",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


    @app_commands.command(name="shop", description="Browse redeemable prizes and consumable skill cards by category.")
    async def shop(self, interaction: discord.Interaction) -> None:
        """Display interactive categorized Uno Rewards shop."""
        embed = build_shop_embed(self.rewards_service, interaction.user.id, category="home")
        view = ShopView(
            rewards_service=self.rewards_service,
            user_id=interaction.user.id,
            cog=self,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="redeem", description="Redeem a prize or consumable item from the shop.")
    @app_commands.describe(item="The prize item you want to purchase.")
    @app_commands.choices(item=[
        app_commands.Choice(name="🦹 Pickpocket Card (100 pts)", value="pickpocket"),
        app_commands.Choice(name="🛡️ 1-Week Immunity Shield (150 pts)", value="shield_1w"),
        app_commands.Choice(name="⚡ 2x Daily Booster Card (120 pts)", value="double_daily"),
        app_commands.Choice(name="🔄 Uno Reverse Card (180 pts)", value="uno_reverse"),
        app_commands.Choice(name="🌧️ Point Airdrop (120 pts)", value="airdrop"),
        app_commands.Choice(name="📦 Mystery Gacha Box (150 pts)", value="gacha_box"),
        app_commands.Choice(name="🔨 EMP Shield Breaker (140 pts)", value="shield_breaker"),
        app_commands.Choice(name="🕵️ Class Treasurer Audit (200 pts)", value="tax_audit"),
        app_commands.Choice(name="☕ Dean's Coffee Bribe (100 pts)", value="coffee_bribe"),
        app_commands.Choice(name="☕ Intramuros Coffee Treat (1,200 pts)", value="coffee"),
        app_commands.Choice(name="💳 GCash Gift Card ₱100 (2,200 pts)", value="gcash_100"),
        app_commands.Choice(name="🖨️ Free Printing Service 1 Month (2,800 pts)", value="printing_1m"),
        app_commands.Choice(name="🚀 1 Month Discord Nitro (5,500 pts)", value="nitro_1m"),
    ])
    async def redeem(self, interaction: discord.Interaction, item: app_commands.Choice[str]) -> None:
        """Redeem a shop item."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.record_redemption(user_id, item.value)
            new_balance = self.rewards_service.get_balance(user_id)

            if res["category"] == "consumable":
                embed = discord.Embed(
                    title="🛍️ Consumable Purchased!",
                    description=f"You purchased **{res['item_name']}** for **{res['points_spent']:,} pts**!\nItem has been added to your `/inventory`.",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Remaining Balance", value=f"**{new_balance:,} pts**", inline=True)
                await interaction.response.send_message(embed=embed)
            else:
                embed = discord.Embed(
                    title="🎉 Prize Redemption Submitted!",
                    description=(
                        f"You submitted a redemption for **{res['item_name']}** for **{res['points_spent']:,} pts**!\n"
                        f"Jansen has been notified in staff logs. You will receive your prize fulfillment shortly."
                    ),
                    color=discord.Color.gold(),
                )
                embed.add_field(name="Remaining Balance", value=f"**{new_balance:,} pts**", inline=True)
                await interaction.response.send_message(embed=embed)

                # Send approval prompt to staff channel
                log_channel_id = getattr(self.bot.settings, "rewards_log_channel_id", None)
                if log_channel_id:
                    channel = self.bot.get_channel(log_channel_id)
                    if channel:
                        approval_embed = discord.Embed(
                            title="🎁 New Prize Redemption Claim",
                            description=f"Student **{interaction.user.display_name}** (`{interaction.user.id}`) redeemed **{res['item_name']}**.",
                            color=discord.Color.gold(),
                            timestamp=datetime.now(timezone.utc),
                        )
                        approval_embed.add_field(name="Item", value=res["item_name"], inline=True)
                        approval_embed.add_field(name="Points Spent", value=f"{res['points_spent']:,} pts", inline=True)
                        approval_embed.add_field(name="Claim ID", value=f"#{res['id']}", inline=True)
                        view = RedemptionApprovalView(self.rewards_service, res["id"])
                        await channel.send(embed=approval_embed, view=view)

        except InsufficientPointsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="admin-inspect", description="[Admin] Inspect a student's points, streaks, badges, and recent transactions.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="The classmate to inspect.")
    async def admin_inspect(self, interaction: discord.Interaction, member: discord.Member) -> None:
        """Admin command to inspect student economy details."""
        if not self._check_admin_permissions(interaction):
            await interaction.response.send_message(
                "⛔ **Access Denied**: You must be a Server Administrator to use this command.",
                ephemeral=True,
            )
            return

        profile = self.rewards_service.get_profile(member.id)
        txs = self.rewards_service.get_user_transactions(member.id, limit=5)

        embed = discord.Embed(
            title=f"🔍 Admin Inspection — {member.display_name}",
            color=discord.Color.dark_blue(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=str(member.id), inline=True)
        embed.add_field(name="Current Points", value=f"{profile.points:,} pts", inline=True)
        embed.add_field(name="Lifetime Earned", value=f"{profile.lifetime_points:,} pts", inline=True)
        embed.add_field(name="Daily Streak", value=f"{profile.daily_streak}d 🔥", inline=True)
        embed.add_field(name="Rank", value=f"#{profile.rank}", inline=True)
        embed.add_field(
            name="Shield",
            value=f"Active until <t:{int(profile.shield_until.timestamp())}:f>" if profile.shield_until else "None",
            inline=True,
        )

        if txs:
            tx_lines = [
                f"• `{tx['action_type']}` ({'+' if tx['amount'] > 0 else ''}{tx['amount']:,} pts): {tx['description']}"
                for tx in txs
            ]
            embed.add_field(name="Recent Transactions (Last 5)", value="\n".join(tx_lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="admin-points", description="[Admin] Add or deduct Uno Points for a member.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        action="Whether to add or deduct points.",
        member="The student whose points to modify.",
        amount="The amount of points to adjust.",
        reason="Reason for the adjustment (e.g. Quiz Bee Winner).",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="➕ Add Points", value="add"),
        app_commands.Choice(name="➖ Deduct Points", value="deduct"),
    ])
    async def admin_points(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        member: discord.Member,
        amount: int,
        reason: str,
    ) -> None:
        """Admin point adjustment command."""
        if not self._check_admin_permissions(interaction):
            await interaction.response.send_message(
                "⛔ **Access Denied**: You must be a Server Administrator to use this command.",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
            return

        if action.value == "add":
            new_bal = self.rewards_service.add_points(member.id, amount, "ADMIN_ADD", f"Admin Grant: {reason}")
            embed = discord.Embed(
                title="✨ Points Granted",
                description=f"Added **+{amount:,} Uno Points** to **{member.display_name}**.\nReason: *{reason}*",
                color=discord.Color.green(),
            )
            embed.add_field(name="New Balance", value=f"**{new_bal:,} pts**", inline=True)
            await interaction.response.send_message(embed=embed)

            await self._log_activity(
                title="👑 Admin Point Adjustment",
                description=f"**{interaction.user.display_name}** added **+{amount:,} pts** to **{member.display_name}** ({reason}).",
                color=discord.Color.gold(),
            )
        else:
            try:
                new_bal = self.rewards_service.deduct_points(member.id, amount, "ADMIN_DEDUCT", f"Admin Deduction: {reason}")
                embed = discord.Embed(
                    title="➖ Points Deducted",
                    description=f"Deducted **-{amount:,} Uno Points** from **{member.display_name}**.\nReason: *{reason}*",
                    color=discord.Color.red(),
                )
                embed.add_field(name="New Balance", value=f"**{new_bal:,} pts**", inline=True)
                await interaction.response.send_message(embed=embed)

                await self._log_activity(
                    title="👑 Admin Point Adjustment",
                    description=f"**{interaction.user.display_name}** deducted **-{amount:,} pts** from **{member.display_name}** ({reason}).",
                    color=discord.Color.orange(),
                )
            except InsufficientPointsError as e:
                await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="admin-export", description="[Admin] Export the entire Uno Rewards database to a CSV spreadsheet file.")
    @app_commands.default_permissions(administrator=True)
    async def admin_export(self, interaction: discord.Interaction) -> None:
        """Export database as CSV file."""
        if not self._check_admin_permissions(interaction):
            await interaction.response.send_message(
                "⛔ **Access Denied**: You must be a Server Administrator to use this command.",
                ephemeral=True,
            )
            return

        csv_data = self.rewards_service.export_csv()
        file = discord.File(
            fp=io.BytesIO(csv_data.encode("utf-8")),
            filename=f"uno_rewards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        await interaction.response.send_message("📊 Here is the updated Uno Rewards database export:", file=file, ephemeral=True)

    @app_commands.command(name="trivia", description="Answer a CS, Programming, or PLM trivia quiz to earn +50 Uno Points! (Max 3/day)")
    async def trivia(self, interaction: discord.Interaction) -> None:
        """Play a trivia quiz question."""
        user_id = interaction.user.id
        user = self.rewards_service.get_or_create_user(user_id)
        today_str = datetime.now(PHT).strftime("%Y-%m-%d")

        if user.last_trivia_date == today_str and user.daily_trivia_count >= 3:
            await interaction.response.send_message(
                "⏳ You have already completed all **3** of your trivia quizzes for today!\n"
                "Come back tomorrow after midnight PHT to earn more points.",
                ephemeral=True,
            )
            return

        _, question = self.rewards_service.get_random_trivia_question(user_id=user_id)
        is_tf = set(opt.lower() for opt in question.options) == {"true", "false"}
        if is_tf:
            options_formatted = "• **✅ True**\n• **❌ False**"
        else:
            letters = ["A", "B", "C", "D"]
            options_formatted = "\n".join(
                f"**{letters[i]}.** {opt}" for i, opt in enumerate(question.options)
            )

        remaining_before = 3 - (user.daily_trivia_count if user.last_trivia_date == today_str else 0)

        embed = discord.Embed(
            title=f"🧠 Uno Daily Trivia — {question.category}",
            description=(
                f"**{question.question}**\n\n"
                f"{options_formatted}\n\n"
                f"💰 **Reward:** `+50 Uno Points` on correct answer\n"
                f"🎯 **Quizzes Remaining Today:** `{remaining_before} / 3`"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Click the button below matching your answer! • Timeout: 2 minutes")

        view = TriviaView(
            rewards_service=self.rewards_service,
            user_id=user_id,
            question=question,
            cog=self,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="guide", description="Complete guide on how to earn points, gamble, duel, adopt pets, and redeem prizes!")
    async def guide(self, interaction: discord.Interaction) -> None:
        """Display the complete student game guide for Uno Rewards."""
        embed = discord.Embed(
            title="🎮 Uno AI Rewards, Casino, Pets & PvP — Complete Student Guide",
            description=(
                "Welcome to the **BSCS 1-4 Uno Rewards & Gamification Universe**! Earn points, "
                "adopt companions, gamble in the casino, clash in 1v1 PvP duels, place student bounties, and redeem real-world prizes!"
            ),
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="📅 1. How to Earn Points & Side Hustles",
            value=(
                "• **`/daily` or `!daily`**: Daily attendance check-in (+30 base + streak bonus up to +35 pts, 2x with Cat companion!).\n"
                "• **`/work` or `!work`**: Work a campus shift (1h cooldown, earn 40–120 pts + rare card drops).\n"
                "• **`/beg` or `!beg`**: Scavenge pocket change across campus (30m cooldown, 10–40 pts).\n"
                "• **`/trivia` or `!trivia`**: Answer CS & Tech quizzes for **`+50 Uno Points`** each (max 3/day, +75 pts with Owl companion)!\n"
                "• **`/give @user <amount>` or `!give`**: Transfer points directly to a classmate from your wallet (min 10 pts).\n"
                "• **`/steal @user` or `!steal`**: Use a *Pickpocket Card* to steal 40%–60% points from an unshielded classmate!"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎰 2. High-Stakes Casino & Street Bets",
            value=(
                "• **`/bet [amount]` or `!bet`**: High-roller roulette gamble with up to 4x payout & skill drops.\n"
                "• **`/slots [amount]` or `!slots`**: 3-Reel classic slots with up to 20x Uno Wild Jackpot.\n"
                "• **`/coinflip <heads|tails> [amount]` or `!cf`**: 1.70x payout coinflip.\n"
                "• **`/blackjack [amount]` or `!bj`**: Interactive Blackjack 21 with Hit, Stand, Double Down.\n"
                "• **`/highlow [amount]` or `!hl`**: Climb the card guessing ladder for up to 30x multiplier!\n"
                "• **`/cups <1|2|3> [amount]` or `!cups`**: Intramuros 3-Cup Shell Game (Unlimited Wagers)!"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚔️ 3. 1v1 PvP Duels & Classroom Bounties",
            value=(
                "• **`/duel @user [amount] [mode]`**: Challenge a classmate across 4 game modes:\n"
                "  🎲 **Dice Roll** · ✂️ **Rock-Paper-Scissors** · 🃏 **Uno Russian Roulette** · ⚔️ **100 HP RPG Arena**\n"
                "• **`/bounty place @target <amount>`**: Place a wanted bounty on a classmate (min 50 pts).\n"
                "• **`/bounty list`**: View the Most Wanted board. Defeating a bountied classmate in ANY duel awards **100% of their bounty pool**!\n"
                "• **🔁 Double-or-Nothing**: Defeated duelists get a 20s rematch button to double the stakes!"
            ),
            inline=False,
        )

        embed.add_field(
            name="🐾 4. Pet Companions & Shelter",
            value=(
                "• **`/pet starter`**: Claim **1 FREE Starter Companion (0 pts)** (Tuxedo Cat, Golden Dog, or Lop-Eared Bunny)!\n"
                "• **Discounted Adoption**: 🐱 Cats & 🐶 Dogs (`50 pts`), Calico/Shiba (`100 pts`), Bunnies/Owls/Turtles/Foxes/Axolotls (`150-250 pts`).\n"
                "• **Passive Perks**: 2x daily claims, guard dog anti-theft, casino luck boosts, cashback, and trivia bonuses.\n"
                "• **Duel Battle Perks**: Dog intimidation (-15 roll/DMG), Bunny lucky rerolls, Owl clutch roll bonus, Fox loss siphon!\n"
                "• **Care & Shelter**: `/pet view` (feed & cuddle), `/pet switch`, `/pet sell`, `/pet drop`, `/pet guide`."
            ),
            inline=False,
        )

        embed.add_field(
            name="🛡️ 5. Bank Vault & Special Skill Cards",
            value=(
                "• **`/bank <deposit|withdraw|view>`**: Protected bank vault 100% immune to theft and audits.\n"
                "• **`🛡️ 1-Week Immunity Shield`**: Deflects all `/steal` robbery attempts for 7 days!\n"
                "• **`🔄 Uno Reverse Card`**: Counter-steals 40%–60% from anyone who attempts to steal from you!\n"
                "• **`🌧️ Point Airdrop`**: Launches a 100 pt community care package in chat (+25 pts each for 4 catchers)!\n"
                "• **`📦 Mystery Gacha Box`**: Lucky lootbox with rewards up to 1,000 points and rare cards!\n"
                "• **`🔨 EMP Shield Breaker`**: Shatter a classmate's active Immunity Shield (`/use shield_breaker @user`)!\n"
                "• **`🕵️ Class Treasurer Audit`**: Audit a 5% Class Tax from a Top-3 Leaderboard player (`/use tax_audit @user`)!"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎁 6. Prize Catalog (`/shop` or `!shop`)",
            value=(
                "• `50,000 pts` — **☕ Intramuros Coffee Treat** (7-Eleven / Lawson)\n"
                "• `65,000 pts` — **💳 GCash Gift Card ₱100**\n"
                "• `80,000 pts` — **🖨️ Free Printing Service (1 Month)**\n"
                "• `100,000 pts` — **🚀 1 Month Discord Nitro**\n"
                "• *Redeem with `/redeem <item>` or `!redeem <item>`!*"
            ),
            inline=False,
        )

        embed.set_footer(text="BSCS 1-4 • Pamantasan ng Lungsod ng Maynila • Built by Jansen")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="milestone", description="Display the official Uno AI Rewards & Economy launch announcement milestone.")
    async def milestone(self, interaction: discord.Interaction) -> None:
        """Display the official production milestone announcement."""
        embed = discord.Embed(
            title="🎉 PRODUCTION MILESTONE: UNO CASINO, PETS & MEGA PVP EXPANSION",
            description=(
                "**Uno AI Gamification, Casino, Pet Companions & PvP Duels are officially live 🟢**\n\n"
                "Earn Uno Points daily, adopt pixel-art companions (including 1 FREE Starter Pet!), gamble in the casino, "
                "clash in 4-mode PvP duels, place classroom bounties, store savings in bank vaults, and redeem real-world student rewards!\n\n"
                "**🐾 PET COMPANIONS & FREE STARTER (50%+ DISCOUNT)**\n"
                "• 🐱 **Cats**: 2x permanent daily claim boost (`50 pts` / `100 pts` Calico)\n"
                "• 🐶 **Dogs**: Guard dog protection against thieves & -15 roll duel bark (`50 pts` / `100 pts` Shiba)\n"
                "• 🐰 **Bunnies**: Passive luck edge in casino wagers & lucky duel rerolls (`150 pts`)\n"
                "• 🦉 **Owls**: 1.5x bonus trivia points & clutch roll duel bonus (`150 pts`)\n"
                "• 🎁 **Claim Free Starter Companion**: `/pet starter` (0 pts cost!)\n"
                "• 🔄 **Shelter & 3-Day Drops**: `/pet drop`, `/pet adopt`, `/pet switch`, `/pet sell`, `/pet guide`\n\n"
                "**⚔️ 1v1 MEGA DUELS & CLASSROOM BOUNTIES**\n"
                "• 🎮 **4 Duel Modes**: `/duel @classmate [amount] [dice|rps|roulette|rpg]`\n"
                "• 🎯 **Classroom Bounties**: `/bounty place @target <amount>` & `/bounty list` (winner claims 100% bounty pot!)\n"
                "• 🔁 **Double-or-Nothing Rematches**: Instant 2x rematch button for defeated duelists\n\n"
                "**🎰 CASINO & HIGH-STAKES GAMBLING (UNLIMITED WAGERS)**\n"
                "• 🎰 **Unlimited Roulette**: `/bet [amount]` (up to 5x Mega Jackpot!)\n"
                "• 🍒 **3-Reel Slots**: `/slots [amount]` (up to 50x Uno Wild Jackpot!)\n"
                "• 🃏 **Interactive Blackjack 21**: `/blackjack [amount]` (Hit, Stand, Double Down!)\n"
                "• 📈 **High-Low Card Streak**: `/highlow [amount]` (Climb ladder up to 30x max win!)\n"
                "• 🪙 **Coinflip 50/50**: `/coinflip <heads|tails> [amount]`\n\n"
                "**💼 CAMPUS SIDE HUSTLES & BANK VAULTS**\n"
                "• 💻 **Campus Shift / Work**: `/work` (earn 40–120 pts + rare card drops, 1h cooldown)\n"
                "• 🎒 **Campus Scavenge**: `/beg` (find loose change across Intramuros, 30m cooldown)\n"
                "• 🏦 **Piggy Bank Vault**: `/bank deposit|withdraw|view` (100% immune to theft & audits)\n\n"
                "**🏪 REAL-WORLD SHOP & REDEMPTIONS**\n"
                "• ☕ Intramuros Coffee · 💵 GCash ₱100 · 🖨️ 1-Month Printing · 🎒 3k Exam Kit · 💎 Discord Nitro (`/shop`, `/redeem`)\n\n"
                "**🚀 GET STARTED**\n"
                "Claim your free starter with `/pet starter`, check `/daily`, read `/guide`, and test your luck in `/bet` or `/duel`!"
            ),
            color=discord.Color.from_rgb(0, 114, 239),
        )
        embed.set_footer(text="BSCS 1-4 · Pamantasan ng Lungsod ng Maynila · Built by Jansen")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="GitHub Repository ↗", url="https://github.com/cadornajansen/uno-discord-bot"))
        view.add_item(discord.ui.Button(label="Read Documentation ↗", url="https://github.com/cadornajansen/uno-discord-bot#readme"))

        await interaction.response.send_message(embed=embed, view=view)


class RedemptionApprovalView(discord.ui.View):
    """Interactive Admin view for approving or rejecting prize claims."""

    def __init__(self, rewards_service: RewardsDBService, redemption_id: int):
        super().__init__(timeout=None)
        self.rewards_service = rewards_service
        self.redemption_id = redemption_id

    @discord.ui.button(label="Approve Prize", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            res = self.rewards_service.update_redemption_status(self.redemption_id, "APPROVED")
            for item in self.children:
                item.disabled = True

            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value=f"✅ **APPROVED by {interaction.user.display_name}**", inline=False)

            await interaction.response.edit_message(embed=embed, view=self)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Reject & Refund", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            res = self.rewards_service.update_redemption_status(self.redemption_id, "REJECTED")
            for item in self.children:
                item.disabled = True

            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value=f"❌ **REJECTED & REFUNDED ({res['points_spent']:,} pts returned) by {interaction.user.display_name}**", inline=False)

            await interaction.response.edit_message(embed=embed, view=self)
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RewardsCog(bot))
