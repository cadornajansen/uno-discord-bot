import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from qdrant_client import models

from bot.services.vector_store import (
    VectorStore,
    VectorStoreDimensionMismatchError,
    VectorStoreConnectionError,
)


def test_upsert_message_success():
    """Test VectorStore upsert_message creates point with message_id as Point ID."""
    async def _test():
        store = VectorStore(url="http://localhost:6333", collection_name="discord_messages")

        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = True

        mock_collection_info = MagicMock()
        mock_collection_info.config.params.vectors = models.VectorParams(
            size=4,
            distance=models.Distance.COSINE,
        )
        mock_client.get_collection.return_value = mock_collection_info

        store._client = mock_client

        payload = {
            "message_id": "1122334455",
            "guild_id": "100",
            "channel_id": "200",
            "author_id": "300",
            "content": "Test content",
            "created_at": "2026-08-08T00:00:00Z",
        }

        await store.upsert_message(
            message_id=1122334455,
            vector=[0.1, 0.2, 0.3, 0.4],
            payload=payload,
        )

        mock_client.upsert.assert_called_once()
        _, kwargs = mock_client.upsert.call_args
        assert kwargs["collection_name"] == "discord_messages"
        points = kwargs["points"]
        assert len(points) == 1
        assert points[0].id == 1122334455
        assert points[0].vector == [0.1, 0.2, 0.3, 0.4]
        assert points[0].payload["content"] == "Test content"

    asyncio.run(_test())


def test_delete_message_success():
    """Test VectorStore delete_message calls client.delete using exact integer message ID."""
    async def _test():
        store = VectorStore(url="http://localhost:6333", collection_name="discord_messages")

        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = True
        store._client = mock_client

        await store.delete_message(message_id=987654321)

        mock_client.delete.assert_called_once()
        _, kwargs = mock_client.delete.call_args
        assert kwargs["collection_name"] == "discord_messages"
        selector = kwargs["points_selector"]
        assert isinstance(selector, models.PointIdsList)
        assert selector.points == [987654321]

    asyncio.run(_test())


def test_delete_channel_messages_uses_exact_payload_filter():
    """Channel purge deletes only points matching the retired channel ID."""
    async def _test():
        store = VectorStore()
        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = True
        store._client = mock_client

        await store.delete_channel_messages(1531615193786876062)

        selector = mock_client.delete.call_args.kwargs["points_selector"]
        assert isinstance(selector, models.FilterSelector)
        condition = selector.filter.must[0]
        assert condition.key == "channel_id"
        assert condition.match.value == "1531615193786876062"
        assert mock_client.delete.call_args.kwargs["wait"] is True

    asyncio.run(_test())


def test_search_similar_success():
    """Test VectorStore search_similar returns ranked items with payload and scores."""
    async def _test():
        store = VectorStore()

        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = True

        mock_collection_info = MagicMock()
        mock_collection_info.config.params.vectors = models.VectorParams(
            size=2,
            distance=models.Distance.COSINE,
        )
        mock_client.get_collection.return_value = mock_collection_info

        mock_point = MagicMock()
        mock_point.score = 0.85
        mock_point.payload = {"content": "Our DSA quiz is on Friday."}

        mock_response = MagicMock()
        mock_response.points = [mock_point]

        mock_client.query_points.return_value = mock_response
        store._client = mock_client

        results = await store.search_similar(vector=[0.1, 0.2], limit=3, channel_id=123)

        assert len(results) == 1
        assert results[0]["score"] == 0.85
        assert results[0]["payload"]["content"] == "Our DSA quiz is on Friday."
        mock_client.query_points.assert_called_once()

    asyncio.run(_test())


def test_search_similar_filters_multiple_homework_channels():
    """Homework search can be restricted to an explicit channel set."""
    async def _test():
        store = VectorStore()
        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = True
        collection_info = MagicMock()
        collection_info.config.params.vectors = models.VectorParams(
            size=2,
            distance=models.Distance.COSINE,
        )
        mock_client.get_collection.return_value = collection_info
        response = MagicMock()
        response.points = []
        mock_client.query_points.return_value = response
        store._client = mock_client

        await store.search_similar(
            [0.1, 0.2],
            guild_id=777,
            channel_ids=frozenset({100, 200}),
        )

        query_filter = mock_client.query_points.call_args.kwargs["query_filter"]
        channel_condition = query_filter.must[1]
        assert channel_condition.key == "channel_id"
        assert set(channel_condition.match.any) == {"100", "200"}

    asyncio.run(_test())


def test_list_recent_messages_sorts_payload_dates_descending():
    """Recent-message lookup returns newest channel records first."""
    async def _test():
        store = VectorStore()
        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = True
        older = MagicMock()
        older.payload = {"created_at": "2026-08-01T00:00:00Z", "content": "Older"}
        newer = MagicMock()
        newer.payload = {"created_at": "2026-08-10T00:00:00Z", "content": "Newer"}
        mock_client.scroll.return_value = ([older, newer], None)
        store._client = mock_client

        results = await store.list_recent_messages(
            guild_id=777,
            channel_ids=frozenset({100}),
            limit=2,
        )

        assert [result["payload"]["content"] for result in results] == [
            "Newer",
            "Older",
        ]
        scroll_filter = mock_client.scroll.call_args.kwargs["scroll_filter"]
        assert scroll_filter.must[0].match.value == "777"
        assert scroll_filter.must[1].match.any == ["100"]

    asyncio.run(_test())


def test_dimension_mismatch_error():
    """Test that dimension mismatch between collection and incoming vector raises VectorStoreDimensionMismatchError."""
    async def _test():
        store = VectorStore()

        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = True

        mock_collection_info = MagicMock()
        mock_collection_info.config.params.vectors = models.VectorParams(
            size=768,
            distance=models.Distance.COSINE,
        )
        mock_client.get_collection.return_value = mock_collection_info

        store._client = mock_client

        with pytest.raises(VectorStoreDimensionMismatchError, match="expects 768, got 4"):
            await store.upsert_message(
                message_id=12345,
                vector=[0.1, 0.2, 0.3, 0.4],
                payload={},
            )

    asyncio.run(_test())


def test_collection_creation_on_first_upsert():
    """Test that VectorStore creates collection and payload indexes when collection does not exist."""
    async def _test():
        store = VectorStore()

        mock_client = AsyncMock()
        mock_client.collection_exists.return_value = False
        store._client = mock_client

        await store.upsert_message(
            message_id=999,
            vector=[0.5, 0.6],
            payload={"content": "Hello"},
        )

        mock_client.create_collection.assert_called_once()
        assert mock_client.create_payload_index.call_count == 3

    asyncio.run(_test())
