"""Tests for Real-World Prize Benchmark Win Rate Dampener."""

import random
from datetime import datetime, timedelta, timezone
import pytest

from bot.services.rewards_db import (
    RewardsDBService,
    BetOutcome,
    BlackjackCard,
)


@pytest.fixture
def test_db_service(tmp_path):
    db_path = tmp_path / "test_rewards_dampener.db"
    return RewardsDBService(db_path=str(db_path))


def _set_points(service: RewardsDBService, user_id: int, points: int) -> None:
    service.get_or_create_user(user_id)
    with service._get_connection() as conn:
        conn.execute("UPDATE users SET points = ? WHERE user_id = ?", (points, user_id))
        conn.commit()


def test_get_prize_benchmark_win_cap_curve(test_db_service: RewardsDBService):
    """Verify exact dampener mathematical curve across points tiers."""
    user = test_db_service.get_or_create_user(99901)

    # 1. Below 49,000 pts -> None (standard odds)
    _set_points(test_db_service, user.user_id, 0)
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) is None

    _set_points(test_db_service, user.user_id, 48_999)
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) is None

    # 2. Exactly 49,000 pts (1,000 away from Coffee Treat @ 50k) -> 10% (0.10)
    _set_points(test_db_service, user.user_id, 49_000)
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) == 0.10

    _set_points(test_db_service, user.user_id, 49_999)
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) == 0.10

    # 3. 50,000 pts (Coffee Treat reached / 50k away from Nitro) -> 10% (0.10)
    _set_points(test_db_service, user.user_id, 50_000)
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) == 0.10

    # 4. 65,000 pts (GCash ₱100 benchmark) -> 7.3%
    _set_points(test_db_service, user.user_id, 65_000)
    user = test_db_service.get_or_create_user(user.user_id)
    cap_65k = test_db_service.get_prize_benchmark_win_cap(user)
    assert cap_65k == 0.073

    # 5. 80,000 pts (Free Printing benchmark) -> 4.6%
    _set_points(test_db_service, user.user_id, 80_000)
    user = test_db_service.get_or_create_user(user.user_id)
    cap_80k = test_db_service.get_prize_benchmark_win_cap(user)
    assert cap_80k == 0.046

    # 6. 100,000 pts (1 Month Discord Nitro benchmark) -> 1.0% (0.01)
    _set_points(test_db_service, user.user_id, 100_000)
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) == 0.01

    # 7. > 100,000 pts -> 1.0% (0.01)
    _set_points(test_db_service, user.user_id, 150_000)
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) == 0.01


def test_bank_vault_assets_included_in_benchmark_cap(test_db_service: RewardsDBService):
    """Verify players cannot bypass the dampener by stashing points in bank vault."""
    user = test_db_service.get_or_create_user(99902)
    # Wallet has only 500 points, but Bank has 49,000 points (Total = 49,500)
    _set_points(test_db_service, user.user_id, 500)
    with test_db_service._get_connection() as conn:
        conn.execute("UPDATE users SET bank_points = 49000 WHERE user_id = ?", (user.user_id,))
        conn.commit()

    user = test_db_service.get_or_create_user(user.user_id)
    assert user.points == 500
    assert user.bank_points == 49000
    # Total assets = 49,500 -> triggers 10% cap
    assert test_db_service.get_prize_benchmark_win_cap(user) == 0.10

    # Total assets = 100,000 (Wallet 1,000 + Bank 99,000) -> triggers 1% cap
    _set_points(test_db_service, user.user_id, 1_000)
    with test_db_service._get_connection() as conn:
        conn.execute("UPDATE users SET bank_points = 99000 WHERE user_id = ?", (user.user_id,))
        conn.commit()
    user = test_db_service.get_or_create_user(user.user_id)
    assert test_db_service.get_prize_benchmark_win_cap(user) == 0.01


def test_deterministic_fixed_outcomes_unaffected(test_db_service: RewardsDBService):
    """Ensure fixed tests still work even when player has 100,000 points."""
    user_id = 99903
    _set_points(test_db_service, user_id, 100_000)

    # Fixed bet
    res_bet = test_db_service.play_bet(user_id, wager=50, fixed_outcome=BetOutcome.JACKPOT)
    assert res_bet.outcome == BetOutcome.JACKPOT

    # Fixed slots
    res_slots = test_db_service.play_slots(user_id, wager=50, fixed_reels=["🃏", "🃏", "🃏"])
    assert res_slots.is_jackpot is True

    # Fixed coinflip
    res_flip = test_db_service.play_coinflip(user_id, choice="heads", wager=50, fixed_flip="heads")
    assert res_flip.won is True

    # Fixed cups
    res_cups = test_db_service.play_cups(user_id, chosen_cup=1, wager=50, fixed_won=True)
    assert res_cups.won is True


def test_coinflip_and_cups_dampener_simulation(test_db_service: RewardsDBService):
    """Simulate 60 coinflips and cups at 100k points to verify win rate drops to ~1%."""
    user_id = 99904
    _set_points(test_db_service, user_id, 100_000)

    random.seed(42)
    flips_won = 0
    cups_won = 0
    total_rounds = 60

    for _ in range(total_rounds):
        res_cf = test_db_service.play_coinflip(user_id, choice="heads", wager=10)
        if res_cf.won:
            flips_won += 1
        res_cup = test_db_service.play_cups(user_id, chosen_cup=1, wager=10)
        if res_cup.won:
            cups_won += 1

    assert flips_won <= 4, f"Expected flips won <= 4 at 1% cap, got {flips_won}"
    assert cups_won <= 4, f"Expected cups won <= 4 at 1% cap, got {cups_won}"


def test_slots_and_bet_dampener_simulation(test_db_service: RewardsDBService):
    """Simulate slots and bet at 100k points to verify bust rate is massive."""
    user_id = 99905
    _set_points(test_db_service, user_id, 100_000)

    random.seed(42)
    slots_wins = 0
    bet_wins = 0
    total_rounds = 60

    for _ in range(total_rounds):
        res_s = test_db_service.play_slots(user_id, wager=10)
        if res_s.points_delta > 0:
            slots_wins += 1
        res_b = test_db_service.play_bet(user_id, wager=10)
        if res_b.outcome in (BetOutcome.JACKPOT, BetOutcome.DOUBLE, BetOutcome.SKILL_DROP):
            bet_wins += 1

    assert slots_wins <= 4, f"Expected slots wins <= 4 at 1% cap, got {slots_wins}"
    assert bet_wins <= 4, f"Expected bet wins <= 4 at 1% cap, got {bet_wins}"


def test_steal_and_duel_dampener(test_db_service: RewardsDBService):
    """Verify steal success rate is capped and duel rolls dampened for high-asset users."""
    thief_id = 99906
    target_id = 99907
    _set_points(test_db_service, thief_id, 100_000)
    _set_points(test_db_service, target_id, 1_000)
    test_db_service.add_item(thief_id, "pickpocket", 100)

    random.seed(42)
    steals_won = 0
    base_time = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(40):
        test_db_service.add_item(thief_id, "pickpocket", 1)
        res = test_db_service.execute_steal(thief_id, target_id, now=base_time + timedelta(seconds=65 * i))
        if res.success:
            steals_won += 1

    assert steals_won <= 3, f"Expected steals won <= 3 at 1% cap, got {steals_won}"
