import logging
import discord
from discord.ext import commands
import httpx

from bot.services.embeddings import EmbeddingService, EmbeddingError
from bot.services.vector_store import VectorStore, VectorStoreError
from bot.services.ocr import OCRService, is_supported_image

logger = logging.getLogger(__name__)


def should_index_message(
    message: discord.Message,
    indexed_channel_ids: frozenset[int],
    ocr_channel_ids: frozenset[int] = frozenset(),
    ocr_max_image_mb: int = 8,
) -> bool:
    """Determine whether a Discord message meets all knowledge ingestion rules.

    Args:
        message: The Discord message object to evaluate.
        indexed_channel_ids: Frozenset of explicitly allowlisted channel IDs.
        ocr_channel_ids: Frozenset of channel IDs approved for image OCR.
        ocr_max_image_mb: Maximum size limit for image OCR processing in MB.

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

    # Rule 5: Message must not be an interaction or slash-command invocation
    if getattr(message, "interaction_metadata", None) is not None:
        return False

    # Rule 6: Evaluating message text content & attachments
    has_text = bool(message.content and message.content.strip())

    is_ocr_channel = message.channel.id in ocr_channel_ids
    has_supported_ocr_attachment = False

    if is_ocr_channel and getattr(message, "attachments", None):
        try:
            max_bytes = int(ocr_max_image_mb) * 1024 * 1024
        except (TypeError, ValueError):
            max_bytes = 8 * 1024 * 1024

        for att in message.attachments:
            if is_supported_image(att.filename, getattr(att, "content_type", None)):
                att_size = getattr(att, "size", 0)
                if isinstance(att_size, (int, float)) and att_size <= max_bytes:
                    has_supported_ocr_attachment = True
                    break

    # Eligible if message has text OR has supported OCR image attachment in an OCR channel
    if not has_text and not has_supported_ocr_attachment:
        return False

    return True


class KnowledgeCog(commands.Cog):
    """Cog handling controlled background ingestion & synchronization of Discord messages and image OCR."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        settings = getattr(bot, "settings", None)

        base_url = (
            settings.ollama_base_url
            if settings and isinstance(getattr(settings, "ollama_base_url", None), str)
            else "http://localhost:11434"
        )
        embed_model = (
            settings.ollama_embedding_model
            if settings and isinstance(getattr(settings, "ollama_embedding_model", None), str)
            else "embeddinggemma"
        )
        qdrant_url = (
            settings.qdrant_url
            if settings and isinstance(getattr(settings, "qdrant_url", None), str)
            else "http://localhost:6333"
        )
        qdrant_coll = (
            settings.qdrant_collection
            if settings and isinstance(getattr(settings, "qdrant_collection", None), str)
            else "discord_messages"
        )

        self.indexed_channel_ids: frozenset[int] = (
            settings.indexed_channel_ids
            if settings and isinstance(getattr(settings, "indexed_channel_ids", None), (frozenset, set))
            else frozenset()
        )
        self.ocr_channel_ids: frozenset[int] = (
            settings.ocr_channel_ids
            if settings and isinstance(getattr(settings, "ocr_channel_ids", None), (frozenset, set))
            else frozenset()
        )

        self.ocr_max_image_mb: int = 8
        if settings and isinstance(getattr(settings, "ocr_max_image_mb", None), int):
            self.ocr_max_image_mb = settings.ocr_max_image_mb

        self.ocr_min_text_chars: int = 10
        if settings and isinstance(getattr(settings, "ocr_min_text_chars", None), int):
            self.ocr_min_text_chars = settings.ocr_min_text_chars

        self.ocr_max_images_per_message: int = 3
        if settings and isinstance(getattr(settings, "ocr_max_images_per_message", None), int):
            self.ocr_max_images_per_message = settings.ocr_max_images_per_message

        self.embedding_service = EmbeddingService(base_url=base_url, model=embed_model)
        self.vector_store = VectorStore(url=qdrant_url, collection_name=qdrant_coll)
        self.ocr_service = OCRService(min_text_chars=self.ocr_min_text_chars)

    async def index_message(self, message: discord.Message) -> bool:
        """Reusable method to validate, OCR, embed, and upsert a Discord message into Qdrant.

        Args:
            message: Discord message to process.

        Returns:
            True if indexing succeeded; False if skipped or failed.
        """
        if not should_index_message(
            message,
            indexed_channel_ids=self.indexed_channel_ids,
            ocr_channel_ids=self.ocr_channel_ids,
            ocr_max_image_mb=self.ocr_max_image_mb,
        ):
            return False

        try:
            normal_text = message.content.strip() if message.content else ""
            ocr_texts: list[str] = []
            ocr_filenames: list[str] = []

            # 1. OCR processing if channel is OCR-enabled
            if message.channel.id in self.ocr_channel_ids and getattr(message, "attachments", None):
                max_bytes = self.ocr_max_image_mb * 1024 * 1024
                img_count = 0

                for att in message.attachments:
                    if img_count >= self.ocr_max_images_per_message:
                        break

                    if not is_supported_image(att.filename, getattr(att, "content_type", None)):
                        logger.debug(f"Skipping OCR: unsupported image type '{att.filename}'")
                        continue

                    if getattr(att, "size", 0) > max_bytes:
                        logger.info(
                            f"Skipping OCR attachment {att.filename}: exceeds {self.ocr_max_image_mb} MB limit"
                        )
                        continue

                    try:
                        # Download image bytes
                        if hasattr(att, "read") and callable(att.read):
                            img_bytes = await att.read()
                        elif hasattr(att, "url") and att.url:
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                resp = await client.get(att.url)
                                resp.raise_for_status()
                                img_bytes = resp.content
                        else:
                            continue

                        extracted = await self.ocr_service.extract_text(img_bytes)
                        if extracted:
                            logger.info(f"OCR extracted {len(extracted)} chars from {att.filename}")
                            ocr_texts.append(extracted)
                            ocr_filenames.append(att.filename)
                            img_count += 1
                        else:
                            logger.debug(f"Skipping OCR: text too short in {att.filename}")
                    except Exception as ocr_err:
                        logger.warning(f"OCR failed for attachment {att.filename}: {ocr_err}")

            # 2. Combine normal text and OCR extracted text
            ocr_combined = "\n\n".join(ocr_texts).strip()

            if normal_text and ocr_combined:
                combined_content = f"Discord message:\n{normal_text}\n\nImage text:\n{ocr_combined}"
                source_type = "text_and_image_ocr"
            elif ocr_combined:
                combined_content = f"Image text:\n{ocr_combined}"
                source_type = "image_ocr"
            elif normal_text:
                combined_content = normal_text
                source_type = "text"
            else:
                # No usable text or OCR content
                return False

            # 3. Generate dense vector embedding
            vector = await self.embedding_service.embed(combined_content)

            # 4. Build metadata payload
            payload = {
                "message_id": str(message.id),
                "guild_id": str(message.guild.id),
                "channel_id": str(message.channel.id),
                "author_id": str(message.author.id),
                "content": combined_content,
                "created_at": message.created_at.isoformat(),
                "source_type": source_type,
                "ocr_attachment_count": len(ocr_filenames),
                "ocr_filenames": ocr_filenames,
            }

            # 5. Upsert into Qdrant using Discord message ID as canonical Point ID
            await self.vector_store.upsert_message(
                message_id=message.id,
                vector=vector,
                payload=payload,
            )

            logger.info(
                f"Indexed message ID {message.id} (Channel ID: {message.channel.id}, "
                f"source_type: {source_type}) into Qdrant"
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
        """Listener for new Discord text messages and image attachments."""
        await self.index_message(message)

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        """Listener for edited Discord text messages."""
        if before.content == after.content and getattr(before, "attachments", None) == getattr(after, "attachments", None):
            return

        if should_index_message(
            after,
            indexed_channel_ids=self.indexed_channel_ids,
            ocr_channel_ids=self.ocr_channel_ids,
            ocr_max_image_mb=self.ocr_max_image_mb,
        ):
            logger.info(f"Processing edited message ID {after.id}")
            await self.index_message(after)
        else:
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

