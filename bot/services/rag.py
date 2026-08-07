import logging
import time
from typing import Any, Optional

from bot.services.ai import AIService, AIError
from bot.services.embeddings import EmbeddingService, EmbeddingError
from bot.services.vector_store import VectorStore, VectorStoreError

logger = logging.getLogger(__name__)


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


def format_sources_section(results: list[dict[str, Any]]) -> str:
    """Format lightweight source citation list from retrieved results payload metadata.

    Args:
        results: List of result dicts containing 'payload'.

    Returns:
        Formatted source citation string.
    """
    sources = []
    seen = set()

    for item in results:
        payload = item.get("payload", {})
        channel_id = payload.get("channel_id")
        message_id = payload.get("message_id")

        if channel_id and message_id:
            key = (channel_id, message_id)
            if key not in seen:
                seen.add(key)
                sources.append(f"- Channel ID {channel_id} — message {message_id}")

    if not sources:
        return ""

    return "Sources:\n" + "\n".join(sources)


class RAGService:
    """Orchestrates retrieval-augmented generation for Discord /ask command."""

    def __init__(
        self,
        ai_service: Optional[AIService] = None,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStore] = None,
        top_k: int = 5,
        min_score: float = 0.30,
    ):
        self.ai_service = ai_service or AIService()
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or VectorStore()
        self.top_k = top_k
        self.min_score = min_score

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
            Grounded LLM response string, with optional lightweight sources if context was used.

        Raises:
            AIError: If LLM chat generation fails.
        """
        logger.info(f"RAG request started for Guild ID {guild_id}")
        start_time = time.perf_counter()

        query_vector: Optional[list[float]] = None
        raw_results: list[dict[str, Any]] = []

        # 1. Attempt query embedding generation
        try:
            query_vector = await self.embedding_service.embed(question)
        except EmbeddingError as e:
            logger.warning(f"RAG fallback: Embedding generation failed for question: {e}")

        # 2. Attempt vector retrieval if embedding succeeded
        if query_vector is not None:
            try:
                raw_results = await self.vector_store.search_similar(
                    query_vector,
                    limit=self.top_k,
                    guild_id=guild_id,
                )
                logger.info(
                    f"RAG search retrieved {len(raw_results)} candidate vector match(es)"
                )
            except VectorStoreError as e:
                logger.warning(f"RAG fallback: VectorStore search failed: {e}")

        # 3. Filter retrieved results by minimum similarity score threshold
        valid_results = [
            item for item in raw_results if item.get("score", 0.0) >= self.min_score
        ]

        # 4. Generate response with RAG context or plain AI fallback
        if valid_results:
            context_block = format_context_block(valid_results)
            sources_section = format_sources_section(valid_results)

            logger.info(
                f"RAG invoking AIService with {len(valid_results)} context item(s) "
                f"(top score: {valid_results[0].get('score', 0.0):.2f})"
            )

            answer_text = await self.ai_service.ask(question, context=context_block)

            if sources_section:
                answer_text = f"{answer_text}\n\n{sources_section}"

        else:
            logger.info("No valid context passed minimum score threshold. Proceeding with plain AI fallback.")
            answer_text = await self.ai_service.ask(question, context=None)

        duration = time.perf_counter() - start_time
        logger.info(f"RAG answer completed in {duration:.2f}s")
        return answer_text
