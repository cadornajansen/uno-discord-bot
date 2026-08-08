import logging
import discord
from discord.ext import commands

from bot.services.embeddings import EmbeddingService, EmbeddingError
from bot.services.vector_store import VectorStore, VectorStoreError

logger = logging.getLogger(__name__)


def should_index_message(message: discord.Message, indexed_channel_ids: frozenset[int]) -> bool:
    """Determine whether a Discord message meets all knowledge ingestion rules.

    Args:
        message: The Discord message object to evaluate.
        indexed_channel_ids: Frozenset of explicitly allowlisted channel IDs.

    Returns:
        True if the message is eligible for ingestion; False otherwise.
    """
    # Rule 1: Must be inside a guild (ignore DMs)
    if message.guild is None:
        return False

    # Rule 2: Channel ID must be explicitly allowlisted in configuration
    if message.channel.id not in indexed_channel_ids:
        return False

    # Rule 3: Author must not be a bot
    if message.author.bot:
        return False

    # Rule 4: Message must not originate from a webhook
    if getattr(message, "webhook_id", None) is not None:
        return False

    # Rule 5: Message must contain non-empty text content
    if not message.content or not message.content.strip():
        return False

    return True


class KnowledgeCog(commands.Cog):
    """Cog handling controlled background ingestion & synchronization of Discord messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        settings = getattr(bot, "settings", None)

        base_url = settings.ollama_base_url if settings else "http://localhost:11434"
        embed_model = settings.ollama_embedding_model if settings else "embeddinggemma"
        qdrant_url = settings.qdrant_url if settings else "http://localhost:6333"
        qdrant_coll = settings.qdrant_collection if settings else "discord_messages"

        self.indexed_channel_ids: frozenset[int] = (
            settings.indexed_channel_ids if settings else frozenset()
        )

        self.embedding_service = EmbeddingService(base_url=base_url, model=embed_model)
        self.vector_store = VectorStore(url=qdrant_url, collection_name=qdrant_coll)

    async def index_message(self, message: discord.Message) -> bool:
        """Reusable method to validate, embed, and upsert a Discord message into Qdrant.

        Args:
            message: Discord message to process.

        Returns:
            True if indexing succeeded; False if skipped or failed.
        """
        if not should_index_message(message, self.indexed_channel_ids):
            return False

        content = message.content.strip()

        try:
            # 1. Generate dense vector embedding
            vector = await self.embedding_service.embed(content)

            # 2. Build metadata payload
            payload = {
                "message_id": str(message.id),
                "guild_id": str(message.guild.id),
                "channel_id": str(message.channel.id),
                "author_id": str(message.author.id),
                "content": content,
                "created_at": message.created_at.isoformat(),
            }

            # 3. Upsert into Qdrant using Discord message ID as canonical Point ID
            await self.vector_store.upsert_message(
                message_id=message.id,
                vector=vector,
                payload=payload,
            )

            logger.info(
                f"Indexed message ID {message.id} (Channel ID: {message.channel.id}) into Qdrant"
            )
            return True

        except (EmbeddingError, VectorStoreError) as e:
            logger.error(
                f"Knowledge indexing failed for message ID {message.id} "
                f"in channel ID {message.channel.id}: {e}"
            )
            return False
        except Exception as e:
            logger.exception(
                f"Unexpected failure during knowledge indexing for message ID {message.id}: {e}"
            )
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listener for new Discord text messages."""
        await self.index_message(message)

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        """Listener for edited Discord text messages."""
        # Skip if message text content did not change
        if before.content == after.content:
            return

        # If edited message is still eligible, re-embed and update Qdrant point
        if should_index_message(after, self.indexed_channel_ids):
            logger.info(f"Processing edited message ID {after.id}")
            await self.index_message(after)
        else:
            # If message became ineligible after editing (e.g. edited to empty text),
            # delete existing point if original message was in an allowlisted channel & guild
            if (
                before.guild is not None
                and before.channel.id in self.indexed_channel_ids
            ):
                logger.info(
                    f"Edited message ID {after.id} became ineligible. Removing from Qdrant."
                )
                try:
                    await self.vector_store.delete_message(after.id)
                except VectorStoreError as e:
                    logger.error(
                        f"Failed to delete point for ineligible edited message ID {after.id}: {e}"
                    )

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self,
        payload: discord.RawMessageDeleteEvent,
    ) -> None:
        """Raw listener for deleted Discord messages (handles both cached and uncached messages)."""
        # Delete only if deletion occurred inside a guild and allowlisted channel
        if (
            payload.guild_id is not None
            and payload.channel_id in self.indexed_channel_ids
        ):
            logger.info(
                f"Processing message deletion for message ID {payload.message_id} "
                f"in channel ID {payload.channel_id}"
            )
            try:
                await self.vector_store.delete_message(payload.message_id)
            except VectorStoreError as e:
                logger.error(
                    f"Failed to delete point for message ID {payload.message_id} from Qdrant: {e}"
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(KnowledgeCog(bot))
