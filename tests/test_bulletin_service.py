import json

from bot.services.bulletin import AnySearchNewsClient, BulletinArticle, BulletinState
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
