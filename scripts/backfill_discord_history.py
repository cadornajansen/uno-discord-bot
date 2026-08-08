"""Developer CLI script to backfill historical Discord messages into Qdrant vector database.

Usage:
    python scripts/backfill_discord_history.py [--channel-id <ID>] [--limit <N>]

Examples:
    python scripts/backfill_discord_history.py
    python scripts/backfill_discord_history.py --channel-id 123456789012345678 --limit 200
"""

import argparse
import asyncio
import logging
import sys
import discord
from discord.ext import commands

from config.settings import load_settings, ConfigError
from bot.cogs.knowledge import should_index_message
from bot.services.embeddings import EmbeddingService, EmbeddingError
from bot.services.vector_store import VectorStore, VectorStoreError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backfill")


async def run_backfill(channel_id_filter: int | None, limit: int | None) -> int:
    """Execute historical message backfill for allowlisted Discord channels.

    Args:
        channel_id_filter: Optional specific channel ID to backfill.
        limit: Optional maximum number of messages to fetch per channel.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    try:
        settings = load_settings()
    except ConfigError as e:
        logger.error(f"Configuration Error: {e}")
        return 1

    allowlist = settings.indexed_channel_ids
    if not allowlist:
        logger.error("No channel IDs configured in INDEXED_CHANNEL_IDS. Backfill aborted.")
        return 1

    # Validate specified channel ID against allowlist
    if channel_id_filter is not None:
        if channel_id_filter not in allowlist:
            logger.error(
                f"Channel ID {channel_id_filter} is not in INDEXED_CHANNEL_IDS allowlist: {set(allowlist)}"
            )
            return 1
        target_channel_ids = [channel_id_filter]
    else:
        target_channel_ids = list(allowlist)

    embedding_service = EmbeddingService(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
    )
    vector_store = VectorStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
    )

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    bot.settings = settings

    from bot.cogs.knowledge import KnowledgeCog

    cog = KnowledgeCog(bot)

    @bot.event
    async def on_ready():
        logger.info(f"Backfill client logged in as {bot.user} (ID: {bot.user.id})")
        logger.info(f"Targeting {len(target_channel_ids)} allowlisted channel(s)")

        total_indexed = 0
        total_skipped = 0
        total_failed = 0

        for ch_id in target_channel_ids:
            try:
                channel = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
            except Exception as e:
                logger.error(f"Failed to fetch channel ID {ch_id}: {e}")
                continue

            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                logger.warning(f"Channel ID {ch_id} is not a text channel or thread. Skipping.")
                continue

            logger.info(f"Starting history scan for #{channel.name} (ID: {ch_id}), limit={limit}...")

            ch_indexed = 0
            ch_skipped = 0
            ch_failed = 0

            try:
                async for message in channel.history(limit=limit, oldest_first=True):
                    if not should_index_message(
                        message,
                        indexed_channel_ids=settings.indexed_channel_ids,
                        ocr_channel_ids=settings.ocr_channel_ids,
                        ocr_max_image_mb=settings.ocr_max_image_mb,
                    ):
                        ch_skipped += 1
                        continue

                    success = await cog.index_message(message)
                    if success:
                        ch_indexed += 1
                    else:
                        ch_failed += 1

            except Exception as hist_err:
                logger.error(f"Error reading history for channel ID {ch_id}: {hist_err}")

            logger.info(
                f"Completed #{channel.name}: {ch_indexed} indexed, {ch_skipped} skipped, {ch_failed} failed"
            )
            total_indexed += ch_indexed
            total_skipped += ch_skipped
            total_failed += ch_failed

        logger.info(
            f"Historical backfill complete! Total indexed: {total_indexed}, "
            f"skipped: {total_skipped}, failed: {total_failed}"
        )

        await cog.vector_store.close()
        await bot.close()

    try:
        await bot.start(settings.discord_token)
        return 0
    except Exception as e:
        logger.error(f"Backfill execution failed: {e}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historical Discord messages into Qdrant vector database."
    )
    parser.add_argument(
        "--channel-id",
        type=int,
        default=None,
        help="Optional specific allowlisted channel ID to backfill.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of messages to fetch per channel.",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(run_backfill(channel_id_filter=args.channel_id, limit=args.limit))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
