from datetime import datetime
import re
from typing import Optional
import discord


MAX_DISCORD_CHUNK_CHARS = 1900
ASSIGNMENT_HEADING = re.compile(r"^\*\*(.+?)\s+—\s+(.+?)\*\*$")
MAX_EMBED_FIELD_CHARS = 1024
MAX_FIELDS_PER_ASSIGNMENT_EMBED = 8


def format_latency(latency_seconds: float) -> str:
    """Format bot WebSocket latency in milliseconds.

    Args:
        latency_seconds: Latency in seconds (e.g. from bot.latency).

    Returns:
        Formatted string like "42ms".
    """
    ms = round(latency_seconds * 1000)
    return f"{ms}ms"


def format_timestamp(dt: Optional[datetime], style: str = "F") -> str:
    """Format a datetime into Discord Markdown timestamp syntax.

    Args:
        dt: Datetime object to format.
        style: Discord timestamp style flag (e.g., 'F' for long date/time, 'R' for relative).

    Returns:
        Formatted Discord timestamp tag string, or 'Unknown' if dt is None.
    """
    if dt is None:
        return "Unknown"
    unix_timestamp = int(dt.timestamp())
    return f"<t:{unix_timestamp}:{style}>"


def _find_split_position(text: str, limit: int) -> int:
    """Find the best content-preserving split position within ``limit``."""
    for separator in ("\n\n", "\n", ". "):
        index = text.rfind(separator, 0, limit + 1)
        if index >= 0:
            return index + len(separator)

    for index in range(limit - 1, -1, -1):
        if text[index].isspace():
            return index + 1

    return limit


def _split_text_at_boundaries(text: str, limit: int) -> list[str]:
    """Split text while retaining every original separator character."""
    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        split_position = _find_split_position(remaining, limit)
        nearby_fence = remaining.find(
            "```",
            max(0, split_position - 2),
            min(len(remaining), split_position + 2),
        )
        if nearby_fence >= 0 and nearby_fence < split_position < nearby_fence + 3:
            split_position = nearby_fence if nearby_fence > 0 else 3
        chunks.append(remaining[:split_position])
        remaining = remaining[split_position:]

    if remaining:
        chunks.append(remaining)

    return chunks


def split_message(
    text: str,
    limit: int = MAX_DISCORD_CHUNK_CHARS,
) -> list[str]:
    """Split text into Discord-safe chunks at readable boundaries.

    Split priority is paragraph, newline, sentence, whitespace, then a hard
    character boundary. Markdown code blocks are closed and reopened across
    chunk boundaries so each Discord message renders independently.

    Args:
        text: The string content to split.
        limit: Maximum character length per chunk (default: 1900).

    Returns:
        A list of non-empty string chunks.
    """
    if not text:
        return []

    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    if len(text) <= limit:
        return [text]

    has_code_fence = "```" in text
    fence_overhead = 8 if has_code_fence else 0
    content_limit = max(1, limit - fence_overhead)
    raw_chunks = _split_text_at_boundaries(text, content_limit)

    if not has_code_fence:
        return raw_chunks

    chunks: list[str] = []
    code_fence_open = False
    for raw_chunk in raw_chunks:
        prefix = "```\n" if code_fence_open else ""
        code_fence_open = code_fence_open != (raw_chunk.count("```") % 2 == 1)
        suffix = "\n```" if code_fence_open else ""
        chunks.append(f"{prefix}{raw_chunk}{suffix}")

    return chunks


class PaginatedTextView(discord.ui.View):
    """Navigate a long response without creating multiple channel messages."""

    def __init__(
        self,
        pages: list[str],
        owner_id: int,
        timeout: float = 300.0,
    ) -> None:
        if len(pages) < 2:
            raise ValueError("PaginatedTextView requires at least two pages")

        super().__init__(timeout=timeout)
        self.pages = tuple(pages)
        self.owner_id = owner_id
        self.current_page = 0
        self.message: discord.InteractionMessage | None = None
        self._update_button_states()

    @property
    def content(self) -> str:
        """Return the current page with a compact position indicator."""
        return (
            f"{self.pages[self.current_page].rstrip()}\n\n"
            f"*Page {self.current_page + 1} of {len(self.pages)}*"
        )

    def _update_button_states(self) -> None:
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.pages) - 1
        self.next_button.label = (
            "Next - Read More" if self.current_page == 0 else "Next"
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the user who requested the response to change pages."""
        if interaction.user.id == self.owner_id:
            return True

        await interaction.response.send_message(
            "Only the person who requested this response can change its page.",
            ephemeral=True,
        )
        return False

    async def _show_page(self, interaction: discord.Interaction) -> None:
        self._update_button_states()
        await interaction.response.edit_message(content=self.content, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.current_page = max(0, self.current_page - 1)
        await self._show_page(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        await self._show_page(interaction)

    async def on_timeout(self) -> None:
        """Disable expired controls so their inactive state is clear."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        if self.message is None:
            return

        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


async def send_deferred_response(
    interaction: "discord.Interaction",
    content: str,
    limit: int = MAX_DISCORD_CHUNK_CHARS,
) -> None:
    """Send text content in response to a deferred slash command interaction.

    Edits the original deferred response message to preserve the 'user used
    /command' invocation header. Long responses stay in that single message and
    receive Previous and Next controls instead of creating followup messages.

    Args:
        interaction: Discord interaction object.
        content: String content to send.
        limit: Maximum character length per chunk (default: 1900).
    """
    safe_limit = min(limit, MAX_DISCORD_CHUNK_CHARS)
    chunks = split_message(content, limit=safe_limit)
    if not chunks:
        await interaction.edit_original_response(content="No response generated.")
        return

    await send_deferred_pages(interaction, chunks)


async def send_deferred_pages(
    interaction: "discord.Interaction",
    pages: list[str],
) -> None:
    """Display pre-built text pages in one deferred interaction response."""
    non_empty_pages = [page for page in pages if page]
    if not non_empty_pages:
        await interaction.edit_original_response(content="No response generated.")
        return

    if len(non_empty_pages) == 1:
        await interaction.edit_original_response(content=non_empty_pages[0])
        return

    view = PaginatedTextView(non_empty_pages, owner_id=interaction.user.id)
    view.message = await interaction.edit_original_response(
        content=view.content,
        view=view,
    )


def build_assignment_embeds(
    items: tuple[dict[str, object], ...] | list[dict[str, object]],
    current_datetime: str | None = None,
) -> list[discord.Embed]:
    """Turn a trusted structured homework summary into scan-friendly embeds."""
    sections: list[tuple[str, str]] = []
    for item in items:
        sections.extend(_parse_assignment_sections(str(item.get("content", ""))))

    if not sections:
        return []

    pages = [
        sections[index : index + MAX_FIELDS_PER_ASSIGNMENT_EMBED]
        for index in range(0, len(sections), MAX_FIELDS_PER_ASSIGNMENT_EMBED)
    ]
    embeds: list[discord.Embed] = []
    for page_number, page in enumerate(pages, start=1):
        title = "Latest Assignments"
        if len(pages) > 1:
            title += f" · {page_number}/{len(pages)}"
        embed = discord.Embed(
            title=title,
            description="Organized by subject from the latest approved homework post.",
            color=discord.Color.blurple(),
        )
        for heading, details in page:
            embed.add_field(
                name=heading[:256],
                value=_truncate_embed_field(details),
                inline=False,
            )
        embed.set_footer(text=_assignment_footer(current_datetime))
        embeds.append(embed)
    return embeds


async def send_deferred_chat_response(
    interaction: "discord.Interaction",
    content: str,
    assignment_items: tuple[dict[str, object], ...] = (),
    current_datetime: str | None = None,
) -> None:
    """Send either assignment embeds or the normal chunked text response."""
    embeds = build_assignment_embeds(assignment_items, current_datetime)
    if not embeds:
        await send_deferred_response(interaction, content)
        return

    await interaction.edit_original_response(content=None, embed=embeds[0])
    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed)


def _parse_assignment_sections(content: str) -> list[tuple[str, str]]:
    """Parse the normalized homework Markdown emitted by the RAG formatter."""
    sections: list[tuple[str, str]] = []
    heading: str | None = None
    details: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        match = ASSIGNMENT_HEADING.match(line)
        if match and line != "**Latest Homework & Requirements**":
            if heading and details:
                sections.append((heading, "\n".join(details)))
            heading = f"{match.group(1)} — {match.group(2)}"
            details = []
        elif heading and line:
            details.append(f"• {line[2:]}" if line.startswith("- ") else line)

    if heading and details:
        sections.append((heading, "\n".join(details)))
    return sections


def _truncate_embed_field(value: str) -> str:
    """Keep a field within Discord's limit without cutting a word abruptly."""
    if len(value) <= MAX_EMBED_FIELD_CHARS:
        return value
    cutoff = value.rfind("\n", 0, MAX_EMBED_FIELD_CHARS - 1)
    if cutoff < 1:
        cutoff = MAX_EMBED_FIELD_CHARS - 1
    return value[:cutoff].rstrip() + "…"


def _assignment_footer(current_datetime: str | None) -> str:
    if current_datetime:
        try:
            checked_at = datetime.fromisoformat(current_datetime)
            return f"Checked {checked_at.strftime('%b %d, %Y at %I:%M %p')} · Asia/Manila"
        except ValueError:
            pass
    return "Latest approved homework post · Asia/Manila"
