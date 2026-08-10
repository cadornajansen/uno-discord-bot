import logging
import time
from typing import Literal
import httpx

logger = logging.getLogger(__name__)

# Timeout in seconds for embedding generation
EMBEDDING_TIMEOUT_SECONDS = 30.0


class EmbeddingError(Exception):
    """Base exception for embedding service operations."""

    pass


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when required Gemini embedding configuration is missing."""

    pass


class EmbeddingConnectionError(EmbeddingError):
    """Raised when unable to connect to the Gemini API."""

    pass


class EmbeddingModelNotFoundError(EmbeddingError):
    """Raised when the configured Gemini embedding model is unavailable."""


class EmbeddingTimeoutError(EmbeddingError):
    """Raised when embedding generation times out."""

    pass


class EmbeddingService:
    """Generate retrieval embeddings with Google's Gemini Embedding API."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str = "gemini-embedding-2",
        output_dimensionality: int = 768,
        timeout_seconds: float = EMBEDDING_TIMEOUT_SECONDS,
    ):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.output_dimensionality = output_dimensionality
        self.timeout_seconds = timeout_seconds

    async def embed(
        self,
        text: str,
        *,
        task_type: Literal["query", "document"] = "query",
        title: str | None = None,
    ) -> list[float]:
        """Generate a dense embedding vector for the provided text.

        Args:
            text: The text content to embed.

        Returns:
            A list of float values representing the embedding vector.

        Raises:
            EmbeddingError: If Gemini returns an invalid payload or error.
        """
        if not text or not text.strip():
            raise EmbeddingError("Cannot generate embedding for empty text.")
        if not self.api_key:
            raise EmbeddingConfigurationError("GEMINI_API_KEY is missing or empty.")

        cleaned_text = text.strip()
        if task_type == "document":
            prepared_text = f"title: {title or 'none'} | text: {cleaned_text}"
        else:
            prepared_text = f"task: question answering | query: {cleaned_text}"

        endpoint = f"{self.base_url}/models/{self.model}:embedContent"
        payload = {
            "content": {"parts": [{"text": prepared_text}]},
            "output_dimensionality": self.output_dimensionality,
        }

        start_time = time.perf_counter()
        timeout = httpx.Timeout(self.timeout_seconds)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint,
                    headers={"x-goog-api-key": self.api_key},
                    json=payload,
                )
                duration = time.perf_counter() - start_time

                if response.status_code == 404:
                    logger.error(
                        f"Gemini embedding model '{self.model}' was not found."
                    )
                    raise EmbeddingModelNotFoundError(
                        f"The configured embedding model '{self.model}' is not available."
                    )

                response.raise_for_status()

                data = response.json()

                # Gemini Embedding 2 returns embeddings with a nested values array.
                embeddings = data.get("embeddings")
                embedding = data.get("embedding")
                if (
                    isinstance(embeddings, list)
                    and embeddings
                    and isinstance(embeddings[0], dict)
                    and isinstance(embeddings[0].get("values"), list)
                ):
                    vector = embeddings[0]["values"]
                elif isinstance(embedding, dict) and isinstance(embedding.get("values"), list):
                    vector = embedding["values"]
                else:
                    logger.error("Gemini returned an invalid embedding response structure.")
                    raise EmbeddingError("Received invalid embedding payload structure from Gemini.")

                if len(vector) != self.output_dimensionality:
                    raise EmbeddingError(
                        "Gemini returned an embedding with an unexpected dimension: "
                        f"expected {self.output_dimensionality}, got {len(vector)}."
                    )

                logger.debug(
                    f"Generated {len(vector)}-dim embedding with model '{self.model}' in {duration:.3f}s"
                )
                return vector

        except httpx.ConnectError as e:
            logger.error(f"Gemini connection error during embedding generation at '{self.base_url}': {e}")
            raise EmbeddingConnectionError(
                f"Cannot connect to the Gemini API at {self.base_url}."
            ) from e

        except httpx.TimeoutException as e:
            duration = time.perf_counter() - start_time
            logger.error(f"Embedding request timed out after {duration:.2f}s")
            raise EmbeddingTimeoutError(
                f"Embedding generation timed out after {self.timeout_seconds}s."
            ) from e

        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini embedding API returned HTTP error status {e.response.status_code}")
            raise EmbeddingError(
                f"Gemini embedding API error (HTTP status {e.response.status_code})."
            ) from e

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to parse embedding response JSON: {e}")
            raise EmbeddingError("Failed to parse embedding response from Gemini.") from e
