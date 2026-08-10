import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ConversationTurn:
    user: str
    assistant: str
    updated_at: float


class ConversationMemory:
    """Small in-memory chat history isolated by server, channel, and user."""

    def __init__(
        self,
        max_turns: int = 4,
        ttl_minutes: int = 30,
        max_tokens: int = 1200,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_turns = max_turns
        self.ttl_seconds = ttl_minutes * 60
        self.max_characters = max_tokens * 4
        self._clock = clock
        self._turns: dict[tuple[int, int, int], list[ConversationTurn]] = {}
        self._locks: defaultdict[tuple[int, int, int], asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock_for(self, guild_id: int, channel_id: int, user_id: int) -> asyncio.Lock:
        return self._locks[(guild_id, channel_id, user_id)]

    def get_messages(self, guild_id: int, channel_id: int, user_id: int) -> list[dict[str, str]]:
        key = (guild_id, channel_id, user_id)
        turns = self._active_turns(key)
        messages: list[dict[str, str]] = []
        for turn in turns:
            messages.extend(
                [
                    {"role": "user", "content": turn.user},
                    {"role": "assistant", "content": turn.assistant},
                ]
            )
        return messages

    def add_turn(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        user: str,
        assistant: str,
    ) -> None:
        key = (guild_id, channel_id, user_id)
        turns = self._active_turns(key)
        turns.append(ConversationTurn(user=user, assistant=assistant, updated_at=self._clock()))
        turns = turns[-self.max_turns :]
        while turns and sum(len(turn.user) + len(turn.assistant) for turn in turns) > self.max_characters:
            turns.pop(0)
        self._turns[key] = turns

    def clear(self, guild_id: int, channel_id: int, user_id: int) -> bool:
        return self._turns.pop((guild_id, channel_id, user_id), None) is not None

    def _active_turns(self, key: tuple[int, int, int]) -> list[ConversationTurn]:
        turns = self._turns.get(key, [])
        if turns and self._clock() - turns[-1].updated_at >= self.ttl_seconds:
            self._turns.pop(key, None)
            return []
        return list(turns)
