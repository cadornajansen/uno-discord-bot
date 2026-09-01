from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from bot.services.rewards_db import RewardsDBService


ANYSEARCH_ENDPOINT = "https://api.anysearch.com/mcp"


@dataclass(frozen=True)
class BulletinArticle:
    title: str
    url: str
    summary: str
    source: str
    published_at: str = ""

    @property
    def fingerprint(self) -> str:
        value = f"{self.title.casefold().strip()}|{self.url.casefold().strip()}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AnySearchNewsClient:
    """Small native AnySearch JSON-RPC client suitable for the deployed bot."""

    def __init__(self, api_key: str = "", timeout_seconds: float = 30.0):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def search(self, queries: list[str], max_results: int = 5) -> list[BulletinArticle]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "batch_search",
                "arguments": {
                    "queries": [{"query": query, "max_results": max_results} for query in queries[:5]],
                },
            },
        }
        headers = {"Content-Type": "application/json", "X-Anysearch-Client": "uno-ai-bulletin/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(ANYSEARCH_ENDPOINT, json=payload, headers=headers)
            response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"].get("message", data["error"])))
        texts = [item.get("text", "") for item in data.get("result", {}).get("content", []) if item.get("type") == "text"]
        return self._parse_articles("\n".join(texts))

    @classmethod
    def _parse_articles(cls, text: str) -> list[BulletinArticle]:
        candidates: list[dict[str, Any]] = []
        try:
            parsed = json.loads(text)
            cls._collect_dicts(parsed, candidates)
        except (json.JSONDecodeError, TypeError):
            pass
        articles: list[BulletinArticle] = []
        for item in candidates:
            title = str(item.get("title") or item.get("name") or "").strip()
            url = str(item.get("url") or item.get("link") or "").strip()
            if not title or not url.startswith(("http://", "https://")):
                continue
            summary = str(item.get("snippet") or item.get("description") or item.get("content") or "").strip()
            source = str(item.get("source") or item.get("domain") or urlsplit(url).netloc).strip()
            published = str(item.get("published_at") or item.get("published_date") or item.get("date") or "").strip()
            articles.append(BulletinArticle(title[:200], cls._canonical_url(url), summary[:500], source[:100], published[:80]))
        if not articles:
            for title, url in re.findall(r"\[([^\]]{5,200})\]\((https?://[^)\s]+)\)", text):
                articles.append(BulletinArticle(title.strip(), cls._canonical_url(url), "", urlsplit(url).netloc))
        unique: dict[str, BulletinArticle] = {}
        for article in articles:
            unique.setdefault(article.fingerprint, article)
        return list(unique.values())

    @classmethod
    def _collect_dicts(cls, value: Any, output: list[dict[str, Any]]) -> None:
        if isinstance(value, dict):
            if ("url" in value or "link" in value) and ("title" in value or "name" in value):
                output.append(value)
            for child in value.values():
                cls._collect_dicts(child, output)
        elif isinstance(value, list):
            for child in value:
                cls._collect_dicts(child, output)

    @staticmethod
    def _canonical_url(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), "", ""))


class BulletinState:
    """Persistent bulletin deduplication and schedule-window state."""

    def __init__(self, rewards: RewardsDBService):
        self.rewards = rewards
        with self.rewards._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bulletin_articles (
                    fingerprint TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    posted_at TEXT NOT NULL,
                    PRIMARY KEY(fingerprint, channel_id)
                );
                CREATE TABLE IF NOT EXISTS bulletin_runs (
                    run_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    detail TEXT,
                    completed_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def has_run(self, run_key: str) -> bool:
        with self.rewards._get_connection() as conn:
            return conn.execute(
                "SELECT 1 FROM bulletin_runs WHERE run_key = ? AND status = 'OK'",
                (run_key,),
            ).fetchone() is not None

    def record_run(self, run_key: str, status: str, detail: str = "") -> None:
        with self.rewards._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bulletin_runs (run_key, status, detail, completed_at) VALUES (?, ?, ?, ?)",
                (run_key, status, detail[:500], datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def filter_new(self, articles: Iterable[BulletinArticle], channel_id: int, hours: int = 72) -> list[BulletinArticle]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = []
        with self.rewards._get_connection() as conn:
            for article in articles:
                row = conn.execute(
                    "SELECT 1 FROM bulletin_articles WHERE fingerprint = ? AND channel_id = ? AND posted_at >= ?",
                    (article.fingerprint, channel_id, cutoff),
                ).fetchone()
                if not row:
                    result.append(article)
        return result

    def mark_posted(self, article: BulletinArticle, channel_id: int) -> None:
        with self.rewards._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bulletin_articles (fingerprint, title, url, source, channel_id, posted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (article.fingerprint, article.title, article.url, article.source, channel_id, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def latest(self, limit: int = 5) -> list[dict[str, Any]]:
        with self.rewards._get_connection() as conn:
            rows = conn.execute(
                "SELECT title, url, source, channel_id, posted_at FROM bulletin_articles ORDER BY posted_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def status(self) -> Optional[dict[str, Any]]:
        with self.rewards._get_connection() as conn:
            row = conn.execute("SELECT * FROM bulletin_runs ORDER BY completed_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
