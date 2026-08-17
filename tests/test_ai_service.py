import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from bot.services.ai import (
    AIService,
    AIConnectionError,
    AIModelNotFoundError,
    AITimeoutError,
    AISafetyBlockError,
    AIEmptyResponseError,
    AIAPIError,
)


def test_ask_success():
    """Test successful AIService prompt generation response parsing."""
    async def _test():
        service = AIService(api_key="test-key", model="gemini-3.5-flash")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "request_id": "request-123",
            "choices": [
                {"message": {"role": "assistant", "content": "Pointers store memory addresses."}}
            ],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.ask("Explain pointers in C")

            assert result == "Pointers store memory addresses."
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["model"] == "gemini-3.5-flash"
            assert payload["max_tokens"] == 1000
            assert payload["messages"][-1]["content"] == "Explain pointers in C"
            assert kwargs["headers"] == {"authorization": "test-key"}

    asyncio.run(_test())


def test_ask_uses_configured_max_tokens():
    """Test the configured generation ceiling is sent to the gateway."""
    async def _test():
        service = AIService(api_key="test-key", max_tokens=250)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "Short answer."}}]
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            await service.ask("Question")

        assert mock_post.call_args.kwargs["json"]["max_tokens"] == 250

    asyncio.run(_test())


def test_ask_allows_a_smaller_per_request_token_limit():
    """Short conversational calls can override the service-wide generation ceiling."""
    async def _test():
        service = AIService(api_key="test-key", max_tokens=400)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "Got it."}}]
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            await service.ask("Be concise", max_tokens=120)

        assert mock_post.call_args.kwargs["json"]["max_tokens"] == 120

    asyncio.run(_test())


def test_ask_connection_error():
    """AIService maps gateway connection failures to AIConnectionError."""
    async def _test():
        service = AIService(api_key="test-key")

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(AIConnectionError, match="Cannot connect to the AI gateway"):
                await service.ask("Test question")

    asyncio.run(_test())


def test_ask_model_not_found():
    """AIService maps a missing gateway model to AIModelNotFoundError."""
    async def _test():
        service = AIService(api_key="test-key", model="nonexistent-model")

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(AIModelNotFoundError, match="is not available"):
                await service.ask("Test question")

    asyncio.run(_test())


def test_ask_timeout_error():
    """AIService maps gateway timeouts to AITimeoutError."""
    async def _test():
        service = AIService(api_key="test-key")

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.TimeoutException("Timed out"),
        ):
            with pytest.raises(AITimeoutError, match="timed out"):
                await service.ask("Test question")

    asyncio.run(_test())


def test_ask_invalid_json_structure():
    """Test AIService raises AIAPIError when the response lacks expected keys."""
    async def _test():
        service = AIService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"unexpected_key": "data"}

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(AIAPIError, match="invalid response structure"):
                await service.ask("Test question")

    asyncio.run(_test())


def test_ask_accepts_structured_text_parts() -> None:
    """Provider-normalized text parts are combined into one assistant message."""
    async def _test() -> None:
        service = AIService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {}
        mock_response.json.return_value = {
            "request_id": "request-parts",
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "First paragraph."},
                        {"type": "text", "text": "Second paragraph."},
                    ],
                },
            }],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.ask("Explain this")

        assert result == "First paragraph.\nSecond paragraph."

    asyncio.run(_test())


def test_complete_returns_tool_calls_and_usage() -> None:
    async def _test() -> None:
        service = AIService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"x-request-id": "header-id"}
        mock_response.json.return_value = {
            "request_id": "request-456",
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "get_class_schedule", "arguments": "{\"when\":\"today\"}"}}
            ]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.complete(
                [{"role": "user", "content": "classes today?"}],
                tools=[{"type": "function", "function": {"name": "get_class_schedule"}}],
                tool_choice="auto",
            )

        assert result.request_id == "request-456"
        assert result.tool_calls[0]["function"]["name"] == "get_class_schedule"
        assert result.usage.total_tokens == 14
        payload = mock_post.call_args.kwargs["json"]
        assert payload["tool_choice"] == "auto"

    asyncio.run(_test())


def test_complete_accepts_choice_level_tool_calls() -> None:
    """Tool calls remain usable if the gateway places them on the choice."""
    async def _test() -> None:
        service = AIService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {}
        mock_response.json.return_value = {
            "request_id": "request-choice-tool",
            "choices": [{
                "finish_reason": "tool_use",
                "message": {"role": "assistant", "content": None},
                "tool_calls": [{
                    "id": "call-2",
                    "type": "function",
                    "function": {
                        "name": "get_latest_assignments",
                        "arguments": "{}",
                    },
                }],
            }],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.complete(
                [{"role": "user", "content": "latest assignments?"}]
            )

        assert result.content is None
        assert result.tool_calls[0]["function"]["name"] == "get_latest_assignments"

    asyncio.run(_test())


def test_complete_raises_safety_block_error_on_safety_finish_reason():
    """AIService raises AISafetyBlockError when finish_reason indicates a safety filter block."""
    async def _test():
        service = AIService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {}
        mock_response.json.return_value = {
            "request_id": "req-safety-1",
            "choices": [{
                "finish_reason": "safety",
                "message": {"role": "assistant", "content": None},
            }],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises(AISafetyBlockError, match="blocked by AI safety policy"):
                await service.complete([{"role": "user", "content": "unsafe query"}])

    asyncio.run(_test())


def test_complete_raises_empty_response_error_on_empty_payload():
    """AIService raises AIEmptyResponseError when gateway returns no content and no tool calls."""
    async def _test():
        service = AIService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {}
        mock_response.json.return_value = {
            "request_id": "req-empty-1",
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": None},
                "tool_calls": [],
            }],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises(AIEmptyResponseError, match="empty text response"):
                await service.complete([{"role": "user", "content": "empty result query"}])

    asyncio.run(_test())
