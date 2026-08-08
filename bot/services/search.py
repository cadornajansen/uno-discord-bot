from dataclasses import dataclass
import logging
import time
from typing import Any
import httpx

logger = logging.getLogger(__name__)

# Maximum query length in characters
MAX_QUERY_LENGTH = 300
SERPER_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class SearchResult:
    """Represents a single organic search result from Serper."""

    title: str
    url: str
    snippet: str


class SearchError(Exception):
    """Base exception for search service operations."""

    pass


class SearchConfigError(SearchError):
    """Raised when Serper API key is missing or invalid."""

    pass


class SerperAPIError(SearchError):
    """Raised when Serper returns an HTTP status error or unexpected payload structure."""

    pass


class SearchConnectionError(SearchError):
    """Raised when unable to connect to the Serper API endpoint."""

    pass


class SearchTimeoutError(SearchError):
    """Raised when search request exceeds timeout limit."""

    pass


class SearchService:
    """Service executing Google organic search queries via the Serper REST API."""

    def __init__(self, api_key: str = "", base_url: str = "https://google.serper.dev"):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Perform a web search query via Serper API and return organic results.

        Args:
            query: User search query text.
            limit: Maximum number of organic search results to return.

        Returns:
            List of SearchResult objects containing title, url, and snippet.

        Raises:
            SearchConfigError: If API key is missing.
            SearchError: If input query is empty or too long.
            SerperAPIError: If HTTP error status (401, 403, 429, 500) is returned.
            SearchConnectionError: If network connection fails.
            SearchTimeoutError: If request times out.
        """
        if not self.api_key:
            logger.error("Serper API key is not configured.")
            raise SearchConfigError(
                "Serper API key is missing. Please set SERPER_API_KEY in configuration."
            )

        cleaned_query = query.strip()
        if not cleaned_query:
            raise SearchError("Search query cannot be empty or contain only whitespace.")

        if len(cleaned_query) > MAX_QUERY_LENGTH:
            raise SearchError(
                f"Search query is too long (maximum {MAX_QUERY_LENGTH} characters)."
            )

        endpoint = f"{self.base_url}/search"
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {"q": cleaned_query}

        logger.info(
            f"Executing Serper search (query length: {len(cleaned_query)}, limit: {limit})"
        )
        start_time = time.perf_counter()
        timeout = httpx.Timeout(SERPER_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                duration = time.perf_counter() - start_time

                if response.status_code in (401, 403):
                    logger.error(
                        "Serper API authentication failed (HTTP 401/403). Verify SERPER_API_KEY."
                    )
                    raise SerperAPIError(
                        "Serper API authentication failed. Please check the configured API key."
                    )

                if response.status_code == 429:
                    logger.error("Serper API rate limit exceeded (HTTP 429).")
                    raise SerperAPIError(
                        "Serper API rate limit exceeded. Please try again later."
                    )

                response.raise_for_status()

                data = response.json()
                organic = data.get("organic", [])
                if not isinstance(organic, list):
                    logger.error("Unexpected response structure from Serper: 'organic' is not a list")
                    return []

                results = []
                for item in organic[:limit]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title", "").strip() or "Untitled Result"
                    url = item.get("link", "").strip()
                    snippet = item.get("snippet", "").strip()

                    if url:
                        results.append(SearchResult(title=title, url=url, snippet=snippet))

                logger.info(
                    f"Serper search completed in {duration:.2f}s, returned {len(results)} organic result(s)"
                )
                return results

        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to Serper API: {e}")
            raise SearchConnectionError("Cannot connect to the search service.") from e

        except httpx.TimeoutException as e:
            duration = time.perf_counter() - start_time
            logger.error(f"Serper search request timed out after {duration:.2f}s")
            raise SearchTimeoutError(
                f"Search request timed out after {SERPER_TIMEOUT_SECONDS} seconds."
            ) from e

        except httpx.HTTPStatusError as e:
            logger.error(f"Serper API returned HTTP status error {e.response.status_code}")
            raise SerperAPIError(
                f"Search API error (HTTP status {e.response.status_code})."
            ) from e

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Failed to parse Serper JSON payload: {e}")
            raise SerperAPIError("Failed to parse response payload from search service.") from e
