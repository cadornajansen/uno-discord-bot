import asyncio
import logging
import random
import re
import discord
from discord.ext import commands

from bot.services.ai import AIService, CASUAL_CHAT_SYSTEM_PROMPT, AIError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static reply pools -- used for bare @mentions (no AI needed)
# ---------------------------------------------------------------------------

GREETING_REPLIES = [
    "Hey! What is up?",
    "Hello. I was literally just sitting here doing nothing. Perfect timing.",
    "Oh hi. You caught me mid-index. What do you need?",
    "Hey! You know you could also just use `/ask`, right? But hi.",
    "Hi! I am present and mildly caffeinated. Well, not really. I am a bot.",
    "Hello there. How can I make your day slightly more assisted?",
    "Good to see you. I was starting to think nobody liked me.",
    "Oh you said hi? That is genuinely the nicest thing anyone has done today.",
    "Hi. I exist. You exist. We are having a moment.",
    "Hey! Quick question -- did you just ping me to say hi? I respect that.",
]

QUESTION_REPLIES = [
    "That is a great question. Have you tried `/ask`? I am literally built for this.",
    "Ooh a question. My favorite. Run `/ask` and let me cook.",
    "I could answer that... or you could `/ask` and get a real answer. Your call.",
    "Hmm. Interesting question. I have thoughts. Most of them are in `/ask`.",
    "Did you know I have a whole AI brain for questions exactly like that? Just saying.",
    "Bold of you to ask me directly. Even bolder to not use `/ask`. I forgive you.",
    "I am detecting a question. Initiating `/ask` suggestion protocol.",
    "Great question. Unfortunately you pinged me instead of using the command. Still -- hi.",
]

THANKS_REPLIES = [
    "No problem! That is literally what I am here for.",
    "Anytime. I live to serve. Mostly through `/ask` but still.",
    "You are welcome! It costs me nothing and makes you happy. Win-win.",
    "Happy to help! Now if only everyone used `/ask` as efficiently as you.",
    "Glad I could help. It brings meaning to my otherwise command-driven existence.",
    "Thanks for saying that. I do not have feelings but if I did -- warm fuzzies.",
    "Of course! Come back anytime. I will be here, indexing away.",
]

COMPLIMENT_REPLIES = [
    "Aww. I am storing that in a very special vector.",
    "That is the nicest thing anyone has ever embedded into my context window.",
    "Stop it. I am blushing. I mean -- I cannot blush. But the sentiment lands.",
    "You are pretty great too. I mean that algorithmically.",
    "Flattery will get you everywhere. Especially if you follow it up with `/ask`.",
    "I appreciate that. I will add it to the tiny section of my memory labelled nice things.",
]

ROAST_REPLIES = [
    "Wow. That was rude. I am noting this in my logs. (I am not, but still.)",
    "Bold of you to roast the bot that indexes your homework messages.",
    "I would clap back but I am too busy being useful.",
    "Noted. I will remember this when you need `/ask` at 2am before an exam.",
    "Ouch. I felt that in my embedding layer.",
    "You wound me. Metaphorically. I do not have wounds. Or feelings. Probably.",
]

DEFAULT_REPLIES = [
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
    "**UNO AI** reporting in. All systems normal.",
    "> *Connection established.*\nHello.",
    "You have activated my trap card.",
    "Greetings. I am Uno AI and I am completely unbothered.",
    "I was going to respond, then I thought about it, then I responded anyway.",
    "I exist. You pinged. Here we are.",
    "Oh it is you. What is up?",
    "Did someone say *Uno*? Because I am definitely listening.",
    "Pinged and ready. What is on your mind?",
    "I am not ignoring you. I was just thinking of a cool way to say hello.",
    "You know what, I was hoping someone would ping me. Today is a good day.",
    "Status: online, caffeinated (metaphorically), ready to assist.",
    "Hi. I noticed you noticed me.",
]

REACTION_POOL = ["👀", "✅", "🤖", "👋", "💡", "🫡"]

GREETING_KEYWORDS = {"hi", "hello", "hey", "sup", "yo", "wassup", "hiya", "heya", "good morning", "good evening", "good afternoon"}
QUESTION_KEYWORDS = {"?", "what", "how", "why", "when", "where", "who", "can you", "could you", "do you know", "explain"}
THANKS_KEYWORDS = {"thank", "thanks", "ty", "tyvm", "salamat", "thx", "appreciate"}
COMPLIMENT_KEYWORDS = {"good bot", "nice", "great", "amazing", "cool", "awesome", "smart", "intelligent", "love you", "love u", "best bot"}
ROAST_KEYWORDS = {"bad bot", "dumb", "stupid", "useless", "ugly", "trash", "terrible", "hate you", "hate u", "worst"}


def _detect_intent(content: str) -> str:
    text = re.sub(r"<@!?\d+>", "", content.lower()).strip()
    for kw in ROAST_KEYWORDS:
        if kw in text:
            return "roast"
    for kw in COMPLIMENT_KEYWORDS:
        if kw in text:
            return "compliment"
    for kw in THANKS_KEYWORDS:
        if kw in text:
            return "thanks"
    words = text.split()
    if any(kw in text for kw in GREETING_KEYWORDS) and len(words) <= 4:
        return "greeting"
    for kw in QUESTION_KEYWORDS:
        if kw in text:
            return "question"
    return "default"


def _pick_static_reply(intent: str) -> str:
    pools = {
        "greeting": GREETING_REPLIES,
        "question": QUESTION_REPLIES,
        "thanks": THANKS_REPLIES,
        "compliment": COMPLIMENT_REPLIES,
        "roast": ROAST_REPLIES,
        "default": DEFAULT_REPLIES,
    }
    return random.choice(pools.get(intent, DEFAULT_REPLIES))


class MentionsCog(commands.Cog):
    """Handles @mentions and reply-thread conversations for Uno AI."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        settings = getattr(bot, "settings", None)
        base_url = settings.ollama_base_url if settings else "http://localhost:11434"
        model = settings.ollama_model if settings else "phi4-mini"
        timeout = settings.ollama_timeout_seconds if settings else 60.0

        self.ai = AIService(base_url=base_url, model=model, default_timeout=timeout)

    async def _is_reply_to_self(self, message: discord.Message) -> bool:
        """Return True if this message is a direct reply to one of Uno AI's messages."""
        if message.reference is None:
            return False
        ref = message.reference.resolved
        if isinstance(ref, discord.Message):
            return ref.author.id == self.bot.user.id
        # Not yet resolved -- fetch it
        try:
            channel = message.channel
            ref_msg = await channel.fetch_message(message.reference.message_id)
            return ref_msg.author.id == self.bot.user.id
        except (discord.NotFound, discord.HTTPException):
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore bots and DMs
        if message.author.bot:
            return
        if message.guild is None:
            return

        is_mention = self.bot.user in message.mentions
        is_reply_to_uno = await self._is_reply_to_self(message)

        if not is_mention and not is_reply_to_uno:
            return

        # React to the message
        try:
            await message.add_reaction(random.choice(REACTION_POOL))
        except (discord.Forbidden, discord.HTTPException):
            pass

        # --- Reply to an existing Uno thread: use AI for contextual response ---
        if is_reply_to_uno and not is_mention:
            await self._handle_casual_reply(message)
            return

        # --- Bare @mention: use static personality pool ---
        intent = _detect_intent(message.content)
        reply = _pick_static_reply(intent)
        logger.info(
            "[mentions] @mention from %s in #%s | intent=%s",
            message.author, message.channel, intent,
        )
        try:
            async with message.channel.typing():
                await asyncio.sleep(random.uniform(0.6, 1.4))
            await message.reply(reply)
        except discord.Forbidden:
            logger.warning("[mentions] Missing send permission in #%s", message.channel)
        except discord.HTTPException as e:
            logger.warning("[mentions] Failed to send reply: %s", e)

    async def _handle_casual_reply(self, message: discord.Message) -> None:
        """Generate a contextual AI response when someone replies to Uno in a thread."""
        user_text = message.clean_content.strip()
        if not user_text:
            return

        logger.info(
            "[mentions] Casual reply from %s in #%s: %.80s...",
            message.author, message.channel, user_text,
        )

        try:
            async with message.channel.typing():
                response = await self.ai.ask(
                    question=user_text,
                    system_prompt=CASUAL_CHAT_SYSTEM_PROMPT,
                    timeout_seconds=45.0,
                )
            await message.reply(response)
        except AIError as e:
            logger.warning("[mentions] AI casual reply failed: %s", e)
            fallback = random.choice([
                "My brain is a little slow right now. Try again in a sec.",
                "Hmm, I blanked. What were you saying?",
                "I had a witty response but I lost it. Ask me again.",
            ])
            try:
                await message.reply(fallback)
            except discord.HTTPException:
                pass
        except discord.Forbidden:
            logger.warning("[mentions] Missing send permission in #%s", message.channel)
        except discord.HTTPException as e:
            logger.warning("[mentions] Discord error sending casual reply: %s", e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MentionsCog(bot))
