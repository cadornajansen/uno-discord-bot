import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from bot.services.ai import (
    AIService,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    OllamaAPIError,
)


def test_ask_success():
    """Test successful AIService prompt generation response parsing."""
    async def _test():
        service = AIService(base_url="http://localhost:11434", model="phi4-mini")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "model": "phi4-mini",
            "message": {"role": "assistant", "content": "Pointers store memory addresses."},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.ask("Explain pointers in C")

            assert result == "Pointers store memory addresses."
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["model"] == "phi4-mini"
            assert payload["stream"] is False
            assert payload["messages"][-1]["content"] == "Explain pointers in C"

    asyncio.run(_test())


def test_ask_connection_error():
    """Test AIService raises OllamaConnectionError when Ollama service is unreachable."""
    async def _test():
        service = AIService()

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(OllamaConnectionError, match="Cannot connect to Ollama"):
                await service.ask("Test question")

    asyncio.run(_test())


def test_ask_model_not_found():
    """Test AIService raises OllamaModelNotFoundError when Ollama returns HTTP 404."""
    async def _test():
        service = AIService(model="nonexistent-model")

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(OllamaModelNotFoundError, match="is not available"):
                await service.ask("Test question")

    asyncio.run(_test())


def test_ask_timeout_error():
    """Test AIService raises OllamaTimeoutError when request times out."""
    async def _test():
        service = AIService()

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.TimeoutException("Timed out"),
        ):
            with pytest.raises(OllamaTimeoutError, match="timed out"):
                await service.ask("Test question")

    asyncio.run(_test())


def test_ask_invalid_json_structure():
    """Test AIService raises OllamaAPIError when response JSON lacks expected keys."""
    async def _test():
        service = AIService()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"unexpected_key": "data"}

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(OllamaAPIError, match="invalid response structure"):
                await service.ask("Test question")

    asyncio.run(_test())
