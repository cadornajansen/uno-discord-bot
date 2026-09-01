from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.community_games import CommunityGamesService
from bot.services.rewards_db import RewardsDBService, RewardsError


def _activity_text(activity: dict) -> str:
    players = " ".join(f"<@{item['user_id']}>" for item in activity["participants"])
    return (
        f"**Status:** {activity['status']}\n"
        f"**Stage:** {int(activity['stage']) + 1}\n"
        f"**Players:** {players or 'None'}\n\n"
        f"**Challenge:** {activity['prompt']}"
    )


def _startup_text(project: dict) -> str:
    return (
        f"**{project['name']}** — Phase {project['phase']}/3\n"
        f"Budget: `{project['budget']}` · Quality: `{project['quality']}` · "
        f"Research: `{project['research']}` · Reputation: `{project['reputation']}`\n"
        f"Contributions this phase: `{project['contributions']}`"
    )


class CommunityCog(commands.Cog):
    """Persistent cooperative games and the Campus Review Board."""

    raid_group = app_commands.Group(name="raid", description="Run cooperative academic Study Raids.")
    escape_group = app_commands.Group(name="escape", description="Play persistent coding escape rooms.")
    startup_group = app_commands.Group(name="startup", description="Manage a guild campus startup.")
    review_group = app_commands.Group(name="review", description="Review bot-recorded economy disputes.")
    economy_group = app_commands.Group(name="economy", description="View Uno economy reporting.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        rewards = getattr(bot, "rewards_service", None)
        if not isinstance(rewards, RewardsDBService):
            raise RuntimeError("CommunityCog requires the shared RewardsDBService.")
        self.service = CommunityGamesService(rewards)

    @staticmethod
    def _server_id(interaction: discord.Interaction) -> int:
        if not interaction.guild_id:
            raise RewardsError("This activity can only run inside a server.")
        return interaction.guild_id

    async def _send_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.response.send_message(str(error), ephemeral=True)

    @raid_group.command(name="create", description="Open a 2–8 player Study Raid lobby.")
    async def raid_create(self, interaction: discord.Interaction) -> None:
        try:
            activity = self.service.create_activity(self._server_id(interaction), interaction.user.id, "raid")
            await interaction.response.send_message("Study Raid lobby opened. Use `/raid join`, then `/raid launch`.\n\n" + _activity_text(activity))
        except RewardsError as error:
            await self._send_error(interaction, error)

    @raid_group.command(name="join", description="Join the open Study Raid lobby.")
    async def raid_join(self, interaction: discord.Interaction) -> None:
        try:
            activity = self.service.join_activity(self._server_id(interaction), interaction.user.id, "raid")
            await interaction.response.send_message(f"{interaction.user.mention} joined the Study Raid.\n\n{_activity_text(activity)}")
        except RewardsError as error:
            await self._send_error(interaction, error)

    @raid_group.command(name="launch", description="Launch the Study Raid lobby you created.")
    async def raid_launch(self, interaction: discord.Interaction) -> None:
        try:
            activity = self.service.launch_raid(self._server_id(interaction), interaction.user.id)
            await interaction.response.send_message("Study Raid launched.\n\n" + _activity_text(activity))
        except RewardsError as error:
            await self._send_error(interaction, error)

    @raid_group.command(name="status", description="Show the active Study Raid.")
    async def raid_status(self, interaction: discord.Interaction) -> None:
        try:
            activity = self.service.get_activity(self._server_id(interaction), "raid")
            await interaction.response.send_message(_activity_text(activity))
        except RewardsError as error:
            await self._send_error(interaction, error)

    @raid_group.command(name="answer", description="Submit your answer for the current raid stage.")
    async def raid_answer(self, interaction: discord.Interaction, answer: str) -> None:
        try:
            update = self.service.answer_activity(self._server_id(interaction), interaction.user.id, "raid", answer)
            await interaction.response.send_message(update.message)
        except RewardsError as error:
            await self._send_error(interaction, error)

    @escape_group.command(name="create", description="Open a 1–4 player coding escape room.")
    async def escape_create(self, interaction: discord.Interaction) -> None:
        try:
            activity = self.service.create_activity(self._server_id(interaction), interaction.user.id, "escape")
            await interaction.response.send_message("Coding Escape Room opened.\n\n" + _activity_text(activity))
        except RewardsError as error:
            await self._send_error(interaction, error)

    @escape_group.command(name="join", description="Join the active coding escape room.")
    async def escape_join(self, interaction: discord.Interaction) -> None:
        try:
            activity = self.service.join_activity(self._server_id(interaction), interaction.user.id, "escape")
            await interaction.response.send_message(f"{interaction.user.mention} joined.\n\n{_activity_text(activity)}")
        except RewardsError as error:
            await self._send_error(interaction, error)

    @escape_group.command(name="status", description="Show the active coding escape room.")
    async def escape_status(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.send_message(_activity_text(self.service.get_activity(self._server_id(interaction), "escape")))
        except RewardsError as error:
            await self._send_error(interaction, error)

    @escape_group.command(name="answer", description="Submit an answer for the current room.")
    async def escape_answer(self, interaction: discord.Interaction, answer: str) -> None:
        try:
            update = self.service.answer_activity(self._server_id(interaction), interaction.user.id, "escape", answer)
            await interaction.response.send_message(update.message)
        except RewardsError as error:
            await self._send_error(interaction, error)

    @escape_group.command(name="hint", description="Reveal a hint, reducing the final reward.")
    async def escape_hint(self, interaction: discord.Interaction) -> None:
        try:
            hint = self.service.use_escape_hint(self._server_id(interaction), interaction.user.id)
            await interaction.response.send_message(f"Hint: {hint}")
        except RewardsError as error:
            await self._send_error(interaction, error)

    @startup_group.command(name="start", description="Start a three-phase project for your guild.")
    async def startup_start(self, interaction: discord.Interaction, name: str) -> None:
        try:
            project = self.service.start_startup(self._server_id(interaction), interaction.user.id, name)
            await interaction.response.send_message("Campus startup created.\n\n" + _startup_text(project))
        except RewardsError as error:
            await self._send_error(interaction, error)

    @startup_group.command(name="contribute", description="Contribute once during the current project phase.")
    @app_commands.choices(action=[
        app_commands.Choice(name="Build", value="build"),
        app_commands.Choice(name="Research", value="research"),
        app_commands.Choice(name="Market", value="market"),
        app_commands.Choice(name="Stabilize", value="stabilize"),
    ])
    async def startup_contribute(self, interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
        try:
            project = self.service.contribute_startup(self._server_id(interaction), interaction.user.id, action.value)
            await interaction.response.send_message(f"Contribution recorded: **{action.name}**.\n\n{_startup_text(project)}")
        except RewardsError as error:
            await self._send_error(interaction, error)

    @startup_group.command(name="status", description="Show your guild's current startup project.")
    async def startup_status(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.send_message(_startup_text(self.service.get_startup(self._server_id(interaction), interaction.user.id)))
        except RewardsError as error:
            await self._send_error(interaction, error)

    @startup_group.command(name="advance", description="Advance your guild project after contributions are complete.")
    async def startup_advance(self, interaction: discord.Interaction) -> None:
        try:
            update = self.service.advance_startup(self._server_id(interaction), interaction.user.id)
            await interaction.response.send_message(update.message)
        except RewardsError as error:
            await self._send_error(interaction, error)

    @review_group.command(name="file", description="File a review for one of your bot-recorded transactions.")
    async def review_file(self, interaction: discord.Interaction, target: discord.Member, transaction_id: int, reason: str) -> None:
        try:
            case = self.service.file_review(self._server_id(interaction), interaction.user.id, target.id, transaction_id, reason)
            await interaction.response.send_message(f"Campus Review case **#{case['id']}** filed. {target.mention} has 24 hours to respond.")
        except RewardsError as error:
            await self._send_error(interaction, error)

    @review_group.command(name="history", description="List your latest transactions eligible for Campus Review.")
    async def review_history(self, interaction: discord.Interaction) -> None:
        transactions = self.service.get_reviewable_transactions(interaction.user.id)
        if not transactions:
            await interaction.response.send_message("You have no recent transactions eligible for review.", ephemeral=True)
            return
        lines = [
            f"`#{item['id']}` · `{item['amount']:+,} pts` · {item['action_type']} · {item['description']}"
            for item in transactions
        ]
        await interaction.response.send_message(
            "**Your reviewable transactions**\n" + "\n".join(lines),
            ephemeral=True,
        )

    @review_group.command(name="respond", description="Respond to a Campus Review case filed against you.")
    async def review_respond(self, interaction: discord.Interaction, case_id: int, response: str) -> None:
        try:
            case = self.service.respond_review(
                case_id,
                interaction.user.id,
                response,
                server_id=self._server_id(interaction),
            )
            await interaction.response.send_message(f"Response recorded for case **#{case['id']}**.", ephemeral=True)
        except RewardsError as error:
            await self._send_error(interaction, error)

    @review_group.command(name="status", description="View a Campus Review case.")
    async def review_status(self, interaction: discord.Interaction, case_id: int) -> None:
        try:
            case = self.service.get_review(case_id, server_id=self._server_id(interaction))
            await interaction.response.send_message(
                f"**Case #{case['id']} — {case['status']}**\n"
                f"Filer: <@{case['filer_id']}> · Respondent: <@{case['target_id']}>\n"
                f"Transaction: `{case['transaction_id']}`\nReason: {case['reason']}\n"
                f"Response: {case['response'] or 'No response yet'}\n"
                f"Resolution: {case['resolution'] or 'Pending'}"
            )
        except RewardsError as error:
            await self._send_error(interaction, error)

    @review_group.command(name="resolve", description="Resolve a Campus Review case. Moderators only.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(decision=[
        app_commands.Choice(name="Dismiss", value="dismiss"),
        app_commands.Choice(name="Uphold", value="uphold"),
        app_commands.Choice(name="Refund", value="refund"),
    ])
    async def review_resolve(self, interaction: discord.Interaction, case_id: int, decision: app_commands.Choice[str], note: str) -> None:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not permissions or not (permissions.manage_guild or permissions.administrator):
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        try:
            case = self.service.resolve_review(
                case_id,
                interaction.user.id,
                decision.value,
                note,
                server_id=self._server_id(interaction),
            )
            await interaction.response.send_message(f"Case **#{case_id}** resolved: **{decision.name}**. Refunded: `{case['refunded']} pts`.")
        except RewardsError as error:
            await self._send_error(interaction, error)

    @economy_group.command(name="pulse", description="Generate the current six-hour Uno economy pulse.")
    async def economy_pulse(self, interaction: discord.Interaction) -> None:
        report = self.service.capture_economy_pulse()
        await interaction.response.send_message(self.format_pulse(report))

    @staticmethod
    def format_pulse(report: dict[str, object]) -> str:
        movements = report["movements"]
        movement_lines = []
        for item in movements:
            movement = item["movement"]
            label = "new Top 10 entry" if movement is None else (f"up {movement}" if movement > 0 else f"down {abs(movement)}")
            movement_lines.append(f"<@{item['user_id']}>: {label}, now #{item['rank']}")
        growth_lines = []
        for item in report["growth"]:
            percentage = f" ({item['percent']:+}%)" if item["percent"] is not None else " (newly active)"
            growth_lines.append(f"<@{item['user_id']}>: {item['delta']:+,} pts{percentage}")
        return (
            f"**Uno Economy Pulse — Last {report['hours']} Hours**\n"
            f"Earned: `{report['earned']:,}` · Spent: `{report['spent']:,}` · Transactions: `{report['transactions']}`\n"
            f"Study sessions: `{report['study_sessions']}` · Casino rounds: `{report['casino_rounds']}` · Win rate: `{report['casino_win_rate']}%`\n\n"
            f"**Leaderboard movement**\n" + ("\n".join(movement_lines) or "No rank changes yet.") + "\n\n"
            f"**Growth**\n" + ("\n".join(growth_lines) or "No major gains in this window.")
        )

    @commands.group(name="raid", invoke_without_command=True)
    @commands.guild_only()
    async def raid_prefix(self, context: commands.Context) -> None:
        await context.reply("Use `!raid create|join|launch|status|answer <text>`. ")

    @raid_prefix.command(name="create")
    async def raid_create_prefix(self, context: commands.Context) -> None:
        await context.reply("Study Raid lobby opened.\n\n" + _activity_text(self.service.create_activity(context.guild.id, context.author.id, "raid")))

    @raid_prefix.command(name="join")
    async def raid_join_prefix(self, context: commands.Context) -> None:
        await context.reply(_activity_text(self.service.join_activity(context.guild.id, context.author.id, "raid")))

    @raid_prefix.command(name="launch")
    async def raid_launch_prefix(self, context: commands.Context) -> None:
        await context.reply(_activity_text(self.service.launch_raid(context.guild.id, context.author.id)))

    @raid_prefix.command(name="status")
    async def raid_status_prefix(self, context: commands.Context) -> None:
        await context.reply(_activity_text(self.service.get_activity(context.guild.id, "raid")))

    @raid_prefix.command(name="answer")
    async def raid_answer_prefix(self, context: commands.Context, *, answer: str) -> None:
        await context.reply(self.service.answer_activity(context.guild.id, context.author.id, "raid", answer).message)

    @commands.group(name="escape", invoke_without_command=True)
    @commands.guild_only()
    async def escape_prefix(self, context: commands.Context) -> None:
        await context.reply("Use `!escape create|join|status|answer <text>|hint`.")

    @escape_prefix.command(name="create")
    async def escape_create_prefix(self, context: commands.Context) -> None:
        await context.reply(_activity_text(self.service.create_activity(context.guild.id, context.author.id, "escape")))

    @escape_prefix.command(name="join")
    async def escape_join_prefix(self, context: commands.Context) -> None:
        await context.reply(_activity_text(self.service.join_activity(context.guild.id, context.author.id, "escape")))

    @escape_prefix.command(name="status")
    async def escape_status_prefix(self, context: commands.Context) -> None:
        await context.reply(_activity_text(self.service.get_activity(context.guild.id, "escape")))

    @escape_prefix.command(name="answer")
    async def escape_answer_prefix(self, context: commands.Context, *, answer: str) -> None:
        await context.reply(self.service.answer_activity(context.guild.id, context.author.id, "escape", answer).message)

    @escape_prefix.command(name="hint")
    async def escape_hint_prefix(self, context: commands.Context) -> None:
        await context.reply("Hint: " + self.service.use_escape_hint(context.guild.id, context.author.id))

    @commands.group(name="startup", invoke_without_command=True)
    @commands.guild_only()
    async def startup_prefix(self, context: commands.Context) -> None:
        await context.reply("Use `!startup start <name>|contribute <action>|status|advance`.")

    @startup_prefix.command(name="start")
    async def startup_start_prefix(self, context: commands.Context, *, name: str) -> None:
        await context.reply("Campus startup created.\n\n" + _startup_text(self.service.start_startup(context.guild.id, context.author.id, name)))

    @startup_prefix.command(name="contribute")
    async def startup_contribute_prefix(self, context: commands.Context, action: str) -> None:
        await context.reply(_startup_text(self.service.contribute_startup(context.guild.id, context.author.id, action)))

    @startup_prefix.command(name="status")
    async def startup_status_prefix(self, context: commands.Context) -> None:
        await context.reply(_startup_text(self.service.get_startup(context.guild.id, context.author.id)))

    @startup_prefix.command(name="advance")
    async def startup_advance_prefix(self, context: commands.Context) -> None:
        await context.reply(self.service.advance_startup(context.guild.id, context.author.id).message)

    @commands.group(name="review", invoke_without_command=True)
    @commands.guild_only()
    async def review_prefix(self, context: commands.Context) -> None:
        await context.reply("Use `!review history|file <@member> <transaction_id> <reason>|respond|status|resolve`.")

    @review_prefix.command(name="history")
    async def review_history_prefix(self, context: commands.Context) -> None:
        transactions = self.service.get_reviewable_transactions(context.author.id)
        lines = [
            f"`#{item['id']}` · `{item['amount']:+,} pts` · {item['action_type']} · {item['description']}"
            for item in transactions
        ]
        await context.reply("**Your reviewable transactions**\n" + ("\n".join(lines) or "None found."))

    @review_prefix.command(name="file")
    async def review_file_prefix(self, context: commands.Context, target: discord.Member, transaction_id: int, *, reason: str) -> None:
        case = self.service.file_review(context.guild.id, context.author.id, target.id, transaction_id, reason)
        await context.reply(f"Campus Review case **#{case['id']}** filed.")

    @review_prefix.command(name="respond")
    async def review_respond_prefix(self, context: commands.Context, case_id: int, *, response: str) -> None:
        self.service.respond_review(case_id, context.author.id, response, server_id=context.guild.id)
        await context.reply(f"Response recorded for case **#{case_id}**.")

    @review_prefix.command(name="status")
    async def review_status_prefix(self, context: commands.Context, case_id: int) -> None:
        case = self.service.get_review(case_id, server_id=context.guild.id)
        await context.reply(f"Case #{case_id}: **{case['status']}** · {case['resolution'] or 'Pending'}")

    @review_prefix.command(name="resolve")
    @commands.has_permissions(manage_guild=True)
    async def review_resolve_prefix(self, context: commands.Context, case_id: int, decision: str, *, note: str) -> None:
        case = self.service.resolve_review(
            case_id,
            context.author.id,
            decision,
            note,
            server_id=context.guild.id,
        )
        await context.reply(f"Case **#{case_id}** resolved. Refunded: `{case['refunded']} pts`.")

    @commands.group(name="economy", invoke_without_command=True)
    @commands.guild_only()
    async def economy_prefix(self, context: commands.Context) -> None:
        await context.reply("Use `!economy pulse`.")

    @economy_prefix.command(name="pulse")
    async def economy_pulse_prefix(self, context: commands.Context) -> None:
        await context.reply(self.format_pulse(self.service.capture_economy_pulse()))

    async def cog_command_error(self, context: commands.Context, error: commands.CommandError) -> None:
        cause = getattr(error, "original", error)
        if isinstance(cause, RewardsError):
            await context.reply(str(cause))
            return
        raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommunityCog(bot))
