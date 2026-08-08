from datetime import datetime, timedelta, timezone
import pytest

from bot.services.document_sessions import DocumentSessionService, DocumentSession


def test_set_and_get_session_success():
    """Test storing and retrieving an active document session."""
    service = DocumentSessionService(ttl_minutes=30)
    service.set_session(
        guild_id=100,
        channel_id=200,
        user_id=300,
        filename="lecture.pdf",
        markdown="Sample markdown",
        warnings=("Warning 1",),
    )

    session, was_expired = service.get_session(100, 200, 300)
    assert was_expired is False
    assert session is not None
    assert session.filename == "lecture.pdf"
    assert session.markdown == "Sample markdown"
    assert session.warnings == ("Warning 1",)


def test_session_key_isolation():
    """Test that sessions are isolated by (guild_id, channel_id, user_id)."""
    service = DocumentSessionService(ttl_minutes=30)
    service.set_session(100, 200, 300, "user1.pdf", "Content 1", ())

    # Same channel, different user
    session, _ = service.get_session(100, 200, 999)
    assert session is None

    # Same user, different channel
    session, _ = service.get_session(100, 888, 300)
    assert session is None

    # Same channel & user, different guild
    session, _ = service.get_session(777, 200, 300)
    assert session is None


def test_session_replacement():
    """Test that analyzing a new document replaces the user's active session."""
    service = DocumentSessionService(ttl_minutes=30)
    service.set_session(100, 200, 300, "old.pdf", "Old content", ())
    service.set_session(100, 200, 300, "new.pptx", "New content", ())

    session, _ = service.get_session(100, 200, 300)
    assert session is not None
    assert session.filename == "new.pptx"
    assert session.markdown == "New content"


def test_ttl_expiration():
    """Test that sessions older than ttl_minutes return was_expired=True and None."""
    service = DocumentSessionService(ttl_minutes=30)
    session = service.set_session(100, 200, 300, "doc.pdf", "Content", ())

    # Manually backdate created_at to 31 minutes ago
    session.created_at = datetime.now(timezone.utc) - timedelta(minutes=31)

    retrieved, was_expired = service.get_session(100, 200, 300)
    assert was_expired is True
    assert retrieved is None

    # Subsequent check should return None with was_expired=False
    retrieved_again, was_expired_again = service.get_session(100, 200, 300)
    assert was_expired_again is False
    assert retrieved_again is None


def test_max_sessions_capacity_purge():
    """Test that exceeding max_sessions capacity purges the oldest session."""
    service = DocumentSessionService(ttl_minutes=30, max_sessions=3)
    service.set_session(100, 200, 1, "doc1.pdf", "c1", ())
    service.set_session(100, 200, 2, "doc2.pdf", "c2", ())
    service.set_session(100, 200, 3, "doc3.pdf", "c3", ())

    # Store 4th session -> should purge doc1 (user 1)
    service.set_session(100, 200, 4, "doc4.pdf", "c4", ())

    session1, _ = service.get_session(100, 200, 1)
    assert session1 is None

    session4, _ = service.get_session(100, 200, 4)
    assert session4 is not None
    assert session4.filename == "doc4.pdf"
