import logging
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

import httpx
from bot.services.ocr import OCRService, is_supported_image
from bot.utils.formatting import format_latency, format_timestamp

logger = logging.getLogger(__name__)


class GeneralCog(commands.Cog):
    """Cog containing general utility slash commands and context menu apps."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.explain_menu = app_commands.ContextMenu(
            name="Explain This",
            callback=self.explain_this,
        )
        self.ocr_menu = app_commands.ContextMenu(
            name="Run OCR",
            callback=self.run_ocr,
        )
        if hasattr(self.bot, "tree") and self.bot.tree is not None:
            self.bot.tree.add_command(self.explain_menu)
            self.bot.tree.add_command(self.ocr_menu)

    async def cog_unload(self) -> None:
        if hasattr(self.bot, "tree") and self.bot.tree is not None:
            self.bot.tree.remove_command(self.explain_menu.name, type=self.explain_menu.type)
            self.bot.tree.remove_command(self.ocr_menu.name, type=self.ocr_menu.type)

    @app_commands.command(name="ping", description="Check the bot WebSocket latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Respond with the bot's current WebSocket latency."""
        latency_str = format_latency(self.bot.latency)
        await interaction.response.send_message(f"Pong! {latency_str}")

    @app_commands.command(name="hello", description="Say hello to the bot.")
    async def hello(self, interaction: discord.Interaction) -> None:
        """Greet the user using their server display name."""
        display_name = interaction.user.display_name
        await interaction.response.send_message(f"Hello, {display_name}!")

    @app_commands.command(name="userinfo", description="Display public information about a user.")
    @app_commands.describe(member="The member to view information for (defaults to you).")
    async def userinfo(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        """Display non-sensitive account metadata for the specified or calling user."""
        target = member or interaction.user

        embed = discord.Embed(
            title=f"User Info - {target.display_name}",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Username", value=target.name, inline=True)
        embed.add_field(name="Display Name", value=target.display_name, inline=True)
        embed.add_field(name="User ID", value=str(target.id), inline=False)
        embed.add_field(
            name="Account Created",
            value=format_timestamp(target.created_at, style="F"),
            inline=True,
        )

        # Server join date is only available when target is a Member within a server context
        if isinstance(target, discord.Member) and target.joined_at:
            embed.add_field(
                name="Joined Server",
                value=format_timestamp(target.joined_at, style="F"),
                inline=True,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Display information about the current server.")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        """Display server metadata (name, owner, member count, creation date)."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=guild.name,
            description="Server Information",
            color=discord.Color.green(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Server ID", value=str(guild.id), inline=True)
        
        # Display owner name if available in cache, otherwise show owner ID
        owner_display = str(guild.owner) if guild.owner else f"ID: {guild.owner_id}"
        embed.add_field(name="Owner", value=owner_display, inline=True)
        
        embed.add_field(name="Members", value=str(guild.member_count), inline=True)
        embed.add_field(
            name="Created On",
            value=format_timestamp(guild.created_at, style="F"),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="List all available commands and descriptions.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        """List all slash commands grouped by feature area."""
        embed = discord.Embed(
            title="Uno AI - Command Reference",
            description=(
                "Use `/` slash commands or their `!` prefix equivalents. "
                "You can also mention Uno naturally. Document commands remain slash-only."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="AI & Knowledge",
            value=(
                "`/ask question:<text>` or `!ask <text>` - Chat with Uno. Class questions can use "
                "assignments, announcements, schedules, subjects, and professor data.\n"
                "`/reset-chat` or `!reset-chat` - Clear only your chat memory in this channel.\n"
                "`/search query:<text>` or `!search <text>` - Search Google and get the top results."
            ),
            inline=False,
        )

        embed.add_field(
            name="Document Analysis",
            value=(
                "`/analyze file:<attachment>` - Upload a PDF or PPTX and get an AI summary.\n"
                "`/docask question:<text>` - Ask a follow-up question about the last analyzed document.\n"
                "These two commands require `/`; `!analyze` and `!docask` provide guidance only."
            ),
            inline=False,
        )

        embed.add_field(
            name="Academic Schedule",
            value=(
                "`/today` or `!today` - Show today's class schedule.\n"
                "`/schedule` or `!schedule` - Show the full weekly schedule.\n"
                "`/nextclass` or `!nextclass` - Show the next upcoming class.\n"
                "`/prof subject:<name>` or `!prof <name>` - Look up the professor for a subject.\n"
                "`/countdown` or `!countdown` - View countdown to upcoming academic milestones."
            ),
            inline=False,
        )

        embed.add_field(
            name="Weather",
            value=(
                "`/weather` or `!weather` - Current conditions, 6-hour forecast, official PAGASA warnings, "
                "and class disruption risk (LOW / MODERATE / HIGH)."
            ),
            inline=False,
        )

        embed.add_field(
            name="💰 Earning & Economy",
            value=(
                "`/daily` or `!daily` - Claim daily attendance points and build streaks.\n"
                "`/work` or `!work` - Work a campus shift (1hr cooldown, 40-120 pts + rare drops).\n"
                "`/beg` or `!beg` - Scavenge pocket change (30m cooldown, 10-40 pts).\n"
                "`/trivia` or `!trivia` - Answer CS/Tech trivia for +50 pts each.\n"
                "`/balance` or `!bal` - Check wallet, streak, and shield status.\n"
                "`/profile [member]` or `!profile` - Full student card, companion, rank, and badges.\n"
                "`/rank` or `!rank` - Quick Top 10 campus leaderboard.\n"
                "`/leaderboard` or `!lb` - Interactive paginated server leaderboard.\n"
                "`/bank <deposit|withdraw|view>` or `!bank` - Bank vault immune to theft.\n"
                "`/steal @member` or `!steal` - Pickpocket Card to steal 40%-60% points."
            ),
            inline=False,
        )

        embed.add_field(
            name="🛒 Shop, Items & Guides",
            value=(
                "`/shop` or `!shop` - Browse prizes and skill card items.\n"
                "`/redeem <item>` or `!redeem` - Redeem prizes (Coffee, GCash, Nitro, Survival Kit).\n"
                "`/inventory` or `!inv` - View owned skill cards and consumables.\n"
                "`/use <item> [@target]` or `!use` - Activate skill cards (Shield, Gacha, Audit, etc.).\n"
                "`/guide` or `!guide` - Complete student guide and handbook.\n"
                "`/milestone` or `!milestone` - Official Uno Rewards launch announcement."
            ),
            inline=False,
        )

        embed.add_field(
            name="🎰 High-Stakes Casino",
            value=(
                "`/bet [amount]` or `!bet` - Unlimited high-roller betting with jackpots and item drops.\n"
                "`/slots [amount]` or `!slots` - 3-Reel slot machine with up to 50x Wild Jackpot.\n"
                "`/coinflip <heads|tails> [amount]` or `!cf` - 50/50 coinflip with 2.0x payout.\n"
                "`/blackjack [amount]` or `!bj` - Blackjack 21 with Hit, Stand, Double Down.\n"
                "`/highlow [amount]` or `!hl` - High-Low card guessing streak up to 30x multiplier."
            ),
            inline=False,
        )

        embed.add_field(
            name="⚔️ 1v1 PvP Duels & Classroom Bounties",
            value=(
                "`/duel @member [amount] [mode]` or `!duel` - Challenge a classmate across 4 game modes (🎲 Dice, ✂️ RPS, 🃏 Russian Roulette, ⚔️ 100 HP RPG Combat)!\n"
                "`/bounty place @member <amount>` or `!bounty place` - Place a wanted bounty on a classmate.\n"
                "`/bounty list` or `!bounty list` - View the Most Wanted classroom bounty board."
            ),
            inline=False,
        )

        embed.add_field(
            name="🐾 Pet Companions & Shelter",
            value=(
                "`/pet` or `!pet` - Pet dashboard to feed, cuddle, level up, and manage companions.\n"
                "`/pet starter` or `!pet starter` - Adopt your 1 Free Starter Companion (0 pts)!\n"
                "`/pet adopt <species>` or `!pet adopt` - Adopt companions with permanent passive perks (Cats, Dogs, Bunnies, Owls, Turtles, Foxes, Axolotls, Goldfish).\n"
                "`/pet list` or `!pet list` - View all pets in your collection.\n"
                "`/pet switch <species>` or `!pet switch` - Switch active companion.\n"
                "`/pet rename <species> <name>` or `!pet rename` - Give your companion a custom nickname.\n"
                "`/pet sell <species>` or `!pet sell` - Sell a companion for points refund.\n"
                "`/pet drop` or `!pet drop` - View the active rotating 3-day pet drop spotlight.\n"
                "`/pet guide` or `!pet guide` - Comprehensive pet companion handbook."
            ),
            inline=False,
        )

        embed.add_field(
            name="General & Utility",
            value=(
                "`/ping` or `!ping` - Check bot latency.\n"
                "`/hello` or `!hello` - Say hi.\n"
                "`/userinfo [member]` or `!userinfo [member]` - View public account info.\n"
                "`/serverinfo` or `!serverinfo` - View details about this server.\n"
                "`/about` or `!about` - Learn how Uno AI works.\n"
                "`/help` or `!help` - Show this command list.\n"
                "**Right-click a message → Apps → Explain This** - AI explanation of any message.\n"
                "**Right-click a message → Apps → Run OCR** - Extract text from an image attachment."
            ),
            inline=False,
        )

        embed.add_field(
            name="Passive Features",
            value=(
                "**Mention Uno with a question** - `@Uno AI what's due Friday?` works anywhere "
                "in the message. A mention by itself gets a quick static reply.\n"
                "**Reply to Uno** - Continue the conversation without repeating the original question.\n"
                "**Private short-term memory** - History is separated by user and channel, bounded, "
                "and expires automatically.\n"
                "**Approved-channel indexing** - New homework and announcement posts become searchable.\n"
                "**Image OCR** - Homework screenshots in approved channels can also be indexed."
            ),
            inline=False,
        )

        embed.set_footer(text="Uno AI - AssemblyAI LLM Gateway + Gemini Embeddings + Qdrant")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="about", description="Learn how Uno AI works in simple terms.")
    async def about_command(self, interaction: discord.Interaction) -> None:
        """Brief explanation of Uno AI's retrieval and generation flow."""
        embed = discord.Embed(
            title="How does Uno AI work?",
            color=discord.Color.og_blurple(),
        )

        embed.add_field(
            name="The short version",
            value=(
                "Uno is a class assistant with short-term per-user memory and a small set of "
                "read-only class tools. Gemini 3.5 Flash generates replies through AssemblyAI's "
                "LLM Gateway."
            ),
            inline=False,
        )

        embed.add_field(
            name="How a chat request works",
            value=(
                "1. Uno loads your small conversation history for this server channel.\n"
                "2. Clear class questions are routed to a trusted read-only tool.\n"
                "3. Assignment searches prefer newer, structured homework and announcement posts.\n"
                "4. Relative dates such as today, tomorrow, and Friday use Asia/Manila.\n"
                "5. Gemini produces the final Discord reply using only the relevant results."
            ),
            inline=False,
        )

        embed.add_field(
            name="What Uno can check",
            value=(
                "Uno can check approved homework and announcement posts, the class schedule, "
                "subject abbreviations, and professor information. General conversation does "
                "not automatically search the class index."
            ),
            inline=False,
        )

        embed.add_field(
            name="Memory, storage, and privacy",
            value=(
                "Only approved-channel messages and metadata are indexed in Qdrant. Chat memory "
                "keeps at most four completed turns per user and channel, expires after 30 minutes, "
                "and resets when the bot restarts. `/reset-chat` clears it early. Operational logs "
                "record request timing and token counts, never message content or API keys."
            ),
            inline=False,
        )

        embed.add_field(
            name="If retrieval is unavailable",
            value=(
                "A Qdrant or Gemini embedding outage only affects searchable class messages. "
                "Schedule, subject, and professor lookups continue using trusted local academic data."
            ),
            inline=False,
        )

        embed.set_footer(text="Bounded memory, controlled indexing, and read-only class tools")
        await interaction.response.send_message(embed=embed)

    async def explain_this(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """Right-click context menu app to explain a message or code snippet."""
        await interaction.response.defer(ephemeral=False)
        content = message.clean_content.strip()
        if not content:
            if message.attachments:
                content = f"[Attachment: {message.attachments[0].filename}]"
            elif message.embeds:
                content = f"[Embed: {message.embeds[0].title or message.embeds[0].description}]"
            else:
                await interaction.followup.send("That message doesn't contain readable text to explain.", ephemeral=True)
                return

        prompt = (
            f"Explain this Discord message/code from {message.author.display_name} simply and clearly:\n\n"
            f"{content}"
        )
        try:
            response = await self.bot.chat_orchestrator.chat(
                prompt,
                guild_id=interaction.guild.id if interaction.guild else 0,
                channel_id=interaction.channel.id if interaction.channel else 0,
                user_id=interaction.user.id,
                user_display_name=interaction.user.display_name,
                channel_name=getattr(interaction.channel, "name", "unknown"),
            )
            await interaction.followup.send(
                f"💡 **Explanation for {message.author.display_name}'s message:**\n{response.content}"
            )
        except Exception as e:
            logger.warning("[context_menu] Error running 'Explain This': %s", e)
            await interaction.followup.send("Couldn't generate an explanation for that message right now.", ephemeral=True)

    async def run_ocr(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """Right-click context menu app to extract text from an image attachment on demand."""
        await interaction.response.defer(ephemeral=True)
        image_attachments = [
            att for att in message.attachments
            if is_supported_image(att.filename, getattr(att, "content_type", None))
        ]
        if not image_attachments:
            await interaction.followup.send("No supported image attachments (.png, .jpg, .webp) found in that message.", ephemeral=True)
            return

        target_att = image_attachments[0]
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(target_att.url)
                resp.raise_for_status()
                image_bytes = resp.content

            ocr_service = OCRService()
            extracted_text = await ocr_service.extract_text(image_bytes)
            if not extracted_text:
                await interaction.followup.send(f"No readable text could be extracted from `{target_att.filename}`.", ephemeral=True)
                return

            await interaction.followup.send(
                f"📝 **Extracted Text from `{target_att.filename}`:**\n```{extracted_text}```",
                ephemeral=True,
            )
        except Exception as e:
            logger.warning("[context_menu] Error running 'Run OCR': %s", e)
            await interaction.followup.send("Failed to extract text from that image.", ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Handle errors that occur during execution of app commands in this cog."""
        logger.error(
            f"Error in command '{interaction.command.name}' invoked by {interaction.user}: {error}",
            exc_info=True,
        )
        # Inform user politely without exposing technical stack traces
        message = "Something went wrong while running this command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCog(bot))
