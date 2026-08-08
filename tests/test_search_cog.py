import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from bot.cogs.search import SearchCog, extract_domain, format_search_results
from bot.services.search import SearchResult, SearchConfigError, SearchError


def test_extract_domain_helper():
    """Test extract_domain parses hostnames and strips 'www.' prefix."""
    assert extract_domain("https://huggingface.co/blog/rag") == "huggingface.co"
    assert extract_domain("https://www.docs.langchain.com/agents") == "docs.langchain.com"
    assert extract_domain("https://github.com/uno/bot") == "github.com"
    assert extract_domain("invalid_url") == "web"


def test_format_search_results_formatting():
    """Test format_search_results builds markdown title, italicized domain, and snippet."""
    results = [
        SearchResult(
            title="Code RAG",
            url="https://huggingface.co/blog/rag",
            snippet="Exploring RAG...",
        ),
        SearchResult(
            title="Deep Agents",
            url="https://docs.langchain.com/agents",
            snippet="RAG for agents...",
        ),
    ]

    formatted = format_search_results("rag tutorial python", results)

    assert "Search results for: **rag tutorial python**" in formatted
    assert "**1. [Code RAG](https://huggingface.co/blog/rag)**" in formatted
    assert "*huggingface.co*" in formatted
    assert "Exploring RAG..." in formatted
    assert "**2. [Deep Agents](https://docs.langchain.com/agents)**" in formatted
    assert "*docs.langchain.com*" in formatted


def test_format_search_results_empty():
    """Test format_search_results clean output when results list is empty."""
    formatted = format_search_results("unknown query", [])
    assert formatted == "No search results found for **unknown query**."


def test_search_cog_command_execution():
    """Test SearchCog /search slash command flow."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = SearchCog(bot)

        mock_results = [
            SearchResult(
                title="Python Tutorial",
                url="https://python.org/doc",
                snippet="Official Python docs.",
            )
        ]
        cog.search_service.search = AsyncMock(return_value=mock_results)

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.search.callback(cog, interaction, query="python binary search")

        interaction.response.defer.assert_called_once()
        cog.search_service.search.assert_called_once_with("python binary search", limit=5)
        interaction.followup.send.assert_called_once()

        sent_text = interaction.followup.send.call_args[0][0]
        assert "Search results for: **python binary search**" in sent_text
        assert "**1. [Python Tutorial](https://python.org/doc)**" in sent_text
        assert "*python.org*" in sent_text

    asyncio.run(_test())


def test_search_cog_empty_query_rejected():
    """Test SearchCog rejects empty query prior to deferring interaction."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = SearchCog(bot)
        cog.search_service.search = AsyncMock()

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.defer = AsyncMock()

        await cog.search.callback(cog, interaction, query="   ")

        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()
        cog.search_service.search.assert_not_called()

    asyncio.run(_test())


def test_search_cog_unconfigured_api_key_handled():
    """Test SearchCog sends user-friendly error when API key is missing."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = SearchCog(bot)
        cog.search_service.search = AsyncMock(side_effect=SearchConfigError("Missing key"))

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.search.callback(cog, interaction, query="rag tutorial")

        interaction.response.defer.assert_called_once()
        interaction.followup.send.assert_called_once()
        sent_text = interaction.followup.send.call_args[0][0]
        assert "Web search is currently unavailable" in sent_text

    asyncio.run(_test())
