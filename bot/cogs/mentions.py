import logging
import random
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

# Rotation pool of cool replies when Uno AI is mentioned.
# Plain text + Discord markdown only -- no emojis to avoid Windows encoding issues.
MENTION_REPLIES = [
    "**Present.** What do you need?",
    "You called? I was just indexing your messages. No big deal.",
    "Ah yes, summoned once again. What wisdom do you seek?",
    "I heard my name. The bots always hear their name.",
    "**[UNO AI online]** How can I help?",
    "I exist. You pinged. Here we are.",
    "You rang? Try `/ask` if you have an actual question.",
    "Did someone say *Uno*? Because I am definitely listening.",
    "Signal received. Standing by.",
    "At your service -- unless you just pinged me by accident. It happens.",
    "I was going to respond, then I thought about it, then I responded anyway.",
    "Greetings. You have activated my trap card.",
    "> *Connection established.*\nHello.",
    "One ping. One response. That is how this works.",
    "You have my attention. Use it wisely.",
    "I see you. I see everything. (Just kidding, I only see this channel.)",
    "**UNO AI** reporting in. All systems normal.",
    "Oh, it is you. What is up?",
    "Pinged and ready. What is on your mind?",
    "The bot awakens. Speak your request.",
]


class MentionsCog(commands.Cog):
    """Cog that listens for @mentions of the bot and replies with a random cool response."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore messages from bots (including itself)
        if message.author.bot:
            return

        # Ignore DMs
        if message.guild is None:
            return

        # Only respond when the bot is mentioned
        if self.bot.user not in message.mentions:
            return

        reply = random.choice(MENTION_REPLIES)
        logger.info(
            f"[mentions] Responding to mention by {message.author} "
            f"in #{message.channel} ({message.guild})"
        )

        try:
            await message.reply(reply)
        except discord.Forbidden:
            logger.warning(
                f"[mentions] Missing send permission in #{message.channel}"
            )
        except discord.HTTPException as e:
            logger.warning(f"[mentions] Failed to send mention reply: {e}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MentionsCog(bot))
