import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from bot.services.embeddings import (
    EmbeddingService,
    EmbeddingError,
    EmbeddingConnectionError,
    EmbeddingModelNotFoundError,
    EmbeddingTimeoutError,
)


def test_embed_success():
    """Test successful embedding generation response parsing."""
    async def _test():
        service = EmbeddingService(api_key="test-key", output_dimensionality=4)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "embeddings": [{"values": [0.1, 0.2, 0.3, 0.4]}],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.embed("Our quiz is on Monday.")

            assert result == [0.1, 0.2, 0.3, 0.4]
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["content"]["parts"][0]["text"] == (
                "task: question answering | query: Our quiz is on Monday."
            )
            assert payload["output_dimensionality"] == 4
            assert kwargs["headers"] == {"x-goog-api-key": "test-key"}

    asyncio.run(_test())


def test_embed_empty_text():
    """Test generating embedding for empty text raises EmbeddingError."""
    async def _test():
        service = EmbeddingService(api_key="test-key")
        with pytest.raises(EmbeddingError, match="empty text"):
            await service.embed("   ")

    asyncio.run(_test())


def test_embed_document_uses_retrieval_document_format():
    """Indexed messages use Gemini's asymmetric document format."""
    async def _test():
        service = EmbeddingService(api_key="test-key", output_dimensionality=2)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "embeddings": [{"values": [0.1, 0.2]}]
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            await service.embed(
                "FOP assignment is due Friday.",
                task_type="document",
                title="homework-assignments",
            )

        prepared_text = mock_post.call_args.kwargs["json"]["content"]["parts"][0]["text"]
        assert prepared_text == (
            "title: homework-assignments | text: FOP assignment is due Friday."
        )

    asyncio.run(_test())


def test_embed_connection_error():
    """EmbeddingService maps Gemini connection errors."""
    async def _test():
        service = EmbeddingService(api_key="test-key")

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(EmbeddingConnectionError, match="Cannot connect"):
                await service.embed("Test message")

    asyncio.run(_test())


def test_embed_model_not_found():
    """EmbeddingService maps missing Gemini models."""
    async def _test():
        service = EmbeddingService(api_key="test-key", model="missing-embed-model")

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(EmbeddingModelNotFoundError, match="is not available"):
                await service.embed("Test message")

    asyncio.run(_test())


def test_embed_timeout_error():
    """EmbeddingService maps Gemini request timeouts."""
    async def _test():
        service = EmbeddingService(api_key="test-key")

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.TimeoutException("Timed out"),
        ):
            with pytest.raises(EmbeddingTimeoutError, match="timed out"):
                await service.embed("Test message")

    asyncio.run(_test())


def test_embed_invalid_response_payload():
    """Test EmbeddingService raises EmbeddingError on malformed response JSON."""
    async def _test():
        service = EmbeddingService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"invalid_field": "data"}

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(EmbeddingError, match="invalid embedding payload"):
                await service.embed("Test message")

    asyncio.run(_test())
