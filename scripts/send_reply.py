"""
scripts/send_reply.py

One-shot script: fetches a Discord message by ID and replies to it.
Loads DISCORD_TOKEN from .env (same as the main bot).

Usage:
    python scripts/send_reply.py
"""

import asyncio
import os
import sys

import discord
from dotenv import load_dotenv

load_dotenv()

TARGET_MESSAGE_ID = 1536171055864094755

REPLY_CONTENT = (
    "## ?? Hey there!\n\n"
    "> *Uno AI is online and paying attention.*\n\n"
    "Just dropping by to say — this message has been **officially acknowledged** "
    "by the bot. ???\n\n"
    "If you were expecting something specific, ask away with `/ask`.\n"
    "If not — carry on, nothing to see here. ??"
)


class ReplyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._done = False

    async def on_ready(self):
        if self._done:
            return
        self._done = True

        print(f"[reply_bot] Logged in as {self.user} (ID: {self.user.id})")

        message = None

        # Search all guilds then text channels for the target message
        for guild in self.guilds:
            if message:
                break
            for channel in guild.text_channels:
                try:
                    message = await channel.fetch_message(TARGET_MESSAGE_ID)
                    print(
                        f"[reply_bot] Found message {TARGET_MESSAGE_ID} "
                        f"in #{channel.name} ({guild.name})"
                    )
                    break
                except discord.NotFound:
                    continue
                except discord.Forbidden:
                    continue
                except discord.HTTPException:
                    continue

        if message is None:
            print(
                f"[reply_bot] ERROR: Could not find message ID {TARGET_MESSAGE_ID} "
                "in any accessible channel.",
                file=sys.stderr,
            )
            await self.close()
            return

        try:
            await message.reply(REPLY_CONTENT)
            print(f"[reply_bot] Reply sent to message {TARGET_MESSAGE_ID}")
        except discord.Forbidden:
            print(
                "[reply_bot] ERROR: Missing permission to send messages in that channel.",
                file=sys.stderr,
            )
        except discord.HTTPException as e:
            print(f"[reply_bot] ERROR: Failed to send reply: {e}", file=sys.stderr)
        finally:
            await self.close()


async def main():
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        print("ERROR: DISCORD_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)

    client = ReplyClient()
    try:
        await client.start(token)
    except discord.LoginFailure:
        print("ERROR: Invalid DISCORD_TOKEN.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
