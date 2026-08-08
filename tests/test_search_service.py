import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from bot.services.search import (
    SearchService,
    SearchResult,
    SearchError,
    SearchConfigError,
    SerperAPIError,
    SearchConnectionError,
    SearchTimeoutError,
)


def test_search_service_missing_api_key():
    """Test that missing API key raises SearchConfigError."""
    async def _test():
        service = SearchService(api_key="")
        with pytest.raises(SearchConfigError, match="Serper API key is missing"):
            await service.search("python tutorial")

    asyncio.run(_test())


def test_search_service_empty_and_long_query():
    """Test that empty query or query exceeding 300 characters raises SearchError."""
    async def _test():
        service = SearchService(api_key="mock_key")

        with pytest.raises(SearchError, match="cannot be empty"):
            await service.search("   ")

        with pytest.raises(SearchError, match="too long"):
            await service.search("a" * 301)

    asyncio.run(_test())


def test_successful_search_parses_organic_results():
    """Test parsing of valid organic search response."""
    async def _test():
        service = SearchService(api_key="test_api_key", base_url="https://google.serper.dev")

        mock_payload = {
            "organic": [
                {
                    "title": "Code a simple RAG from scratch",
                    "link": "https://huggingface.co/blog/rag",
                    "snippet": "In this blog post, we explore RAG...",
                },
                {
                    "title": "Deep Agents RAG",
                    "link": "https://docs.langchain.com/agents",
                    "snippet": "RAG patterns for Deep Agents...",
                },
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_payload
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            results = await service.search("rag tutorial python", limit=5)

            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            assert kwargs["headers"]["X-API-KEY"] == "test_api_key"
            assert kwargs["json"] == {"q": "rag tutorial python"}

            assert len(results) == 2
            assert results[0] == SearchResult(
                title="Code a simple RAG from scratch",
                url="https://huggingface.co/blog/rag",
                snippet="In this blog post, we explore RAG...",
            )
            assert results[1].title == "Deep Agents RAG"

    asyncio.run(_test())


def test_search_result_limit_respected():
    """Test that results list is capped at the specified limit."""
    async def _test():
        service = SearchService(api_key="test_key")

        organic_items = [
            {"title": f"Result {i}", "link": f"https://example.com/{i}", "snippet": f"Snippet {i}"}
            for i in range(10)
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"organic": organic_items}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            results = await service.search("python", limit=3)
            assert len(results) == 3
            assert results[2].title == "Result 2"

    asyncio.run(_test())


def test_missing_snippet_handled_safely():
    """Test that organic item without a snippet returns empty string snippet."""
    async def _test():
        service = SearchService(api_key="test_key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "organic": [{"title": "No Snippet Title", "link": "https://example.com"}]
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            results = await service.search("python")
            assert len(results) == 1
            assert results[0].snippet == ""

    asyncio.run(_test())


def test_serper_auth_failure_raises_serper_api_error():
    """Test HTTP 401/403 status raises SerperAPIError."""
    async def _test():
        service = SearchService(api_key="invalid_key")

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(SerperAPIError, match="authentication failed"):
                await service.search("python")

    asyncio.run(_test())


def test_serper_rate_limit_raises_serper_api_error():
    """Test HTTP 429 status raises SerperAPIError."""
    async def _test():
        service = SearchService(api_key="test_key")

        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(SerperAPIError, match="rate limit exceeded"):
                await service.search("python")

    asyncio.run(_test())


def test_timeout_raises_search_timeout_error():
    """Test timeout exception raises SearchTimeoutError."""
    async def _test():
        service = SearchService(api_key="test_key")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")

            with pytest.raises(SearchTimeoutError, match="timed out"):
                await service.search("python")

    asyncio.run(_test())


def test_connection_error_raises_search_connection_error():
    """Test connect exception raises SearchConnectionError."""
    async def _test():
        service = SearchService(api_key="test_key")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(SearchConnectionError, match="Cannot connect"):
                await service.search("python")

    asyncio.run(_test())
