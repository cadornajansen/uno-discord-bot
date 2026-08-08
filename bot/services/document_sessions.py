from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default maximum number of active document sessions stored in memory
MAX_ACTIVE_SESSIONS = 50


@dataclass
class DocumentSession:
    """Represents a temporary, in-memory active document session for a user."""

    filename: str
    markdown: str
    warnings: tuple[str, ...]
    created_at: datetime


class DocumentSessionService:
    """In-memory service managing temporary active document sessions for /docask."""

    def __init__(self, ttl_minutes: int = 30, max_sessions: int = MAX_ACTIVE_SESSIONS):
        self.ttl_minutes = ttl_minutes
        self.max_sessions = max_sessions
        # Storage key: (guild_id, channel_id, user_id) -> DocumentSession
        self._sessions: dict[tuple[int, int, int], DocumentSession] = {}

    def _make_key(self, guild_id: Optional[int], channel_id: int, user_id: int) -> tuple[int, int, int]:
        gid = guild_id if guild_id is not None else 0
        return (gid, channel_id, user_id)

    def set_session(
        self,
        guild_id: Optional[int],
        channel_id: int,
        user_id: int,
        filename: str,
        markdown: str,
        warnings: tuple[str, ...],
    ) -> DocumentSession:
        """Store or replace an active document session for a user in a channel.

        Args:
            guild_id: Discord guild ID or None.
            channel_id: Discord channel ID.
            user_id: Discord user ID.
            filename: Document filename.
            markdown: Extracted/truncated Markdown text.
            warnings: Warning messages tuple.

        Returns:
            The created DocumentSession object.
        """
        key = self._make_key(guild_id, channel_id, user_id)

        # Enforce capacity limit by removing oldest session if capacity reached
        if len(self._sessions) >= self.max_sessions and key not in self._sessions:
            oldest_key = min(self._sessions.keys(), key=lambda k: self._sessions[k].created_at)
            del self._sessions[oldest_key]
            logger.info(f"DocumentSessionService capacity limit reached. Purged oldest session key {oldest_key}")

        session = DocumentSession(
            filename=filename,
            markdown=markdown,
            warnings=warnings,
            created_at=datetime.now(timezone.utc),
        )
        self._sessions[key] = session
        logger.info(
            f"Stored document session for key {key} (filename: '{filename}', length: {len(markdown)} chars)"
        )
        return session

    def get_session(
        self,
        guild_id: Optional[int],
        channel_id: int,
        user_id: int,
    ) -> tuple[Optional[DocumentSession], bool]:
        """Retrieve an active session for a user in a channel, applying lazy TTL expiration.

        Args:
            guild_id: Discord guild ID or None.
            channel_id: Discord channel ID.
            user_id: Discord user ID.

        Returns:
            Tuple of (DocumentSession or None, was_expired: bool)
        """
        key = self._make_key(guild_id, channel_id, user_id)
        session = self._sessions.get(key)

        if session is None:
            return (None, False)

        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - session.created_at).total_seconds()

        if elapsed_seconds > (self.ttl_minutes * 60):
            logger.info(
                f"Document session for key {key} expired after {elapsed_seconds:.1f}s. Removing."
            )
            del self._sessions[key]
            return (None, True)

        return (session, False)

    def clear_session(self, guild_id: Optional[int], channel_id: int, user_id: int) -> None:
        """Explicitly clear an active session."""
        key = self._make_key(guild_id, channel_id, user_id)
        if key in self._sessions:
            del self._sessions[key]

    def clear_all(self) -> None:
        """Clear all active sessions in memory."""
        self._sessions.clear()
