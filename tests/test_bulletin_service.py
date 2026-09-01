import json
import asyncio
from types import SimpleNamespace

from bot.services.bulletin import AnySearchNewsClient, BulletinArticle, BulletinState
from bot.cogs.bulletin import BulletinCog
from bot.services.ai import AIError
from bot.services.rewards_db import RewardsDBService


def test_anysearch_parser_extracts_and_deduplicates_articles() -> None:
    payload = {
        "results": [
            {"title": "PH startup update", "url": "https://news.example/story?tracking=1", "snippet": "Details"},
            {"title": "PH startup update", "url": "https://news.example/story?tracking=2", "snippet": "Duplicate"},
        ]
    }

    articles = AnySearchNewsClient._parse_articles(json.dumps(payload))

    assert len(articles) == 1
    assert articles[0].url == "https://news.example/story"


def test_anysearch_parser_supports_numbered_markdown_results() -> None:
    response_text = """## Query 1: latest Philippines technology news today

## Search Results (2 results, 864ms)

### 1. Inquirer Technology
- **URL**: https://technology.inquirer.net/?source=search
- Philippine technology headlines and startup coverage.

### 2. Rappler Technology
- **URL**: https://www.rappler.com/technology/
- Latest reporting about AI and digital policy.
"""

    articles = AnySearchNewsClient._parse_articles(response_text)

    assert [article.title for article in articles] == ["Inquirer Technology", "Rappler Technology"]
    assert articles[0].url == "https://technology.inquirer.net"
    assert articles[0].summary == "Philippine technology headlines and startup coverage."


def test_bulletin_state_deduplicates_per_channel() -> None:
    rewards = RewardsDBService(db_path=":memory:")
    state = BulletinState(rewards)
    article = BulletinArticle("Headline", "https://example.com/story", "Summary", "Example")

    assert state.filter_new([article], channel_id=10) == [article]
    state.mark_posted(article, channel_id=10)
    assert state.filter_new([article], channel_id=10) == []
    assert state.filter_new([article], channel_id=20) == [article]


def test_bulletin_run_keys_are_persistent() -> None:
    rewards = RewardsDBService(db_path=":memory:")
    state = BulletinState(rewards)

    state.record_run("tech:2026-09-01T12", "OK", "3 articles")

    assert state.has_run("tech:2026-09-01T12") is True
    assert state.status()["detail"] == "3 articles"


def test_failed_bulletin_window_can_retry() -> None:
    rewards = RewardsDBService(db_path=":memory:")
    state = BulletinState(rewards)

    state.record_run("tech:2026-09-01T13", "ERROR", "temporary failure")

    assert state.has_run("tech:2026-09-01T13") is False


def test_flash_summary_uses_ai_copy_without_changing_article_metadata() -> None:
    class FakeAI:
        async def ask(self, prompt: str, **kwargs: object) -> str:
            assert "Headline: A major technology update" in prompt
            assert kwargs["max_tokens"] == 180
            return "This update could reshape how students think about the technology they use every day. The details matter more than the headline, and the source has the full story."

    cog = object.__new__(BulletinCog)
    cog.bot = SimpleNamespace(chat_orchestrator=SimpleNamespace(ai_service=FakeAI()))
    article = BulletinArticle(
        "A major technology update",
        "https://example.com/story",
        "A short source snippet.",
        "Example",
        "2026-09-01",
    )

    result = asyncio.run(cog._write_flash_summary(article))

    assert result.title == article.title
    assert result.url == article.url
    assert result.source == article.source
    assert result.summary.startswith("This update could reshape")


def test_flash_summary_falls_back_to_source_snippet_on_ai_error() -> None:
    class FailingAI:
        async def ask(self, prompt: str, **kwargs: object) -> str:
            raise AIError("temporary failure")

    cog = object.__new__(BulletinCog)
    cog.bot = SimpleNamespace(chat_orchestrator=SimpleNamespace(ai_service=FailingAI()))
    article = BulletinArticle("Headline", "https://example.com/story", "Original snippet", "Example")

    result = asyncio.run(cog._write_flash_summary(article))

    assert result == article


def test_flash_summary_rejects_prompt_labels_and_uses_clean_source_text() -> None:
    class MalformedAI:
        async def ask(self, prompt: str, **kwargs: object) -> str:
            return "Source Material: headline and prompt instructions"

    cog = object.__new__(BulletinCog)
    cog.bot = SimpleNamespace(chat_orchestrator=SimpleNamespace(ai_service=MalformedAI()))
    article = BulletinArticle(
        "Technology breakthrough",
        "https://example.com/story",
        "Source Material: A major technology breakthrough was announced.",
        "Example",
    )

    result = asyncio.run(cog._write_flash_summary(article))

    assert result.summary == "A major technology breakthrough was announced."


def test_bulletin_intervals_match_requested_cadence() -> None:
    assert BulletinCog.FLASH_INTERVAL_HOURS == 12
    assert BulletinCog.ECONOMY_INTERVAL_HOURS == 8
    assert BulletinCog.DIGEST_INTERVAL_HOURS == 24
