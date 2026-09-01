from datetime import datetime, timezone

import pytest

from bot.services.community_games import CommunityGamesService
from bot.services.rewards_db import RewardsDBService, RewardsError


@pytest.fixture
def services() -> tuple[RewardsDBService, CommunityGamesService]:
    rewards = RewardsDBService(db_path=":memory:")
    return rewards, CommunityGamesService(rewards)


def test_study_raid_rewards_each_contributor(services: tuple[RewardsDBService, CommunityGamesService]) -> None:
    rewards, games = services
    games.create_activity(10, 1, "raid")
    games.join_activity(10, 2, "raid")
    games.launch_raid(10, 1)

    games.answer_activity(10, 2, "raid", "infinite loop")
    games.answer_activity(10, 2, "raid", "bca")
    result = games.answer_activity(10, 2, "raid", "3")

    assert result.completed is True
    assert rewards.get_balance(1) == 100
    assert rewards.get_balance(2) == 160


def test_escape_room_hint_reduces_reward(services: tuple[RewardsDBService, CommunityGamesService]) -> None:
    rewards, games = services
    games.create_activity(10, 1, "escape")
    games.use_escape_hint(10, 1)

    for answer in ("<", "a", "404"):
        result = games.answer_activity(10, 1, "escape", answer)

    assert result.completed is True
    assert rewards.get_balance(1) == 175

    games.create_activity(10, 1, "escape")
    for answer in ("<", "a", "404"):
        games.answer_activity(10, 1, "escape", answer)
    assert rewards.get_balance(1) == 175


def test_activity_rejects_second_answer_for_same_stage(services: tuple[RewardsDBService, CommunityGamesService]) -> None:
    _, games = services
    games.create_activity(10, 1, "escape")
    games.answer_activity(10, 1, "escape", "wrong")

    with pytest.raises(RewardsError, match="already answered"):
        games.answer_activity(10, 1, "escape", "i < 10")


def test_startup_runs_three_team_phases(services: tuple[RewardsDBService, CommunityGamesService]) -> None:
    rewards, games = services
    rewards.create_guild(10, 1, "Builders")
    rewards.join_guild(10, 2, "Builders")
    games.start_startup(10, 1, "Campus Queue")

    for phase in range(3):
        games.contribute_startup(10, 2, "research")
        result = games.advance_startup(10, 1)
        assert result.completed is (phase == 2)

    assert rewards.get_balance(1) >= 150
    assert rewards.get_balance(2) >= 150


def test_review_refunds_only_eligible_negative_transaction(services: tuple[RewardsDBService, CommunityGamesService]) -> None:
    rewards, games = services
    rewards.add_points(1, 200, "START")
    rewards.transfer_points(1, 2, 100)
    with rewards._get_connection() as conn:
        transaction_id = int(
            conn.execute(
                "SELECT id FROM transactions WHERE user_id = 1 AND action_type = 'GIVE_SENT' ORDER BY id DESC"
            ).fetchone()["id"]
        )

    case = games.file_review(10, 1, 2, transaction_id, "The transfer was disputed.")
    assert games.get_reviewable_transactions(1)[0]["id"] == transaction_id
    games.respond_review(case["id"], 2, "I have provided my response.")
    resolved = games.resolve_review(case["id"], 99, "refund", "Verified by moderator.")

    assert resolved["refunded"] == 100
    assert rewards.get_balance(1) == 200


def test_economy_pulse_reports_rank_change_and_growth(services: tuple[RewardsDBService, CommunityGamesService]) -> None:
    rewards, games = services
    rewards.add_points(1, 1_000, "START")
    rewards.add_points(2, 900, "START")
    first = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    games.capture_economy_pulse(now=first)

    rewards.add_points(2, 300, "BONUS")
    pulse = games.capture_economy_pulse(now=datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc))

    assert any(item["user_id"] == 2 and item["movement"] == 1 for item in pulse["movements"])
    assert any(item["user_id"] == 2 and item["delta"] == 300 for item in pulse["growth"])
