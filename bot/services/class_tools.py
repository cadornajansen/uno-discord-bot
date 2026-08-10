import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bot.services.academic_schedule import (
    AcademicScheduleService,
    ScheduleError,
    VALID_DAYS,
    format_12h_time,
)
from bot.services.embeddings import EmbeddingError, EmbeddingService
from bot.services.rag import format_structured_homework_message, is_homework_context_result
from bot.services.vector_store import VectorStore, VectorStoreError

logger = logging.getLogger(__name__)

CLASS_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_latest_assignments",
            "description": "Get the latest authoritative homework and announcement posts for the class.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_class_messages",
            "description": "Search indexed class announcements and homework messages for class-specific facts.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_class_schedule",
            "description": "Get the class schedule for today, tomorrow, a weekday, or the full week.",
            "parameters": {"type": "object", "properties": {"when": {"type": "string"}}, "required": ["when"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_subject",
            "description": "Resolve a subject name, code, or abbreviation and return trusted metadata.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_professor",
            "description": "Find the professor or instructor for a subject.",
            "parameters": {"type": "object", "properties": {"subject": {"type": "string"}}, "required": ["subject"]},
        },
    },
]


class ClassTools:
    """Read-only tools over trusted academic data and indexed class messages."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        schedule_service: AcademicScheduleService,
        assignment_channel_ids: frozenset[int],
        homework_channel_ids: frozenset[int],
        top_k: int = 5,
        min_score: float = 0.5,
        timezone_name: str = "Asia/Manila",
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.schedule_service = schedule_service
        self.assignment_channel_ids = assignment_channel_ids
        self.homework_channel_ids = homework_channel_ids
        self.top_k = top_k
        self.min_score = min_score
        self.timezone = ZoneInfo(timezone_name)

    async def execute(self, name: str, arguments: dict[str, Any], guild_id: int) -> dict[str, Any]:
        handlers = {
            "get_latest_assignments": self._latest_assignments,
            "search_class_messages": self._search_messages,
            "get_class_schedule": self._schedule,
            "find_subject": self._subject,
            "get_professor": self._professor,
        }
        handler = handlers.get(name)
        if handler is None:
            return {"ok": False, "error": "Unknown tool."}
        try:
            return await handler(arguments, guild_id)
        except ScheduleError as error:
            logger.warning("Trusted academic tool failed (tool=%s): %s", name, error)
            return {"ok": False, "error": "Academic data is unavailable."}

    async def _latest_assignments(self, arguments: dict[str, Any], guild_id: int) -> dict[str, Any]:
        if not self.assignment_channel_ids:
            return {"ok": False, "error": "Assignment channels are not configured.", **self._date_context()}
        try:
            results = await self.vector_store.list_recent_messages(
                guild_id=guild_id,
                channel_ids=self.assignment_channel_ids,
                limit=max(self.top_k * 5, 20),
            )
        except VectorStoreError:
            logger.warning("Latest assignment lookup unavailable", exc_info=True)
            return {"ok": False, "error": "Indexed assignments are temporarily unavailable.", **self._date_context()}

        ranked = self._rank(results, semantic=False)
        return {"ok": True, "items": self._safe_items(ranked[: self.top_k]), **self._date_context()}

    async def _search_messages(self, arguments: dict[str, Any], guild_id: int) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"ok": False, "error": "A search query is required.", **self._date_context()}
        try:
            vector = await self.embedding_service.embed(query)
            results = await self.vector_store.search_similar(
                vector,
                limit=max(self.top_k * 4, 20),
                guild_id=guild_id,
                channel_ids=self.assignment_channel_ids or None,
            )
        except (EmbeddingError, VectorStoreError):
            logger.warning("Semantic class-message search unavailable", exc_info=True)
            return {"ok": False, "error": "Semantic class-message search is temporarily unavailable.", **self._date_context()}

        passing = [item for item in results if float(item.get("score", 0.0)) >= self.min_score]
        ranked = self._rank(passing, semantic=True)
        return {"ok": True, "items": self._safe_items(ranked[: self.top_k]), **self._date_context()}

    async def _schedule(self, arguments: dict[str, Any], guild_id: int) -> dict[str, Any]:
        when = str(arguments.get("when", "today"))
        target = self._resolve_date(when)
        weekly = self.schedule_service.get_week()
        meetings = weekly[VALID_DAYS[target.weekday()]]
        return {
            "ok": True,
            "requested_date": target.date().isoformat(),
            "day": VALID_DAYS[target.weekday()],
            "classes": [self._subject_payload(subject, meeting) for subject, meeting in meetings],
            **self._date_context(),
        }

    async def _subject(self, arguments: dict[str, Any], guild_id: int) -> dict[str, Any]:
        subjects = self.schedule_service.find_subjects(str(arguments.get("query", "")))
        return {"ok": True, "subjects": [self._subject_payload(subject) for subject in subjects[:5]], **self._date_context()}

    async def _professor(self, arguments: dict[str, Any], guild_id: int) -> dict[str, Any]:
        subjects = self.schedule_service.find_subjects(str(arguments.get("subject", "")))
        return {
            "ok": True,
            "matches": [{"code": subject.code, "name": subject.name, "professor": subject.professor} for subject in subjects[:5]],
            **self._date_context(),
        }

    def _rank(self, results: list[dict[str, Any]], semantic: bool) -> list[dict[str, Any]]:
        now = datetime.now(self.timezone)

        def priority(item: dict[str, Any]) -> float:
            payload = item.get("payload", {})
            content = str(payload.get("content", ""))
            channel_id = _as_int(payload.get("channel_id"))
            score = float(item.get("score", 0.0)) if semantic else 0.0
            created = _parse_datetime(payload.get("created_at"), self.timezone)
            age_days = max(0.0, (now - created).total_seconds() / 86400) if created else 365.0
            freshness = max(0.0, 0.35 - min(age_days, 30.0) * (0.35 / 30.0))
            authority = 0.25 if channel_id in self.assignment_channel_ids else 0.0
            if channel_id in self.homework_channel_ids:
                authority += 0.15
            if format_structured_homework_message(content, self.schedule_service):
                authority += 0.25
            elif is_homework_context_result(item):
                authority += 0.10
            casual_penalty = 0.20 if len(content) < 35 and not is_homework_context_result(item) else 0.0
            return score + freshness + authority - casual_penalty

        return sorted(results, key=priority, reverse=True)

    def _safe_items(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items = []
        for result in results:
            payload = result.get("payload", {})
            content = str(payload.get("content", "")).strip()
            if not content:
                continue
            structured = format_structured_homework_message(content, self.schedule_service)
            items.append(
                {
                    "content": structured or content,
                    "channel_kind": "homework" if _as_int(payload.get("channel_id")) in self.homework_channel_ids else "announcement",
                    "created_at": str(payload.get("created_at", "unknown")),
                }
            )
        return items

    def _date_context(self) -> dict[str, Any]:
        now = datetime.now(self.timezone)
        weekdays = {
            day.casefold(): (now + timedelta(days=(index - now.weekday()) % 7)).date().isoformat()
            for index, day in enumerate(VALID_DAYS)
        }
        return {
            "timezone": "Asia/Manila",
            "current_datetime": now.isoformat(timespec="minutes"),
            "relative_dates": {
                "today": now.date().isoformat(),
                "tomorrow": (now + timedelta(days=1)).date().isoformat(),
                **weekdays,
            },
        }

    def _resolve_date(self, text: str) -> datetime:
        now = datetime.now(self.timezone)
        normalized = text.casefold()
        if "tomorrow" in normalized:
            return now + timedelta(days=1)
        if "today" in normalized:
            return now
        for index, day in enumerate(VALID_DAYS):
            if re.search(rf"\b{day.casefold()}\b", normalized):
                offset = (index - now.weekday()) % 7
                return now + timedelta(days=offset)
        return now

    @staticmethod
    def _subject_payload(subject: Any, meeting: Any | None = None) -> dict[str, Any]:
        payload = {
            "code": subject.code,
            "name": subject.name,
            "professor": subject.professor,
            "class_type": subject.class_type,
            "aliases": list(subject.aliases),
        }
        if meeting is not None:
            payload["time"] = f"{format_12h_time(meeting.start)}-{format_12h_time(meeting.end)}"
            payload["location"] = meeting.location
        return payload


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed.astimezone(timezone)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
