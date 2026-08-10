import logging
from collections.abc import Collection
from typing import Any, Optional
from qdrant_client import AsyncQdrantClient, models

logger = logging.getLogger(__name__)


class VectorStoreError(Exception):
    """Base exception for vector store operations."""

    pass


class VectorStoreConnectionError(VectorStoreError):
    """Raised when unable to connect to Qdrant vector database."""

    pass


class VectorStoreDimensionMismatchError(VectorStoreError):
    """Raised when provided vector length does not match existing collection vector size."""

    pass


class VectorStore:
    """Service wrapping Qdrant vector database operations using AsyncQdrantClient."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection_name: str = "discord_messages",
    ):
        self.url = url.rstrip("/")
        self.collection_name = collection_name
        self._client: Optional[AsyncQdrantClient] = None

    @property
    def client(self) -> AsyncQdrantClient:
        """Lazy initializer for AsyncQdrantClient."""
        if self._client is None:
            self._client = AsyncQdrantClient(url=self.url)
        return self._client

    async def _ensure_collection(self, vector_dim: int) -> None:
        """Verify collection exists with matching vector dimension, creating it if needed.

        Raises:
            VectorStoreDimensionMismatchError: If existing collection vector size differs.
            VectorStoreConnectionError: If unable to communicate with Qdrant.
        """
        try:
            exists = await self.client.collection_exists(self.collection_name)

            if not exists:
                logger.info(
                    f"Creating Qdrant collection '{self.collection_name}' with vector size {vector_dim} (Cosine)"
                )
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_dim,
                        distance=models.Distance.COSINE,
                    ),
                )

                # Create payload indexes for frequent filtering fields
                for field in ("guild_id", "channel_id", "author_id"):
                    try:
                        await self.client.create_payload_index(
                            collection_name=self.collection_name,
                            field_name=field,
                            field_schema=models.PayloadSchemaType.KEYWORD,
                        )
                        logger.info(f"Created payload index on '{field}' in collection '{self.collection_name}'")
                    except Exception as idx_err:
                        logger.warning(f"Could not create payload index for '{field}': {idx_err}")

            else:
                info = await self.client.get_collection(self.collection_name)
                # Safely extract configured vector size
                vectors_config = info.config.params.vectors
                if isinstance(vectors_config, models.VectorParams):
                    existing_dim = vectors_config.size
                elif isinstance(vectors_config, dict) and "size" in vectors_config:
                    existing_dim = vectors_config["size"]
                else:
                    existing_dim = getattr(vectors_config, "size", vector_dim)

                if existing_dim != vector_dim:
                    logger.error(
                        f"Collection '{self.collection_name}' vector dimension ({existing_dim}) "
                        f"does not match incoming vector length ({vector_dim})."
                    )
                    raise VectorStoreDimensionMismatchError(
                        f"Vector dimension mismatch: collection expects {existing_dim}, got {vector_dim}."
                    )

        except (VectorStoreDimensionMismatchError, VectorStoreConnectionError):
            raise
        except Exception as e:
            logger.error(f"Failed to verify or create Qdrant collection '{self.collection_name}': {e}")
            raise VectorStoreConnectionError(f"Cannot connect to Qdrant at {self.url}: {e}") from e

    async def upsert_message(
        self,
        *,
        message_id: int,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Upsert a message vector and metadata point into Qdrant.

        Args:
            message_id: Discord message ID (used as stable integer Point ID).
            vector: Embedding vector.
            payload: Metadata dictionary (guild_id, channel_id, author_id, content, created_at).
        """
        vector_dim = len(vector)
        await self._ensure_collection(vector_dim)

        point = models.PointStruct(
            id=message_id,
            vector=vector,
            payload=payload,
        )

        try:
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[point],
            )
            logger.debug(f"Upserted message ID {message_id} into Qdrant collection '{self.collection_name}'")
        except Exception as e:
            logger.error(f"Failed to upsert point {message_id} into Qdrant: {e}")
            raise VectorStoreConnectionError(f"Qdrant point upsert failed: {e}") from e

    async def search_similar(
        self,
        vector: list[float],
        *,
        limit: int = 5,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        channel_ids: Optional[Collection[int]] = None,
    ) -> list[dict[str, Any]]:
        """Search nearest points in Qdrant by cosine similarity with optional guild/channel filtering.

        Args:
            vector: Dense query embedding vector.
            limit: Maximum number of points to return (default: 5).
            guild_id: Optional guild ID to filter by.
            channel_id: Optional channel ID to filter by.
            channel_ids: Optional collection of channel IDs to filter by.

        Returns:
            List of dictionaries containing score and payload metadata.
        """
        await self._ensure_collection(len(vector))

        must_filters = []
        if guild_id is not None:
            must_filters.append(
                models.FieldCondition(
                    key="guild_id",
                    match=models.MatchValue(value=str(guild_id)),
                )
            )
        if channel_id is not None:
            must_filters.append(
                models.FieldCondition(
                    key="channel_id",
                    match=models.MatchValue(value=str(channel_id)),
                )
            )
        elif channel_ids:
            must_filters.append(
                models.FieldCondition(
                    key="channel_id",
                    match=models.MatchAny(
                        any=[str(candidate_id) for candidate_id in channel_ids]
                    ),
                )
            )

        query_filter = models.Filter(must=must_filters) if must_filters else None

        try:
            if hasattr(self.client, "query_points"):
                response = await self.client.query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    query_filter=query_filter,
                    limit=limit,
                )
                points = getattr(response, "points", [])
            else:
                points = await self.client.search(
                    collection_name=self.collection_name,
                    query_vector=vector,
                    query_filter=query_filter,
                    limit=limit,
                )

            return [
                {
                    "score": getattr(point, "score", 0.0),
                    "payload": getattr(point, "payload", {}) or {},
                }
                for point in points
            ]
        except Exception as e:
            logger.error(f"Failed to search Qdrant collection '{self.collection_name}': {e}")
            raise VectorStoreConnectionError(f"Qdrant search failed: {e}") from e

    async def list_recent_messages(
        self,
        *,
        guild_id: int,
        channel_ids: Collection[int],
        limit: int = 20,
        scan_limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return recent stored messages from selected channels by creation time."""
        if limit <= 0 or scan_limit <= 0 or not channel_ids:
            return []

        try:
            if not await self.client.collection_exists(self.collection_name):
                return []

            message_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="guild_id",
                        match=models.MatchValue(value=str(guild_id)),
                    ),
                    models.FieldCondition(
                        key="channel_id",
                        match=models.MatchAny(
                            any=[str(channel_id) for channel_id in channel_ids]
                        ),
                    ),
                ]
            )
            records = []
            offset = None

            while len(records) < scan_limit:
                page_limit = min(100, scan_limit - len(records))
                page, offset = await self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=message_filter,
                    limit=page_limit,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                records.extend(page)
                if offset is None:
                    break

            records.sort(
                key=lambda record: str(
                    (getattr(record, "payload", {}) or {}).get("created_at", "")
                ),
                reverse=True,
            )
            return [
                {
                    "score": 1.0,
                    "payload": getattr(record, "payload", {}) or {},
                }
                for record in records[:limit]
            ]
        except Exception as e:
            logger.error(
                f"Failed to list recent messages from Qdrant collection "
                f"'{self.collection_name}': {e}"
            )
            raise VectorStoreConnectionError(
                f"Qdrant recent-message lookup failed: {e}"
            ) from e

    async def delete_channel_messages(self, channel_id: int) -> None:
        """Delete every stored message whose payload matches one channel ID."""
        try:
            if not await self.client.collection_exists(self.collection_name):
                return

            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="channel_id",
                                match=models.MatchValue(value=str(channel_id)),
                            )
                        ]
                    )
                ),
                wait=True,
            )
            logger.info(
                f"Deleted stored messages for channel ID {channel_id} from "
                f"Qdrant collection '{self.collection_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to delete channel ID {channel_id} from Qdrant collection "
                f"'{self.collection_name}': {e}"
            )
            raise VectorStoreConnectionError(
                f"Qdrant channel deletion failed: {e}"
            ) from e

    async def delete_message(self, message_id: int) -> None:
        """Delete a point from Qdrant by its integer Discord message ID.

        Args:
            message_id: Discord message ID corresponding to Qdrant Point ID.

        Raises:
            VectorStoreConnectionError: If unable to communicate with Qdrant.
        """
        try:
            exists = await self.client.collection_exists(self.collection_name)
            if not exists:
                logger.debug(f"Collection '{self.collection_name}' does not exist. Skipping point deletion.")
                return

            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[message_id]),
            )
            logger.info(f"Deleted point ID {message_id} from Qdrant collection '{self.collection_name}'")
        except Exception as e:
            logger.error(f"Failed to delete point {message_id} from Qdrant collection '{self.collection_name}': {e}")
            raise VectorStoreConnectionError(f"Qdrant point deletion failed: {e}") from e

    async def query_similar(
        self,
        vector: list[float],
        limit: int = 5,
        channel_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Backwards-compatible query helper wrapper calling search_similar."""
        return await self.search_similar(vector, limit=limit, channel_id=channel_id)

    async def close(self) -> None:
        """Close Qdrant client connections if open."""
        if self._client is not None:
            await self._client.close()
            self._client = None
