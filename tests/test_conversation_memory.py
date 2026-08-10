from bot.services.conversation_memory import ConversationMemory


def test_memory_is_isolated_and_bounded_by_turns() -> None:
    memory = ConversationMemory(max_turns=2, ttl_minutes=30, max_tokens=1200)
    memory.add_turn(1, 2, 3, "first", "one")
    memory.add_turn(1, 2, 3, "second", "two")
    memory.add_turn(1, 2, 3, "third", "three")

    assert memory.get_messages(1, 2, 3)[0]["content"] == "second"
    assert memory.get_messages(1, 2, 4) == []


def test_memory_expires_and_can_be_cleared() -> None:
    now = [0.0]
    memory = ConversationMemory(ttl_minutes=1, clock=lambda: now[0])
    memory.add_turn(1, 2, 3, "hello", "hi")
    now[0] = 60.0
    assert memory.get_messages(1, 2, 3) == []

    memory.add_turn(1, 2, 3, "again", "yes")
    assert memory.clear(1, 2, 3) is True
    assert memory.get_messages(1, 2, 3) == []
