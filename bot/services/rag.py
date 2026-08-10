import logging
import re
import time
from typing import Any, Optional

from bot.services.ai import AIService, AIError, HOMEWORK_RAG_SYSTEM_PROMPT
from bot.services.academic_schedule import AcademicScheduleService, ScheduleError
from bot.services.embeddings import EmbeddingService, EmbeddingError
from bot.services.vector_store import VectorStore, VectorStoreError

logger = logging.getLogger(__name__)

HOMEWORK_QUERY_TERMS = ("homework", "assignment", "deadline", "due date")
RECENT_QUERY_TERMS = ("latest", "recent", "current", "upcoming", "pending")
HOMEWORK_MIN_SCORE = 0.35
HOMEWORK_CONTEXT_TERMS = (
    "homework",
    "assignment",
    "quiz",
    "exam",
    "project",
    "activity",
    "exercise",
    "handout",
    "presentation",
    "deadline",
    "due",
    "task",
)
HOMEWORK_DETAIL_TERMS = (
    "tomorrow",
    "next week",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "submit",
    "pass",
    "complete",
    "answer",
    "write",
    "read",
    "study",
    "translate",
    "prepare",
    "bring",
    "solve",
    "collect",
)
DATE_TERMS = (
    "due",
    "today",
    "tomorrow",
    "next week",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
)


def is_homework_query(question: str) -> bool:
    """Return whether a question explicitly asks about homework information."""
    normalized = question.casefold()
    return any(term in normalized for term in HOMEWORK_QUERY_TERMS)


def is_recent_homework_query(question: str) -> bool:
    """Return whether a homework question asks for a current assignment list."""
    normalized = question.casefold()
    if not is_homework_query(question):
        return False
    return (
        any(term in normalized for term in RECENT_QUERY_TERMS)
        or "homeworks" in normalized
        or "assignments" in normalized
        or "what are" in normalized
    )


def is_homework_context_result(result: dict[str, Any]) -> bool:
    """Keep OCR records and messages that look like actionable class work."""
    payload = result.get("payload", {})
    source_type = str(payload.get("source_type", ""))
    if "image_ocr" in source_type:
        return True

    content = str(payload.get("content", "")).casefold()
    has_homework_term = any(term in content for term in HOMEWORK_CONTEXT_TERMS)
    has_actionable_detail = (
        len(content) >= 80
        or any(term in content for term in HOMEWORK_DETAIL_TERMS)
    )
    return has_homework_term and has_actionable_detail


def format_context_block(results: list[dict[str, Any]]) -> str:
    """Format retrieved Qdrant metadata results into a compact text block for LLM prompt context.

    Args:
        results: List of result dicts containing 'score' and 'payload'.

    Returns:
        Formatted context string block.
    """
    entries = []
    for idx, item in enumerate(results, start=1):
        payload = item.get("payload", {})
        content = payload.get("content", "").strip()
        channel_id = payload.get("channel_id", "unknown")
        created_at = payload.get("created_at", "unknown")

        if content:
            entries.append(
                f"[{idx}]\n"
                f"Message: {content}\n"
                f"Channel ID: {channel_id}\n"
                f"Created at: {created_at}"
            )

    return "\n\n".join(entries)


def format_structured_homework_message(
    content: str,
    schedule_service: AcademicScheduleService,
) -> Optional[str]:
    """Format a subject-headed homework post without letting an LLM regroup tasks."""
    term = schedule_service.get_term()
    alias_lookup = {
        alias.casefold(): alias
        for subject in term.subjects
        for alias in subject.aliases
    }
    grouped_tasks: dict[str, list[str]] = {}
    current_alias: Optional[str] = None

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        heading_candidate = stripped.strip("#*_:` ").casefold()
        if heading_candidate in alias_lookup:
            current_alias = alias_lookup[heading_candidate]
            grouped_tasks.setdefault(current_alias, [])
            continue

        if current_alias is None or not re.match(r"^[-*•]\s+", stripped):
            continue

        task = re.sub(r"^[-*•]\s+", "", stripped).strip()
        if task:
            grouped_tasks[current_alias].append(task)

    populated_groups = {
        alias: tasks for alias, tasks in grouped_tasks.items() if tasks
    }
    if len(populated_groups) < 2:
        return None

    sections = ["**Latest Homework & Requirements**"]
    for alias, tasks in populated_groups.items():
        subjects = schedule_service.find_subjects(alias)
        names = list(dict.fromkeys(subject.name for subject in subjects))
        base_names = list(
            dict.fromkeys(re.sub(r" \((?:Lecture|Lab)\)$", "", name) for name in names)
        )
        professors = list(dict.fromkeys(subject.professor for subject in subjects))
        class_types = list(
            dict.fromkeys(subject.class_type for subject in subjects if subject.class_type)
        )
        locations = list(
            dict.fromkeys(
                meeting.location
                for subject in subjects
                for meeting in subject.schedules
            )
        )

        official_name = " / ".join(base_names) if base_names else alias
        sections.append(f"**{alias} — {official_name}**")
        metadata = " · ".join(
            item
            for item in (
                ", ".join(professors),
                "/".join(class_types),
                ", ".join(locations),
            )
            if item
        )
        if metadata:
            sections.append(f"*{metadata}*")

        for task in tasks:
            normalized_task = task.casefold()
            date_suffix = (
                "" if any(term in normalized_task for term in DATE_TERMS)
                else " — No due date stated"
            )
            sections.append(f"- {task}{date_suffix}")
        sections.append("")

    return "\n".join(sections).rstrip()


class RAGService:
    """Orchestrates retrieval-augmented generation for Discord /ask command."""

    def __init__(
        self,
        ai_service: Optional[AIService] = None,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStore] = None,
        top_k: int = 5,
        min_score: float = 0.50,
        max_context_results: int = 3,
        homework_channel_ids: frozenset[int] = frozenset(),
        academic_schedule_service: Optional[AcademicScheduleService] = None,
    ):
        self.ai_service = ai_service or AIService()
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or VectorStore()
        self.top_k = top_k
        self.min_score = min_score
        self.max_context_results = max_context_results
        self.homework_channel_ids = homework_channel_ids
        self.academic_schedule_service = academic_schedule_service

    async def answer(
        self,
        question: str,
        *,
        guild_id: int,
    ) -> str:
        """Process a user question with guild-isolated vector search and grounded LLM generation.

        Args:
            question: The user prompt or question text.
            guild_id: Current Discord guild ID for strict server-scoped vector filtering.

        Returns:
            Grounded LLM response string without retrieval metadata.

        Raises:
            AIError: If LLM chat generation fails.
        """
        logger.info(f"RAG request started for Guild ID {guild_id}")
        start_time = time.perf_counter()

        query_vector: Optional[list[float]] = None
        raw_results: list[dict[str, Any]] = []
        homework_query = is_homework_query(question)
        recent_homework_lookup_used = False

        # 1. Prefer recent, actionable records for explicit homework-list questions.
        if is_recent_homework_query(question) and self.homework_channel_ids:
            try:
                recent_results = await self.vector_store.list_recent_messages(
                    guild_id=guild_id,
                    channel_ids=self.homework_channel_ids,
                    limit=max(self.top_k * 4, self.max_context_results),
                )
                raw_results = [
                    result
                    for result in recent_results
                    if is_homework_context_result(result)
                ]
                recent_homework_lookup_used = bool(raw_results)
                logger.info(
                    f"RAG homework lookup: {len(recent_results)} recent records, "
                    f"{len(raw_results)} actionable"
                )
            except VectorStoreError as e:
                logger.warning(f"RAG recent-homework lookup failed: {e}")

        # 2. Use semantic retrieval for ordinary questions or as a fallback.
        if not raw_results:
            try:
                query_vector = await self.embedding_service.embed(question)
            except EmbeddingError as e:
                logger.warning(
                    f"RAG fallback: Embedding generation failed for question: {e}"
                )

        # 3. Attempt vector retrieval if embedding succeeded.
        if query_vector is not None:
            try:
                search_limit = max(self.top_k, 20) if homework_query else self.top_k
                raw_results = await self.vector_store.search_similar(
                    query_vector,
                    limit=search_limit,
                    guild_id=guild_id,
                    **(
                        {"channel_ids": self.homework_channel_ids}
                        if homework_query and self.homework_channel_ids
                        else {}
                    ),
                )
                logger.info(
                    f"RAG search retrieved {len(raw_results)} candidate vector match(es)"
                )
            except VectorStoreError as e:
                logger.warning(f"RAG fallback: VectorStore search failed: {e}")

        # 4. Filter retrieved results by minimum similarity score threshold.
        effective_min_score = (
            min(self.min_score, HOMEWORK_MIN_SCORE)
            if homework_query and self.homework_channel_ids
            else self.min_score
        )
        if homework_query and self.homework_channel_ids:
            raw_results = [
                result for result in raw_results if is_homework_context_result(result)
            ]

        passing_results = [
            item
            for item in raw_results
            if item.get("score", 0.0) >= effective_min_score
        ]
        if recent_homework_lookup_used:
            valid_results = passing_results[: self.max_context_results]
        elif homework_query and self.homework_channel_ids:
            valid_results = sorted(
                passing_results,
                key=lambda item: (
                    "image_ocr" in str(item.get("payload", {}).get("source_type", "")),
                    item.get("score", 0.0),
                ),
                reverse=True,
            )[: self.max_context_results]
        else:
            valid_results = sorted(
                passing_results,
                key=lambda item: item.get("score", 0.0),
                reverse=True,
            )[: self.max_context_results]

        logger.info(
            f"RAG retrieval: {len(raw_results)} candidates, "
            f"{len(passing_results)} above threshold {effective_min_score:.2f}; "
            f"using {len(valid_results)} -> "
            f"{'grounded response' if valid_results else 'plain AI'}"
        )

        # 5. Generate response with RAG context or plain AI fallback.
        if valid_results:
            context_block = format_context_block(valid_results)

            if (
                recent_homework_lookup_used
                and self.academic_schedule_service is not None
            ):
                for result in valid_results:
                    content = str(result.get("payload", {}).get("content", ""))
                    try:
                        structured_answer = format_structured_homework_message(
                            content,
                            self.academic_schedule_service,
                        )
                    except ScheduleError as error:
                        logger.warning(
                            f"Structured homework formatting unavailable: {error}"
                        )
                        break
                    if structured_answer:
                        duration = time.perf_counter() - start_time
                        logger.info(
                            f"RAG answer completed with deterministic homework formatting "
                            f"in {duration:.2f}s"
                        )
                        return structured_answer

            if homework_query and self.academic_schedule_service is not None:
                try:
                    subject_metadata = self.academic_schedule_service.format_metadata_for_text(
                        context_block
                    )
                except ScheduleError as error:
                    logger.warning(f"Subject metadata unavailable for homework answer: {error}")
                else:
                    if subject_metadata:
                        context_block = (
                            "Trusted subject catalog (use only for subject names and metadata):\n"
                            f"{subject_metadata}\n\n"
                            "Retrieved homework messages (use only for tasks and dates):\n"
                            f"{context_block}"
                        )

            logger.info(
                f"RAG invoking AIService with {len(valid_results)} context item(s) "
                f"(top score: {valid_results[0].get('score', 0.0):.2f})"
            )

            if homework_query:
                answer_text = await self.ai_service.ask(
                    question,
                    system_prompt=HOMEWORK_RAG_SYSTEM_PROMPT,
                    context=context_block,
                )
            else:
                answer_text = await self.ai_service.ask(
                    question,
                    context=context_block,
                )

        else:
            logger.info("No valid context passed minimum score threshold. Proceeding with plain AI fallback.")
            answer_text = await self.ai_service.ask(question, context=None)

        duration = time.perf_counter() - start_time
        logger.info(f"RAG answer completed in {duration:.2f}s")
        return answer_text
