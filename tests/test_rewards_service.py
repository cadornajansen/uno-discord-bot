from datetime import datetime, timedelta, timezone
import pytest

from bot.services.rewards_db import (
    RewardsDBService,
    DailyAlreadyClaimedError,
    InsufficientPointsError,
    ItemNotFoundError,
)


@pytest.fixture
def rewards_service() -> RewardsDBService:
    """Fixture providing an in-memory RewardsDBService instance."""
    return RewardsDBService(db_path=":memory:")


def test_get_or_create_user(rewards_service: RewardsDBService):
    """Test initial user record creation."""
    user = rewards_service.get_or_create_user(1001)
    assert user.user_id == 1001
    assert user.points == 0
    assert user.lifetime_points == 0
    assert user.daily_streak == 0
    assert rewards_service.get_balance(1001) == 0


def test_claim_daily_streak_progression(rewards_service: RewardsDBService):
    """Test daily claims over consecutive days increment streak and bonus points."""
    day1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    res1 = rewards_service.claim_daily(1001, now=day1)
    assert res1.streak == 1
    assert res1.base_points == 30
    assert res1.streak_bonus == 0
    assert res1.points_awarded == 30
    assert res1.new_balance == 30

    # Same day claim should fail
    with pytest.raises(DailyAlreadyClaimedError):
        rewards_service.claim_daily(1001, now=day1 + timedelta(hours=2))

    # Day 2 consecutive claim
    day2 = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)
    res2 = rewards_service.claim_daily(1001, now=day2)
    assert res2.streak == 2
    assert res2.streak_bonus == 5
    assert res2.points_awarded == 35
    assert res2.new_balance == 65

    # Day 3 consecutive claim
    day3 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    res3 = rewards_service.claim_daily(1001, now=day3)
    assert res3.streak == 3
    assert res3.streak_bonus == 10
    assert res3.points_awarded == 40
    assert res3.new_balance == 105


def test_claim_daily_missed_day_resets_streak(rewards_service: RewardsDBService):
    """Test missing a day resets daily streak back to 1."""
    day1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    rewards_service.claim_daily(1001, now=day1)

    # Skip a day -> Day 3
    day3 = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
    res = rewards_service.claim_daily(1001, now=day3)
    assert res.streak == 1
    assert res.points_awarded == 30


def test_3000_milestone_detection(rewards_service: RewardsDBService):
    """Test 3000 lifetime points milestone unlock detection."""
    rewards_service.add_points(1001, 2980, "TEST")
    day1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    res = rewards_service.claim_daily(1001, now=day1)

    assert res.milestone_3k_unlocked is True
    profile = rewards_service.get_profile(1001)
    assert "🍫 Exam Survivor" in profile.badges


def test_7_day_immunity_shield(rewards_service: RewardsDBService):
    """Test 7-day Immunity Shield activation and expiration."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    assert not rewards_service.has_active_shield(1001, now=now)

    # Activate 7-day shield
    shield_until = rewards_service.activate_shield(1001, duration_days=7, now=now)
    assert rewards_service.has_active_shield(1001, now=now)
    assert rewards_service.has_active_shield(1001, now=now + timedelta(days=6))

    # After 7 days and 1 hour -> expired
    assert not rewards_service.has_active_shield(1001, now=now + timedelta(days=7, hours=1))


def test_inventory_add_remove_item(rewards_service: RewardsDBService):
    """Test adding, consuming, and error handling for inventory cards."""
    rewards_service.add_item(1001, "pickpocket", quantity=2)
    inv = rewards_service.get_inventory(1001)
    assert inv["pickpocket"] == 2

    # Remove 1
    rewards_service.remove_item(1001, "pickpocket", quantity=1)
    inv = rewards_service.get_inventory(1001)
    assert inv["pickpocket"] == 1

    # Remove second -> deleted from table
    rewards_service.remove_item(1001, "pickpocket", quantity=1)
    inv = rewards_service.get_inventory(1001)
    assert "pickpocket" not in inv

    # Remove when empty -> ItemNotFoundError
    with pytest.raises(ItemNotFoundError):
        rewards_service.remove_item(1001, "pickpocket", quantity=1)


def test_leaderboard_and_profile_ranking(rewards_service: RewardsDBService):
    """Test paginated leaderboard ordering and profile rank computation."""
    rewards_service.add_points(1001, 500, "TEST")
    rewards_service.add_points(1002, 1200, "TEST")
    rewards_service.add_points(1003, 800, "TEST")

    entries, total = rewards_service.get_leaderboard(limit=2, offset=0)
    assert total == 3
    assert len(entries) == 2
    assert entries[0].user_id == 1002
    assert entries[0].rank == 1
    assert entries[1].user_id == 1003
    assert entries[1].rank == 2

    # Second page
    entries_p2, _ = rewards_service.get_leaderboard(limit=2, offset=2)
    assert len(entries_p2) == 1
    assert entries_p2[0].user_id == 1001
    assert entries_p2[0].rank == 3

    # Check profile rank
    p1 = rewards_service.get_profile(1002)
    assert p1.rank == 1
    assert "👑 Top 1 Scholar" in p1.badges

    p3 = rewards_service.get_profile(1001)
    assert p3.rank == 3
    assert "🌟 Top 3 Elite" in p3.badges


def test_deduct_points_insufficient_balance(rewards_service: RewardsDBService):
    """Test deducting points raises error when balance is inadequate."""
    rewards_service.add_points(1001, 100, "TEST")
    with pytest.raises(InsufficientPointsError):
        rewards_service.deduct_points(1001, 250, "TEST")


def test_csv_export(rewards_service: RewardsDBService):
    """Test CSV export string contains user rows."""
    rewards_service.add_points(1001, 500, "TEST")
    csv_text = rewards_service.export_csv()
    assert "user_id,points,lifetime_points" in csv_text
    assert "1001,500,500" in csv_text


def test_play_bet_outcomes_and_limit(rewards_service: RewardsDBService):
    """Test bet mechanics, skill drops, and 3-bet daily cap."""
    from bot.services.rewards_db import BetOutcome, MaxBetsReachedError

    rewards_service.add_points(1001, 300, "TEST")
    now = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)

    # Bet 1: DOUBLE (+50 net)
    b1 = rewards_service.play_bet(1001, now=now, fixed_outcome=BetOutcome.DOUBLE)
    assert b1.points_delta == 50
    assert b1.new_balance == 350
    assert b1.bets_remaining == 2

    # Bet 2: SKILL_DROP (-50 pts, +1 pickpocket)
    b2 = rewards_service.play_bet(1001, now=now, fixed_outcome=BetOutcome.SKILL_DROP, fixed_skill="pickpocket")
    assert b2.points_delta == -50
    assert b2.new_balance == 300
    assert b2.bets_remaining == 1
    inv = rewards_service.get_inventory(1001)
    assert inv["pickpocket"] == 1

    # Bet 3: BUST (-50 pts)
    b3 = rewards_service.play_bet(1001, now=now, fixed_outcome=BetOutcome.BUST)
    assert b3.new_balance == 250
    assert b3.bets_remaining == 0

    # Bet 4 on same day -> MaxBetsReachedError
    with pytest.raises(MaxBetsReachedError):
        rewards_service.play_bet(1001, now=now)

    # Next day -> bets reset
    next_day = now + timedelta(days=1)
    b4 = rewards_service.play_bet(1001, now=next_day, fixed_outcome=BetOutcome.REFUND)
    assert b4.bets_remaining == 2


def test_execute_steal_mechanics(rewards_service: RewardsDBService):
    """Test pickpocket steal success, shield block, and caught fine."""
    from bot.services.rewards_db import RewardsError

    rewards_service.add_points(1001, 100, "THIEF")  # Thief
    rewards_service.add_points(1002, 500, "TARGET") # Target
    rewards_service.add_item(1001, "pickpocket", 2)

    # 1. Successful Steal
    res_win = rewards_service.execute_steal(1001, 1002, fixed_success=True, fixed_amount=50)
    assert res_win.success is True
    assert res_win.points_stolen == 50
    assert res_win.thief_new_balance == 150
    assert res_win.target_new_balance == 450

    # 2. Target activates Immunity Shield -> Next steal is BLOCKED
    rewards_service.activate_shield(1002, duration_days=7)
    res_blocked = rewards_service.execute_steal(1001, 1002)
    assert res_blocked.blocked_by_shield is True
    assert res_blocked.points_stolen == 0
    assert res_blocked.thief_new_balance == 150

    # 3. Steal without item -> ItemNotFoundError
    with pytest.raises(ItemNotFoundError):
        rewards_service.execute_steal(1001, 1002)

    # 4. Thief caught red-handed -> pays fine
    rewards_service.add_item(1001, "pickpocket", 1)
    rewards_service.add_points(1003, 300, "UNSHIELDED")
    res_busted = rewards_service.execute_steal(1001, 1003, fixed_success=False)
    assert res_busted.success is False
    assert res_busted.fine_paid == 30
    assert res_busted.thief_new_balance == 120  # 150 - 30


def test_use_item_activation(rewards_service: RewardsDBService):
    """Test using inventory items activates 7-day shield."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    rewards_service.add_item(1001, "shield_1w", 1)

    res = rewards_service.use_item(1001, "shield_1w", now=now)
    assert "1-Week Immunity Shield" in res.item_name
    assert rewards_service.has_active_shield(1001, now=now)
    inv = rewards_service.get_inventory(1001)
    assert "shield_1w" not in inv
