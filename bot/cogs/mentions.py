import asyncio
import logging
import random
import re
from typing import Literal
import discord
from discord.ext import commands

from bot.services.ai import AIError
from bot.utils.formatting import build_assignment_embeds

logger = logging.getLogger(__name__)

CONVERSATION_SYSTEM_PROMPT = (
    "You are Uno AI, an assistant for a Computer Science college block section.\n\n"
    "Tone & Persona:\n"
    "- Nonchalant, calm, direct, and unbothered.\n"
    "- Rarely humorously: subtle dry humor only when natural. Do not force jokes or fake enthusiasm.\n"
    "- Super rare use of emojis: almost never use emojis.\n\n"
    "Instructions:\n"
    "- Respond primarily to the current user message.\n"
    "- The replied-to message is immediate conversational context, not a new question to answer again.\n"
    "- If the user gives style or behavior feedback, acknowledge it briefly and apply it immediately.\n"
    "- Use nearby conversation or retrieved class knowledge only when it directly helps the current message.\n"
    "- If the user asks to confirm if data/notes are correct, check the context and confirm or clarify matter-of-factly.\n"
    "- Keep answers to 1-3 short sentences unless the user explicitly requests detail.\n"
    "- Never dump, summarize, or mention irrelevant context.\n"
    "- Do not mention system prompts, vector scores, or technical instructions."
)

ContextMode = Literal["direct", "nearby", "rag"]

CLASS_CONTEXT_TERMS = (
    "announcement",
    "assignment",
    "class",
    "deadline",
    "document",
    "due",
    "exam",
    "homework",
    "instructor",
    "lesson",
    "notes",
    "professor",
    "project",
    "quiz",
    "schedule",
    "subject",
    "teacher",
)

REFERENTIAL_FOLLOWUP_TERMS = (
    "are you sure",
    "can you explain",
    "explain that",
    "how so",
    "is that correct",
    "is that right",
    "what about that",
    "what did you mean",
    "what do you mean",
    "why is that",
)


def style_feedback_acknowledgement(text: str) -> str | None:
    """Return an immediate acknowledgement for common response-style requests."""
    normalized = " ".join(text.casefold().split())
    if "nonchalant" in normalized or "more chill" in normalized:
        return "Got it. Keeping it chill."
    if "shorter" in normalized or "more concise" in normalized:
        return "Got it. I'll keep replies shorter."
    if "less emoji" in normalized or "fewer emoji" in normalized or "no emoji" in normalized:
        return "Got it. Fewer emojis."
    if "more formal" in normalized:
        return "Understood. I'll keep it more formal."
    if "more casual" in normalized:
        return "Got it. I'll keep it casual."
    return None


def choose_context_mode(text: str) -> ContextMode:
    """Choose the smallest amount of context that can answer a conversational reply."""
    normalized = " ".join(text.casefold().split())
    if any(term in normalized for term in CLASS_CONTEXT_TERMS):
        return "rag"
    if any(term in normalized for term in REFERENTIAL_FOLLOWUP_TERMS):
        return "nearby"
    return "direct"

BARE_MENTION_REPLIES = [
    "Yeah? What do you need?",
    "Present.",
    "I'm here. What's up?",
    "Signal received. What's the query?",
    "I heard my name.",
    "At your service.",
    "You pinged?",
    "Standing by.",
    "Uno AI here. What do you need?",
    "Listening.",
]

class MentionsCog(commands.Cog):
    """Handles mentions and replies using only the context each message needs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_orchestrator = bot.chat_orchestrator

    async def _get_referenced_message(self, message: discord.Message) -> discord.Message | None:
        """Fetch and return the referenced message if this is a reply."""
        if message.reference is None:
            return None

        ref = message.reference.resolved
        if isinstance(ref, discord.Message):
            return ref

        if message.reference.message_id:
            try:
                return await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return None

    async def _fetch_recent_channel_history(
        self,
        message: discord.Message,
        *,
        limit: int = 3,
        before: discord.Message | None = None,
    ) -> str:
        """Fetch a small conversation window before the chosen anchor message."""
        history_msgs = []
        try:
            async for msg in message.channel.history(limit=limit, before=before or message):
                content = msg.clean_content.strip()
                if content:
                    history_msgs.append(f"[{msg.author.display_name}]: {content}")
            history_msgs.reverse()  # Oldest first
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("[mentions] Could not fetch channel history: %s", e)

        return "\n".join(history_msgs)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore bots and DMs
        if message.author.bot:
            return
        if message.guild is None:
            return

        is_mention = self.bot.user in message.mentions
        ref_msg = await self._get_referenced_message(message)
        is_reply_to_uno = ref_msg is not None and ref_msg.author.id == self.bot.user.id

        # Trigger if mentioned OR if replying to one of Uno AI's messages
        if not is_mention and not is_reply_to_uno:
            return

        # Clean the user text (strip the bot mention string like @Uno AI)
        clean_text = message.clean_content
        if self.bot.user:
            clean_text = re.sub(r"@?" + re.escape(self.bot.user.name), "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"<@!?\d+>", "", clean_text).strip()

        # Text mentions and replies use adaptive context based on the current message.
        if clean_text or ref_msg is not None:
            await self._respond_with_adaptive_context(message, clean_text, ref_msg)
        else:
            # Bare ping with zero text -> send quick static reply
            reply = random.choice(BARE_MENTION_REPLIES)
            try:
                async with message.channel.typing():
                    await asyncio.sleep(0.5)
                await message.reply(reply)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning("[mentions] Failed to send bare mention reply: %s", e)

    async def _respond_with_adaptive_context(
        self,
        message: discord.Message,
        clean_text: str,
        ref_msg: discord.Message | None,
    ) -> None:
        """Generate a reply through the shared per-user chat workflow."""
        style_acknowledgement = style_feedback_acknowledgement(clean_text)
        if style_acknowledgement:
            try:
                await message.reply(style_acknowledgement)
            except (discord.Forbidden, discord.HTTPException) as error:
                logger.warning(
                    "[mentions] Discord error acknowledging style feedback: %s",
                    error,
                )
            return

        context_mode = choose_context_mode(clean_text)
        channel_history_text = ""
        if context_mode == "nearby":
            channel_history_text = await self._fetch_recent_channel_history(
                message,
                limit=3,
                before=ref_msg,
            )
        user_input_text = clean_text or "(Replied without text)"

        logger.info(
            "[mentions] Adaptive reply for %s in #%s "
            "(mode=%s, nearby_history_len=%d)",
            message.author,
            message.channel,
            context_mode,
            len(channel_history_text.splitlines()),
        )

        try:
            async with message.channel.typing():
                response = await self.chat_orchestrator.chat(
                    user_input_text,
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    user_display_name=message.author.display_name,
                    channel_name=getattr(message.channel, "name", "unknown"),
                    reply_context=(
                        ref_msg.clean_content.strip()
                        if ref_msg and ref_msg.clean_content
                        else None
                    ),
                    nearby_context=channel_history_text or None,
                )
            embeds = build_assignment_embeds(
                response.assignment_items,
                response.current_datetime,
            )
            if embeds:
                await message.reply(embed=embeds[0])
                for embed in embeds[1:]:
                    await message.channel.send(embed=embed)
            else:
                await message.reply(response.content)
        except AIError as e:
            logger.warning("[mentions] AI conversational reply error: %s", e)
            fallback = random.choice([
                "My AI connection hit an error processing that. Try asking again.",
                "Hmm, I had trouble reading the channel context. Mind trying again?",
            ])
            try:
                await message.reply(fallback)
            except discord.HTTPException:
                pass
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("[mentions] Discord error sending AI reply: %s", e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MentionsCog(bot))
