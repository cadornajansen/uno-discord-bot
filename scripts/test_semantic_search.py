"""Developer CLI script to verify semantic search retrieval from Qdrant vector store.

Usage:
    python scripts/test_semantic_search.py "<search query>"

Example:
    python scripts/test_semantic_search.py "When is the data structures quiz?"
"""

import asyncio
import sys

from config.settings import load_settings, ConfigError
from bot.services.embeddings import EmbeddingService, EmbeddingError
from bot.services.vector_store import VectorStore, VectorStoreError


async def run_search(query_text: str) -> int:
    """Execute semantic search against Qdrant and display ranked results.

    Args:
        query_text: The user query string to embed and search.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"Configuration Error: {e}", file=sys.stderr)
        return 1

    embedding_service = EmbeddingService(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
    )
    vector_store = VectorStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
    )

    try:
        print(f"\nQuery: {query_text}\n")

        # 1. Generate query embedding using configured Ollama embedding model
        query_vector = await embedding_service.embed(query_text)

        # 2. Search nearest points in Qdrant collection
        results = await vector_store.search_similar(query_vector, limit=5)

        if not results:
            print("No matching messages found in Qdrant collection.")
            return 0

        # 3. Print ranked results
        for idx, item in enumerate(results, start=1):
            score = item.get("score", 0.0)
            payload = item.get("payload", {})

            content = payload.get("content", "<no content>")
            guild_id = payload.get("guild_id", "<unknown>")
            channel_id = payload.get("channel_id", "<unknown>")
            message_id = payload.get("message_id", "<unknown>")
            created_at = payload.get("created_at", "<unknown>")

            print(f"{idx}. score={score:.2f}")
            print(f"   {content}")
            print(f"   guild_id={guild_id}")
            print(f"   channel_id={channel_id}")
            print(f"   message_id={message_id}")
            print(f"   created_at={created_at}\n")

        return 0

    except EmbeddingError as e:
        print(f"Embedding Service Error: {e}", file=sys.stderr)
        return 1
    except VectorStoreError as e:
        print(f"Vector Store Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected Error: {e}", file=sys.stderr)
        return 1
    finally:
        await vector_store.close()


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage error: Missing required search query text argument.", file=sys.stderr)
        print("Usage: python scripts/test_semantic_search.py \"<search query>\"", file=sys.stderr)
        print("Example: python scripts/test_semantic_search.py \"When is the data structures quiz?\"", file=sys.stderr)
        sys.exit(1)

    query_text = sys.argv[1].strip()
    exit_code = asyncio.run(run_search(query_text))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
