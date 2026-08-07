import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from bot.services.embeddings import (
    EmbeddingService,
    EmbeddingError,
    OllamaEmbeddingConnectionError,
    OllamaEmbeddingModelNotFoundError,
    OllamaEmbeddingTimeoutError,
)


def test_embed_success():
    """Test successful embedding generation response parsing."""
    async def _test():
        service = EmbeddingService(base_url="http://localhost:11434", model="embeddinggemma")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "model": "embeddinggemma",
            "embeddings": [[0.1, 0.2, 0.3, 0.4]],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.embed("Our quiz is on Monday.")

            assert result == [0.1, 0.2, 0.3, 0.4]
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["model"] == "embeddinggemma"
            assert payload["input"] == "Our quiz is on Monday."
            assert payload["truncate"] is True

    asyncio.run(_test())


def test_embed_empty_text():
    """Test generating embedding for empty text raises EmbeddingError."""
    async def _test():
        service = EmbeddingService()
        with pytest.raises(EmbeddingError, match="empty text"):
            await service.embed("   ")

    asyncio.run(_test())


def test_embed_connection_error():
    """Test EmbeddingService raises OllamaEmbeddingConnectionError when connection fails."""
    async def _test():
        service = EmbeddingService()

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(OllamaEmbeddingConnectionError, match="Cannot connect"):
                await service.embed("Test message")

    asyncio.run(_test())


def test_embed_model_not_found():
    """Test EmbeddingService raises OllamaEmbeddingModelNotFoundError on HTTP 404."""
    async def _test():
        service = EmbeddingService(model="missing-embed-model")

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(OllamaEmbeddingModelNotFoundError, match="is not available"):
                await service.embed("Test message")

    asyncio.run(_test())


def test_embed_timeout_error():
    """Test EmbeddingService raises OllamaEmbeddingTimeoutError when request times out."""
    async def _test():
        service = EmbeddingService()

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.TimeoutException("Timed out"),
        ):
            with pytest.raises(OllamaEmbeddingTimeoutError, match="timed out"):
                await service.embed("Test message")

    asyncio.run(_test())


def test_embed_invalid_response_payload():
    """Test EmbeddingService raises EmbeddingError on malformed response JSON."""
    async def _test():
        service = EmbeddingService()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"invalid_field": "data"}

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(EmbeddingError, match="invalid embedding payload"):
                await service.embed("Test message")

    asyncio.run(_test())
