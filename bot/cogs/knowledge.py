import logging
import discord
from discord.ext import commands

from bot.services.embeddings import EmbeddingService, EmbeddingError
from bot.services.vector_store import VectorStore, VectorStoreError

logger = logging.getLogger(__name__)


def should_index_message(message: discord.Message, indexed_channel_ids: frozenset[int]) -> bool:
    """Determine whether a Discord message meets all Phase 2B knowledge ingestion rules.

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
    """Cog handling controlled background ingestion of eligible Discord text messages."""

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Background event listener for incoming Discord messages."""
        if not should_index_message(message, self.indexed_channel_ids):
            return

        content = message.content.strip()

        try:
            # 1. Generate vector embedding using Ollama embeddinggemma
            vector = await self.embedding_service.embed(content)

            # 2. Construct minimal metadata payload
            payload = {
                "message_id": str(message.id),
                "guild_id": str(message.guild.id),
                "channel_id": str(message.channel.id),
                "author_id": str(message.author.id),
                "content": content,
                "created_at": message.created_at.isoformat(),
            }

            # 3. Upsert point into Qdrant vector database
            await self.vector_store.upsert_message(
                message_id=message.id,
                vector=vector,
                payload=payload,
            )

            logger.info(
                f"Successfully indexed message (ID: {message.id}) "
                f"from Channel ID {message.channel.id} into Qdrant"
            )

        except (EmbeddingError, VectorStoreError) as e:
            # Background ingestion failures must log errors without interrupting bot operation or chat
            logger.error(
                f"Knowledge ingestion failed for message ID {message.id} "
                f"in channel ID {message.channel.id}: {e}"
            )
        except Exception as e:
            logger.exception(
                f"Unexpected failure during knowledge ingestion for message ID {message.id}: {e}"
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(KnowledgeCog(bot))
