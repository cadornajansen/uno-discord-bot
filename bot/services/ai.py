import logging
import time
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Default timeout in seconds for local inference.
# 90 seconds allows sufficient margin for CPU/GPU local model generation
# while preventing infinite hangs if the process stalls.
OLLAMA_TIMEOUT_SECONDS = 90.0

DEFAULT_SYSTEM_PROMPT = (
    "You are Uno, an assistant for a Computer Science college block.\n\n"
    "Answer clearly and concisely.\n\n"
    "For programming and computer science questions, prioritize correctness and practical explanations.\n\n"
    "Do not pretend to know class-specific information unless it is explicitly provided to you."
)


class AIError(Exception):
    """Base exception for AI service operations."""

    pass


class OllamaConnectionError(AIError):
    """Raised when unable to connect to the local Ollama service."""

    pass


class OllamaModelNotFoundError(AIError):
    """Raised when the configured model is not found or not pulled in Ollama."""

    pass


class OllamaTimeoutError(AIError):
    """Raised when local AI generation exceeds the configured timeout."""

    pass


class OllamaAPIError(AIError):
    """Raised when Ollama returns an unexpected HTTP error status or payload."""

    pass


class AIService:
    """Service handling direct HTTP communication with local Ollama instance."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "phi4-mini"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def ask(
        self,
        question: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Send a prompt to the local Ollama chat API and return the response.

        Args:
            question: The user prompt or question text.
            system_prompt: Optional system prompt override.

        Returns:
            The generated response string from Ollama.

        Raises:
            OllamaConnectionError: If Ollama HTTP connection fails.
            OllamaModelNotFoundError: If the specified model is not available.
            OllamaTimeoutError: If generation times out.
            OllamaAPIError: If an invalid payload or non-200 HTTP code is returned.
        """
        endpoint = f"{self.base_url}/api/chat"
        sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": question},
            ],
            "stream": False,
        }

        logger.info(f"AI request started with model '{self.model}'")
        start_time = time.perf_counter()

        timeout = httpx.Timeout(OLLAMA_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload)

                duration = time.perf_counter() - start_time

                if response.status_code == 404:
                    logger.error(
                        f"Ollama model '{self.model}' not found (HTTP 404). Run 'ollama pull {self.model}'."
                    )
                    raise OllamaModelNotFoundError(
                        f"The configured AI model '{self.model}' is not available."
                    )

                response.raise_for_status()

                data = response.json()
                content = data.get("message", {}).get("content")

                if not isinstance(content, str):
                    logger.error(f"Unexpected response payload structure from Ollama: {data}")
                    raise OllamaAPIError("Received an invalid response structure from Ollama.")

                logger.info(f"AI request completed in {duration:.2f}s")
                return content.strip()

        except httpx.ConnectError as e:
            logger.error(f"Ollama connection failure at '{self.base_url}': {e}")
            raise OllamaConnectionError(
                f"Cannot connect to Ollama service at {self.base_url}."
            ) from e

        except httpx.TimeoutException as e:
            duration = time.perf_counter() - start_time
            logger.error(f"Ollama request timed out after {duration:.2f}s")
            raise OllamaTimeoutError(
                f"AI request timed out after {OLLAMA_TIMEOUT_SECONDS} seconds."
            ) from e

        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama returned HTTP error status {e.response.status_code}")
            raise OllamaAPIError(
                f"Ollama API error (HTTP status {e.response.status_code})."
            ) from e

        except (KeyError, ValueError) as e:
            logger.error(f"Failed to parse Ollama JSON response: {e}")
            raise OllamaAPIError("Failed to parse response payload from Ollama.") from e
