import asyncio
import logging
import random
import re
import discord
from discord.ext import commands

from bot.services.ai import AIService, CASUAL_CHAT_SYSTEM_PROMPT, AIError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback / Bare mention static replies
# ---------------------------------------------------------------------------

BARE_MENTION_REPLIES = [
    "Present. What do you need?",
    "You called? I was just indexing your messages. No big deal.",
    "Ah yes, summoned once again. What wisdom do you seek?",
    "I heard my name. Bots always hear their name.",
    "Signal received. Standing by.",
    "At your service -- unless you pinged me by accident. It happens.",
    "I see you. I see everything. (Just kidding, I only see this channel.)",
    "One ping. One response. That is how this works.",
    "You have my attention. Use it wisely.",
    "The bot awakens. Speak your request.",
    "UNO AI reporting in. All systems normal.",
    "Greetings. I am Uno AI and I am completely unbothered.",
    "I exist. You pinged. Here we are.",
    "Did someone say Uno? Because I am definitely listening.",
    "Pinged and ready. What is on your mind?",
]

REACTION_POOL = ["👀", "✅", "🤖", "👋", "💡", "🫡"]


class MentionsCog(commands.Cog):
    """Handles @mentions and reply-thread conversations for Uno AI using local AI."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        settings = getattr(bot, "settings", None)
        base_url = settings.ollama_base_url if settings else "http://localhost:11434"
        model = settings.ollama_model if settings else "phi4-mini"
        timeout = settings.ollama_timeout_seconds if settings else 180.0

        self.ai = AIService(base_url=base_url, model=model, default_timeout=timeout)

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

        # Add a friendly reaction
        try:
            await message.add_reaction(random.choice(REACTION_POOL))
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Clean the user text (strip the bot mention string like @Uno AI)
        clean_text = message.clean_content
        if self.bot.user:
            clean_text = re.sub(r"@?" + re.escape(self.bot.user.name), "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"<@!?\d+>", "", clean_text).strip()

        # If user provided text OR is replying to a message -> USE LOCAL AI CONTEXTUALLY
        if clean_text or ref_msg is not None:
            await self._respond_with_ai(message, clean_text, ref_msg)
        else:
            # Bare ping with zero text -> send quick static reply
            reply = random.choice(BARE_MENTION_REPLIES)
            try:
                async with message.channel.typing():
                    await asyncio.sleep(0.5)
                await message.reply(reply)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning("[mentions] Failed to send bare mention reply: %s", e)

    async def _respond_with_ai(
        self,
        message: discord.Message,
        clean_text: str,
        ref_msg: discord.Message | None,
    ) -> None:
        """Use local AI to generate a contextual response to user message or thread reply."""
        ref_content = ref_msg.clean_content.strip() if ref_msg and ref_msg.clean_content else ""

        # Construct prompt with prior message context if replying to a thread
        if ref_content:
            author_name = ref_msg.author.display_name
            prompt = (
                f"Prior message from {author_name}:\n\"{ref_content}\"\n\n"
                f"User reply from {message.author.display_name}:\n\"{clean_text or '(Replied without text)'}\""
            )
        else:
            prompt = clean_text

        logger.info(
            "[mentions] AI conversational reply for %s in #%s: %.80s",
            message.author, message.channel, prompt.replace('\n', ' '),
        )

        try:
            async with message.channel.typing():
                response = await self.ai.ask(
                    question=prompt,
                    system_prompt=CASUAL_CHAT_SYSTEM_PROMPT,
                )
            await message.reply(response)
        except AIError as e:
            logger.warning("[mentions] AI casual chat error: %s", e)
            fallback = random.choice([
                "My local AI brain had a quick hiccup. Try asking again!",
                "Hmm, I got confused for a second. Mind repeating that?",
                "Ollama timed out on my end. Give me another try in a moment.",
            ])
            try:
                await message.reply(fallback)
            except discord.HTTPException:
                pass
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("[mentions] Discord error sending AI reply: %s", e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MentionsCog(bot))
