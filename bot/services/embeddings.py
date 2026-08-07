import logging
import time
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Timeout in seconds for embedding generation
EMBEDDING_TIMEOUT_SECONDS = 30.0


class EmbeddingError(Exception):
    """Base exception for embedding service operations."""

    pass


class OllamaEmbeddingConnectionError(EmbeddingError):
    """Raised when unable to connect to Ollama for embedding generation."""

    pass


class OllamaEmbeddingModelNotFoundError(EmbeddingError):
    """Raised when the specified embedding model is missing from Ollama."""

    pass


class OllamaEmbeddingTimeoutError(EmbeddingError):
    """Raised when embedding generation times out."""

    pass


class EmbeddingService:
    """Service to generate dense vector embeddings using Ollama's /api/embed endpoint."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "embeddinggemma",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def embed(self, text: str) -> list[float]:
        """Generate a dense embedding vector for the provided text.

        Args:
            text: The text content to embed.

        Returns:
            A list of float values representing the embedding vector.

        Raises:
            EmbeddingError: If Ollama returns invalid payload or error.
            OllamaEmbeddingConnectionError: If network connection fails.
            OllamaEmbeddingModelNotFoundError: If model is not pulled in Ollama.
            OllamaEmbeddingTimeoutError: If request times out.
        """
        if not text or not text.strip():
            raise EmbeddingError("Cannot generate embedding for empty text.")

        endpoint = f"{self.base_url}/api/embed"
        payload = {
            "model": self.model,
            "input": text.strip(),
            "truncate": True,
        }

        start_time = time.perf_counter()
        timeout = httpx.Timeout(EMBEDDING_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload)
                duration = time.perf_counter() - start_time

                if response.status_code == 404:
                    logger.error(
                        f"Embedding model '{self.model}' not found (HTTP 404). "
                        f"Run 'ollama pull {self.model}'."
                    )
                    raise OllamaEmbeddingModelNotFoundError(
                        f"The configured embedding model '{self.model}' is not available."
                    )

                response.raise_for_status()

                data = response.json()

                # Ollama /api/embed returns "embeddings": [[float, ...]]
                embeddings = data.get("embeddings")
                if isinstance(embeddings, list) and len(embeddings) > 0 and isinstance(embeddings[0], list):
                    vector = embeddings[0]
                elif isinstance(data.get("embedding"), list):
                    vector = data["embedding"]
                else:
                    logger.error(f"Unexpected response structure from /api/embed: {data}")
                    raise EmbeddingError("Received invalid embedding payload structure from Ollama.")

                logger.debug(
                    f"Generated {len(vector)}-dim embedding with model '{self.model}' in {duration:.3f}s"
                )
                return vector

        except httpx.ConnectError as e:
            logger.error(f"Ollama connection error during embedding generation at '{self.base_url}': {e}")
            raise OllamaEmbeddingConnectionError(
                f"Cannot connect to Ollama service at {self.base_url}."
            ) from e

        except httpx.TimeoutException as e:
            duration = time.perf_counter() - start_time
            logger.error(f"Embedding request timed out after {duration:.2f}s")
            raise OllamaEmbeddingTimeoutError(
                f"Embedding generation timed out after {EMBEDDING_TIMEOUT_SECONDS}s."
            ) from e

        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama embedding API returned HTTP error status {e.response.status_code}")
            raise EmbeddingError(
                f"Ollama embedding API error (HTTP status {e.response.status_code})."
            ) from e

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to parse embedding response JSON: {e}")
            raise EmbeddingError("Failed to parse embedding response from Ollama.") from e
