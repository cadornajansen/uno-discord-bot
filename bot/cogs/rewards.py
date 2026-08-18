from datetime import datetime, timezone
import io
import logging
import math
from pathlib import Path
from typing import Any, Optional
import discord
from discord import app_commands
from discord.ext import commands

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
)

logger = logging.getLogger(__name__)


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
        embed.set_footer(text="Browse companions with /shop or adopt with /pet adopt <species>")
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
    pet_img_path = Path("data/pets") / pet.image_file
    if pet_img_path.exists():
        file_attachment = discord.File(str(pet_img_path), filename=pet.image_file)
        embed.set_thumbnail(url=f"attachment://{pet.image_file}")

    embed.set_footer(text="Use buttons below to feed or pet • Switch companion with dropdown")
    return embed, file_attachment


class PetCareButton(discord.ui.Button):
    """Button to feed or cuddle active companion."""

    def __init__(self, action: str, label: str, emoji: str, style: discord.ButtonStyle = discord.ButtonStyle.primary):
        super().__init__(label=label, emoji=emoji, style=style, custom_id=f"pet_care_{action}")
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "PetView" = self.view  # type: ignore
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ This is not your pet companion!", ephemeral=True)
            return

        try:
            res = view.rewards_service.interact_pet(interaction.user.id, action=self.action)
            updated_pet = view.rewards_service.get_active_pet(interaction.user.id)
            all_pets = view.rewards_service.get_user_pets(interaction.user.id)
            embed, _ = build_pet_embed(updated_pet, interaction.user.display_name, all_pets)
            view.update_components(all_pets)

            await interaction.response.edit_message(embed=embed, view=view)
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
        view: "PetView" = self.view  # type: ignore
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ This is not your pet companion!", ephemeral=True)
            return

        pet_id = self.values[0]
        try:
            switched = view.rewards_service.switch_active_pet(interaction.user.id, pet_id)
            all_pets = view.rewards_service.get_user_pets(interaction.user.id)
            embed, _ = build_pet_embed(switched, interaction.user.display_name, all_pets)
            view.update_components(all_pets)

            await interaction.response.edit_message(embed=embed, view=view)
            await interaction.followup.send(
                f"✨ Switched active companion to **{switched.nickname}** ({switched.display_name})!\n"
                f"Active Perk: **{switched.perk_title}**",
                ephemeral=True,
            )
        except RewardsError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class PetView(discord.ui.View):
    """Interactive pet companion dashboard."""

    def __init__(
        self,
        rewards_service: RewardsDBService,
        user_id: int,
        user_pets: list[PetRecord],
    ):
        super().__init__(timeout=180.0)
        self.rewards_service = rewards_service
        self.user_id = user_id
        self.update_components(user_pets)

    def update_components(self, user_pets: list[PetRecord]) -> None:
        self.clear_items()
        self.add_item(PetCareButton("feed", "Feed Snack", "🍖", discord.ButtonStyle.success))
        self.add_item(PetCareButton("pet", "Cuddle & Pet", "💖", discord.ButtonStyle.primary))

        if len(user_pets) > 1:
            self.add_item(PetSwitchSelect(user_pets))


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

        featured_text = (
            "• **🐾 Pet Shelter Companions** (`500–950 pts`) — *Permanent passive buffs & cute profile badges!*\n"
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

    embed.set_footer(text="Select an item in the Quick-Buy dropdown below or use /redeem <item>")
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
        self.rewards_service: RewardsDBService = getattr(
            bot, "rewards_service", RewardsDBService(getattr(bot.settings, "rewards_db_path", "data/rewards.db"))
        )

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
            pet_img_path = Path("data/pets") / pet.image_file
            if pet_img_path.exists():
                file_attachment = discord.File(str(pet_img_path), filename=pet.image_file)
                embed.set_thumbnail(url=f"attachment://{pet.image_file}")

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

    @pet_group.command(name="view", description="View and care for your active pet companion.")
    async def pet_view(self, interaction: discord.Interaction) -> None:
        """Display pet companion dashboard."""
        active = self.rewards_service.get_active_pet(interaction.user.id)
        all_pets = self.rewards_service.get_user_pets(interaction.user.id)
        embed, file_att = build_pet_embed(active, interaction.user.display_name, all_pets)
        view = PetView(self.rewards_service, interaction.user.id, all_pets)
        if file_att:
            await interaction.response.send_message(embed=embed, file=file_att, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @pet_group.command(name="adopt", description="Adopt a new pet companion from the shelter.")
    @app_commands.describe(
        pet="The species/variant of pet you want to adopt.",
        nickname="Optional custom nickname for your pet.",
    )
    @app_commands.choices(pet=[
        app_commands.Choice(name="🐱 Tuxedo Cat (500 pts)", value="tuxedo_cat"),
        app_commands.Choice(name="🐱 Fluffy Calico Cat (550 pts)", value="calico_cat"),
        app_commands.Choice(name="🐶 Golden Retriever (550 pts)", value="golden_dog"),
        app_commands.Choice(name="🐶 Shiba Inu (580 pts)", value="shiba_dog"),
        app_commands.Choice(name="🐰 Lop-Eared Bunny (600 pts)", value="brown_bunny"),
        app_commands.Choice(name="🐰 Moon Rabbit (650 pts)", value="white_bunny"),
        app_commands.Choice(name="🦉 Scholar Owl (500 pts)", value="scholar_owl"),
        app_commands.Choice(name="🦉 Frost Owl (550 pts)", value="ice_owl"),
        app_commands.Choice(name="🐢 Master Oogway Turtle (600 pts)", value="oogway_turtle"),
        app_commands.Choice(name="🦊 Trickster Fox (650 pts)", value="orange_fox"),
        app_commands.Choice(name="🦊 Arctic Ice Fox (700 pts)", value="ice_fox"),
        app_commands.Choice(name="🦎 Pastel Pink Axolotl (750 pts)", value="pink_axolotl"),
        app_commands.Choice(name="🦎 Rainbow Axolotl (950 pts)", value="rainbow_axolotl"),
        app_commands.Choice(name="🐠 Fiery Lucky Goldfish (800 pts)", value="fiery_goldfish"),
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

            pet_img_path = Path("data/pets") / res.image_file
            if pet_img_path.exists():
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

    @app_commands.command(name="bet", description="Gamble 50 Uno Points for double points, skill drops, or bust! (Max 3/day)")
    async def bet(self, interaction: discord.Interaction) -> None:
        """Play 50 pt roulette minigame."""
        user_id = interaction.user.id
        try:
            res = self.rewards_service.play_bet(user_id)

            if res.outcome in (BetOutcome.JACKPOT, BetOutcome.DOUBLE):
                title = "🎰 JACKPOT! Mega Win! (+200 pts)"
                desc = (
                    f"🎉 **JACKPOT!** You kept your **50 pts** bet and won **+200 Uno Points**!\n"
                    f"💰 **Total Return:** `250 pts` (Net Gain: **+200 pts**)"
                )
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

    @app_commands.command(name="guide", description="Complete guide on how to earn points, gamble, steal, and redeem prizes in Uno!")
    async def guide(self, interaction: discord.Interaction) -> None:
        """Display the complete student game guide for Uno Rewards."""
        embed = discord.Embed(
            title="🎮 Uno AI Rewards & Economy — Complete Student Guide",
            description=(
                "Welcome to the **BSCS 1-4 Uno Rewards System**! Earn points by interacting, "
                "competing on the leaderboard, answering daily trivia, and redeeming real-world prizes!"
            ),
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="📅 1. How to Earn Points",
            value=(
                "• **`/daily` or `!daily`**: Claim your daily attendance reward (+30 pts base + 5 pts/day of streak, max +35 pts bonus!).\n"
                "• **`/trivia` or `!trivia`**: Answer CS & Tech quizzes for **`+50 Uno Points`** each (max 3/day, no cooldown)!\n"
                "• **`/bet` or `!bet`**: Risk 50 pts on roulette (max 3/day). 25% Jackpot (+200 pts net!), 25% Skill Drop, 15% Refund, 35% Bust.\n"
                "• **`/steal @user` or `!steal`**: Use a *Pickpocket Card* to steal 40%–60% points from an unshielded classmate!"
            ),
            inline=False,
        )

        embed.add_field(
            name="🛡️ 2. Protection & Special Skill Cards",
            value=(
                "• **`/inventory` or `!inv`**: Inspect your owned skill cards.\n"
                "• **`🛡️ 1-Week Immunity Shield`**: Deflects all `/steal` robbery attempts for 7 days!\n"
                "• **`🔄 Uno Reverse Card`**: Passive trap! Counter-steals 40%–60% from anyone who attempts to steal from you!\n"
                "• **`🌧️ Point Airdrop`**: Launches a 100 pt community care package in chat (+25 pts each for 4 catchers)!\n"
                "• **`📦 Mystery Gacha Box`**: Lucky lootbox with rewards up to 1,000 points and rare cards!\n"
                "• **`🔨 EMP Shield Breaker`**: Target a protected classmate (`/use shield_breaker @user`) to shatter their Immunity Shield!\n"
                "• **`🕵️ Class Treasurer Audit`**: Audit a 5% Class Tax from a Top-3 Leaderboard player (`/use tax_audit @user`)!\n"
                "• **`☕ Dean's Coffee Bribe`**: Instant grant of +100 to +180 Uno Points!"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎁 3. Prize Catalog (`/shop` or `!shop`)",
            value=(
                "• `1,200 pts` — **☕ Intramuros Coffee Treat** (7-Eleven / Lawson)\n"
                "• `2,200 pts` — **💳 GCash Gift Card ₱100**\n"
                "• `2,800 pts` — **🖨️ Free Printing Service (1 Month)**\n"
                "• `3,000 pts` — **🍫 Exams Survival Kit** *(FREE Milestone Auto-Unlock!)*\n"
                "• `5,500 pts` — **🚀 1 Month Discord Nitro**\n"
                "• *Redeem with `/redeem <item>` or `!redeem <item>`!*"
            ),
            inline=False,
        )

        embed.add_field(
            name="📊 4. Profiles & Leaderboard",
            value=(
                "• **`/balance` / `!bal`**: Check wallet balance, streak, and shield status.\n"
                "• **`/profile` / `!profile`**: View student rank, badges, and inventory.\n"
                "• **`/rank` / `!rank`**: Compact Top 10 members today.\n"
                "• **`/leaderboard` / `!lb`**: Full class ranking with interactive page buttons."
            ),
            inline=False,
        )

        embed.set_footer(text="BSCS 1-4 • Pamantasan ng Lungsod ng Maynila • Built by Jansen")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="milestone", description="Display the official Uno AI Rewards & Economy launch announcement milestone.")
    async def milestone(self, interaction: discord.Interaction) -> None:
        """Display the official production milestone announcement."""
        embed = discord.Embed(
            title="✅ PRODUCTION MILESTONE: UNO REWARDS & GAMIFICATION",
            description=(
                "**Uno AI Gamification & Rewards System is officially live 🟢**\n\n"
                "Earn Uno Points every day, answer daily trivia, climb the student leaderboards, roll the roulette, "
                "protect your wallet with Immunity Shields, and redeem real-world student perks!\n\n"
                "**ECONOMY FEATURES**\n"
                "• 📅 Daily Attendance & Streak Bonus (`/daily` or `!daily`)\n"
                "• 🧠 Daily CS Trivia Quizzes (`/trivia` or `!trivia` — +50 pts, max 3/day)\n"
                "• 🎰 50pt Roulette Gambling (`/bet` or `!bet`)\n"
                "• 🦹 Pickpocket Robberies & 1-Week Shields (`/steal`, `/use`)\n"
                "• 🏆 Paginated Class Leaderboard (`/leaderboard` or `!lb`)\n"
                "• 🏪 Prize Shop & Real Redemptions (`/shop`, `/redeem`)\n\n"
                "**REDEEMABLE PERKS**\n"
                "Intramuros Coffee · GCash ₱100 · 1-Month Printing · 3k Exam Kit · Discord Nitro\n\n"
                "**GET STARTED**\n"
                "Run `/guide` or `!guide` to learn all game mechanics and claim your first `/daily`!"
            ),
            color=discord.Color.from_rgb(0, 114, 239),
        )
        embed.set_footer(text="BSCS 1-4 · Built for the block. Now living in the cloud.")

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
