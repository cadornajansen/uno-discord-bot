import logging
from urllib.parse import urlparse
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.search import (
    SearchService,
    SearchResult,
    SearchConfigError,
    SearchConnectionError,
    SearchTimeoutError,
    SerperAPIError,
    SearchError,
    MAX_QUERY_LENGTH,
)
from bot.utils.formatting import split_message, send_deferred_response

logger = logging.getLogger(__name__)


def extract_domain(url: str) -> str:
    """Extract a user-friendly display domain from a full URL.

    Args:
        url: Full web URL string.

    Returns:
        Hostname domain string (e.g. 'huggingface.co') or 'web'.
    """
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "web"
    except Exception:
        return "web"


def format_search_results(query: str, results: list[SearchResult]) -> str:
    """Format organic search results into clean, compact Discord Markdown.

    Args:
        query: User search query.
        results: List of SearchResult dataclass objects.

    Returns:
        Formatted markdown string block.
    """
    if not results:
        return f"No search results found for **{query}**."

    lines = [f"Search results for: **{query}**"]

    for idx, res in enumerate(results, start=1):
        domain = extract_domain(res.url)
        snippet_text = res.snippet if res.snippet else "No description available."

        entry = f"**{idx}. [{res.title}](<{res.url}>)** *{domain}*\n{snippet_text}"
        lines.append(entry)

    return "\n\n".join(lines)


class SearchCog(commands.Cog):
    """Cog for web-based academic and technical search powered by Serper API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        settings = getattr(bot, "settings", None)

        api_key = settings.serper_api_key if settings else ""
        base_url = settings.serper_base_url if settings else "https://google.serper.dev"
        self.default_limit = settings.search_result_limit if settings else 5

        self.search_service = SearchService(api_key=api_key, base_url=base_url)

    @app_commands.command(
        name="search",
        description="Search the web for academic and technical resources.",
    )
    @app_commands.describe(query="The topic or academic query to search.")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        """Slash command /search query:<text>"""
        cleaned_query = query.strip()

        # Input validation
        if not cleaned_query:
            await interaction.response.send_message(
                "Search query cannot be empty or contain only whitespace.",
                ephemeral=True,
            )
            return

        if len(cleaned_query) > MAX_QUERY_LENGTH:
            await interaction.response.send_message(
                f"Search query is too long (maximum {MAX_QUERY_LENGTH} characters).",
                ephemeral=True,
            )
            return

        # Defer interaction before executing external HTTP search request
        await interaction.response.defer()

        try:
            results = await self.search_service.search(
                cleaned_query,
                limit=self.default_limit,
            )

            formatted = format_search_results(cleaned_query, results)
            await send_deferred_response(interaction, formatted)

        except SearchConfigError:
            logger.warning(f"User {interaction.user.id} '/search' failed: API key unconfigured.")
            await interaction.edit_original_response(
                content="Web search is currently unavailable (API key not configured)."
            )

        except SearchConnectionError:
            logger.warning(f"User {interaction.user.id} '/search' failed: Connection error.")
            await interaction.edit_original_response(
                content="Unable to connect to the search service right now. Please try again later."
            )

        except SearchTimeoutError:
            logger.warning(f"User {interaction.user.id} '/search' failed: Request timeout.")
            await interaction.edit_original_response(
                content="The search request took too long to respond. Please try again later."
            )

        except SerperAPIError as e:
            logger.error(f"User {interaction.user.id} '/search' failed with API error: {e}")
            await interaction.edit_original_response(
                content="An error occurred while communicating with the search service."
            )

        except SearchError as e:
            logger.warning(f"User {interaction.user.id} '/search' failed with search error: {e}")
            await interaction.edit_original_response(
                content=f"Could not complete search: {e}"
            )

        except Exception as e:
            logger.error(
                f"Unexpected exception during '/search' execution: {e}",
                exc_info=True,
            )
            await interaction.edit_original_response(
                content="Something went wrong while running this command."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SearchCog(bot))
