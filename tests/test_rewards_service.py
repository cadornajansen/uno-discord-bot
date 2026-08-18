from datetime import datetime, timedelta, timezone
import pytest

from bot.services.rewards_db import (
    RewardsDBService,
    RewardsError,
    DailyAlreadyClaimedError,
    InsufficientPointsError,
    ItemNotFoundError,
    MaxTriviaReachedError,
    BetOutcome,
    BlackjackCard,
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
    assert res1.base_points == 20
    assert res1.streak_bonus == 0
    assert res1.points_awarded == 20
    assert res1.new_balance == 20

    # Same day claim should fail
    with pytest.raises(DailyAlreadyClaimedError):
        rewards_service.claim_daily(1001, now=day1 + timedelta(hours=2))

    # Day 2 consecutive claim
    day2 = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)
    res2 = rewards_service.claim_daily(1001, now=day2)
    assert res2.streak == 2
    assert res2.streak_bonus == 2
    assert res2.points_awarded == 22
    assert res2.new_balance == 42

    # Day 3 consecutive claim
    day3 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    res3 = rewards_service.claim_daily(1001, now=day3)
    assert res3.streak == 3
    assert res3.streak_bonus == 4
    assert res3.points_awarded == 24
    assert res3.new_balance == 66


def test_claim_daily_missed_day_resets_streak(rewards_service: RewardsDBService):
    """Test missing a day resets daily streak back to 1."""
    day1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    rewards_service.claim_daily(1001, now=day1)

    # Skip a day -> Day 3
    day3 = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
    res = rewards_service.claim_daily(1001, now=day3)
    assert res.streak == 1
    assert res.points_awarded == 20


def test_claim_daily_resets_at_midnight_pht(rewards_service: RewardsDBService):
    """Test that claiming at 11:50 PM PHT and claiming again at 12:05 AM PHT (new calendar day) succeeds."""
    from bot.services.rewards_db import PHT

    # 1. Claim at 11:50 PM Manila Time (Aug 17)
    night_time = datetime(2026, 8, 17, 23, 50, tzinfo=PHT)
    res1 = rewards_service.claim_daily(1001, now=night_time)
    assert res1.streak == 1
    assert res1.points_awarded == 20

    # 2. Claim at 11:55 PM (same day) -> raises DailyAlreadyClaimedError pointing to 12:00 AM midnight
    with pytest.raises(DailyAlreadyClaimedError) as exc_info:
        rewards_service.claim_daily(1001, now=night_time + timedelta(minutes=5))
    expected_midnight = datetime(2026, 8, 18, 0, 0, tzinfo=PHT)
    assert exc_info.value.next_claim_time == expected_midnight

    # 3. Claim at 12:05 AM Manila Time (Aug 18, just 15 minutes later!) -> SUCCEEDS immediately!
    next_day_early = datetime(2026, 8, 18, 0, 5, tzinfo=PHT)
    res2 = rewards_service.claim_daily(1001, now=next_day_early)
    assert res2.streak == 2
    assert res2.points_awarded == 22
    assert res2.new_balance == 42


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
    """Test bet mechanics, dynamic payouts, and skill drops with unlimited wagers."""
    from bot.services.rewards_db import BetOutcome

    rewards_service.add_points(1001, 300, "TEST")
    now = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)

    # Bet 1: JACKPOT (+150 net on 50 wager -> 4x total payout)
    b1 = rewards_service.play_bet(1001, wager=50, now=now, fixed_outcome=BetOutcome.JACKPOT)
    assert b1.points_delta == 150
    assert b1.new_balance == 450

    # Bet 2: SKILL_DROP (reimburses wager + drops skill item)
    b2 = rewards_service.play_bet(1001, wager=50, now=now, fixed_outcome=BetOutcome.SKILL_DROP, fixed_skill="pickpocket")
    assert b2.points_delta == 0
    assert b2.new_balance == 450
    inv = rewards_service.get_inventory(1001)
    assert inv["pickpocket"] == 1

    # Bet 3: BUST (-50 pts)
    b3 = rewards_service.play_bet(1001, wager=50, now=now, fixed_outcome=BetOutcome.BUST)
    assert b3.new_balance == 400

    # Bet 4 on same day
    b4 = rewards_service.play_bet(1001, wager=50, now=now, fixed_outcome=BetOutcome.REFUND)
    assert b4.new_balance == 400
    assert b4.daily_bets_count == 4
    assert b4.bets_remaining == 6


def test_play_bet_daily_limit_and_rigged_mechanics(rewards_service: RewardsDBService):
    """Test 10 daily bet limit, rigged 5-win trap (next 7 forced losses), and pity system."""
    import pytest
    from bot.services.rewards_db import BetOutcome, MaxBetsReachedError

    rewards_service.add_points(2001, 50000, "TEST")
    day1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)

    # 1. Test 5 consecutive wins -> triggers 7 rigged forced losses
    for _ in range(5):
        win_res = rewards_service.play_bet(2001, wager=50, now=day1, fixed_outcome=BetOutcome.DOUBLE)
        assert win_res.outcome == BetOutcome.DOUBLE

    u = rewards_service.get_or_create_user(2001)
    assert u.bet_rigged_loss_remaining == 7
    assert u.bet_win_streak == 0

    # Next 5 bets on day 1 (reaching limit 10/10) must be forced BUSTs
    for i in range(5):
        loss_res = rewards_service.play_bet(2001, wager=50, now=day1)
        assert loss_res.outcome == BetOutcome.BUST
        assert loss_res.daily_bets_count == 6 + i

    # 11th bet on same day raises MaxBetsReachedError
    with pytest.raises(MaxBetsReachedError):
        rewards_service.play_bet(2001, wager=50, now=day1)

    # 2. Next Day (Day 2): 2 remaining rigged losses from the 7 penalty
    day2 = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    for _ in range(2):
        loss_res = rewards_service.play_bet(2001, wager=50, now=day2)
        assert loss_res.outcome == BetOutcome.BUST

    u2 = rewards_service.get_or_create_user(2001)
    assert u2.bet_rigged_loss_remaining == 0

    # 3. Test Pity System (5 consecutive losses outside rigged penalty -> guaranteed win)
    rewards_service.add_points(3001, 10000, "TEST")
    for _ in range(5):
        rewards_service.play_bet(3001, wager=50, now=day1, fixed_outcome=BetOutcome.BUST)

    u3 = rewards_service.get_or_create_user(3001)
    assert u3.bet_loss_streak == 5

    # 6th bet triggers Pity System -> guaranteed win!
    pity_res = rewards_service.play_bet(3001, wager=50, now=day1)
    assert pity_res.outcome in (BetOutcome.DOUBLE, BetOutcome.JACKPOT, BetOutcome.SKILL_DROP)
    u3_after = rewards_service.get_or_create_user(3001)
    assert u3_after.bet_loss_streak == 0


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
    assert res_busted.thief_new_balance == 120


def test_steal_percentage_range(rewards_service: RewardsDBService):
    """Test that steal without fixed_amount extracts 15%-30% (capped at 120 pts) of target balance."""
    rewards_service.add_points(1001, 100, "THIEF")
    rewards_service.add_points(1002, 1000, "TARGET")
    rewards_service.add_item(1001, "pickpocket", 1)

    res = rewards_service.execute_steal(1001, 1002, fixed_success=True)
    assert res.success is True
    # 15% to 30% of 1,000 points capped at 120 is 120 points
    assert res.points_stolen <= 120
    assert res.target_new_balance == 1000 - res.points_stolen
    assert res.thief_new_balance == 100 + res.points_stolen


def test_use_item_activation(rewards_service: RewardsDBService):
    """Test using inventory items activates 7-day shield."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    rewards_service.add_item(1001, "shield_1w", 1)

    res = rewards_service.use_item(1001, "shield_1w", now=now)
    assert "1-Week Immunity Shield" in res.item_name
    assert rewards_service.has_active_shield(1001, now=now)
    inv = rewards_service.get_inventory(1001)
    assert "shield_1w" not in inv


def test_record_and_update_redemptions(rewards_service: RewardsDBService):
    """Test purchasing shop items, approvals, and refunds."""
    rewards_service.add_points(1001, 3000, "TEST")

    # 1. Consumable purchase -> auto-granted to inventory
    res_cons = rewards_service.record_redemption(1001, "pickpocket")
    assert res_cons["status"] == "DELIVERED"
    assert rewards_service.get_balance(1001) == 2900
    assert rewards_service.get_inventory(1001)["pickpocket"] == 1

    # 2. Physical prize purchase -> PENDING status
    res_coffee = rewards_service.record_redemption(1001, "coffee")
    assert res_coffee["status"] == "PENDING"
    assert rewards_service.get_balance(1001) == 1700

    # 3. Approve redemption
    app_res = rewards_service.update_redemption_status(res_coffee["id"], "APPROVED")
    assert app_res["status"] == "APPROVED"

    # 4. Another redemption -> REJECT & REFUND
    rewards_service.add_points(1001, 1000, "TEST")  # 1700 + 1000 = 2700
    res_gcash = rewards_service.record_redemption(1001, "gcash_100")
    assert rewards_service.get_balance(1001) == 500

    # Reject -> refund 2200 points
    rej_res = rewards_service.update_redemption_status(res_gcash["id"], "REJECTED")
    assert rej_res["status"] == "REJECTED"
    assert rewards_service.get_balance(1001) == 2700


def test_trivia_service_mechanics(rewards_service: RewardsDBService):
    """Test trivia quiz rewards (+25 pts), wrong answers (0 pts), daily cap (3/day), and reset."""
    today = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)

    # 1. Correct answer -> +25 points
    res1 = rewards_service.record_trivia_attempt(1001, is_correct=True, now=today)
    assert res1.is_correct is True
    assert res1.points_awarded == 25
    assert res1.new_balance == 25
    assert res1.trivia_remaining == 2
    assert rewards_service.get_balance(1001) == 25

    # 2. Incorrect answer -> 0 points, attempt counted
    res2 = rewards_service.record_trivia_attempt(1001, is_correct=False, now=today)
    assert res2.is_correct is False
    assert res2.points_awarded == 0
    assert res2.new_balance == 25
    assert res2.trivia_remaining == 1
    assert rewards_service.get_balance(1001) == 25

    # 3. Third attempt (correct) -> +25 points, 0 remaining
    res3 = rewards_service.record_trivia_attempt(1001, is_correct=True, now=today)
    assert res3.is_correct is True
    assert res3.points_awarded == 25
    assert res3.new_balance == 50
    assert res3.trivia_remaining == 0

    # 4. 4th attempt on same day -> MaxTriviaReachedError
    with pytest.raises(MaxTriviaReachedError):
        rewards_service.record_trivia_attempt(1001, is_correct=True, now=today)

    # 5. Next day -> resets, allows 3 new attempts
    res_next = rewards_service.record_trivia_attempt(1001, is_correct=True, now=next_day)
    assert res_next.is_correct is True
    assert res_next.points_awarded == 25
    assert res_next.new_balance == 75
    assert res_next.trivia_remaining == 2


def test_trivia_anti_repetition_and_reset(rewards_service: RewardsDBService):
    """Test that users receive unique questions without repeats until the bank is fully completed."""
    from bot.services.rewards_db import TRIVIA_QUESTIONS

    total = len(TRIVIA_QUESTIONS)
    seen_ids = set()

    for _ in range(total):
        idx, q = rewards_service.get_random_trivia_question(user_id=1001)
        assert idx not in seen_ids
        seen_ids.add(idx)

    assert len(seen_ids) == total

    # Next call resets history and returns a question successfully
    next_idx, next_q = rewards_service.get_random_trivia_question(user_id=1001)
    assert 0 <= next_idx < total


def test_uno_reverse_card_counter_steals(rewards_service: RewardsDBService):
    """Test that Uno Reverse card in defender's inventory deflects steal and counter-robs thief."""
    rewards_service.add_points(1001, 200, "THIEF")
    rewards_service.add_points(1002, 300, "DEFENDER")
    rewards_service.add_item(1001, "pickpocket", 1)
    rewards_service.add_item(1002, "uno_reverse", 1)

    res = rewards_service.execute_steal(1001, 1002)
    assert res.reversed_by_uno is True
    assert res.success is False
    assert res.blocked_by_shield is False
    assert res.points_stolen > 0  # 15% of thief 200 pts = 30 pts
    assert res.thief_new_balance == 200 - res.points_stolen
    assert res.target_new_balance == 300 + res.points_stolen

    # Uno reverse is consumed
    assert "uno_reverse" not in rewards_service.get_inventory(1002)


def test_shield_breaker_and_tax_audit(rewards_service: RewardsDBService):
    """Test EMP Shield Breaker destroying shields and Tax Audit taxing Top-3 players."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    rewards_service.add_points(1001, 500, "TOP1")
    rewards_service.add_points(1002, 100, "AUDITOR")

    # 1. Activate shield on Top 1
    rewards_service.add_item(1001, "shield_1w", 1)
    rewards_service.use_item(1001, "shield_1w", now=now)
    assert rewards_service.has_active_shield(1001, now=now)

    # 2. Break shield using EMP Shield Breaker
    rewards_service.add_item(1002, "shield_breaker", 1)
    res_break = rewards_service.use_item(1002, "shield_breaker", target_id=1001, now=now)
    assert "EMP Shatter" in res_break.description
    assert not rewards_service.has_active_shield(1001, now=now)
    assert "shield_breaker" not in rewards_service.get_inventory(1002)

    # 3. Tax Audit Top 1 player (5% of 500 = 25 pts)
    rewards_service.add_item(1002, "tax_audit", 1)
    res_tax = rewards_service.use_item(1002, "tax_audit", target_id=1001, now=now)
    assert res_tax.points_awarded == 25
    assert rewards_service.get_balance(1001) == 475
    assert rewards_service.get_balance(1002) == 125


def test_coffee_bribe_and_gacha_box(rewards_service: RewardsDBService):
    """Test Coffee Bribe instant points and Gacha Box opening."""
    rewards_service.add_points(1001, 100, "TEST")

    # Coffee Bribe
    rewards_service.add_item(1001, "coffee_bribe", 1)
    res_coffee = rewards_service.use_item(1001, "coffee_bribe")
    assert 100 <= res_coffee.points_awarded <= 180
    assert rewards_service.get_balance(1001) == 100 + res_coffee.points_awarded

    # Gacha Box
    rewards_service.add_item(1001, "gacha_box", 1)
    res_gacha = rewards_service.use_item(1001, "gacha_box")
    assert res_gacha.points_awarded >= 50
    assert res_gacha.bonus_item_name is not None


def test_pet_adoption_and_switching(rewards_service: RewardsDBService):
    """Test adopting multiple pets, listing collection, switching active pet, and renaming."""
    rewards_service.add_points(1001, 2000, "START")

    # 1. Adopt Tuxedo Cat (50 pts)
    pet1 = rewards_service.adopt_pet(1001, "tuxedo_cat", nickname="Oreo")
    assert pet1.nickname == "Oreo"
    assert pet1.is_active is True
    assert rewards_service.get_balance(1001) == 2000 - 50

    # 2. Adopt Golden Retriever (50 pts)
    pet2 = rewards_service.adopt_pet(1001, "golden_dog", nickname="Buddy")
    assert pet2.nickname == "Buddy"
    assert pet2.is_active is False  # First adopted stays active by default

    # 3. List pets
    all_pets = rewards_service.get_user_pets(1001)
    assert len(all_pets) == 2

    # 4. Switch active pet to Golden Retriever
    switched = rewards_service.switch_active_pet(1001, "golden_dog")
    assert switched.pet_id == "golden_dog"
    active = rewards_service.get_active_pet(1001)
    assert active is not None
    assert active.pet_id == "golden_dog"

    # 5. Rename pet
    renamed = rewards_service.rename_pet(1001, "golden_dog", "Barkley")
    assert renamed.nickname == "Barkley"


def test_pet_cat_perk_daily(rewards_service: RewardsDBService):
    """Test Cat 2x daily claim perk."""
    rewards_service.add_points(1001, 1000, "START")
    rewards_service.adopt_pet(1001, "tuxedo_cat")

    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    res = rewards_service.claim_daily(1001, now=now)
    # Day 1 base: 20 pts, with 2x cat perk: 40 pts
    assert res.points_awarded == 40


def test_pet_turtle_perk(rewards_service: RewardsDBService):
    """Test Turtle streak freeze on missed days and +2d shield extension."""
    rewards_service.add_points(1001, 1000, "START")
    rewards_service.adopt_pet(1001, "oogway_turtle")

    # Day 1
    d1 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    res1 = rewards_service.claim_daily(1001, now=d1)
    assert res1.streak == 1

    # Miss 2 days (jump to Day 4) -> Turtle protects streak!
    d4 = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    res4 = rewards_service.claim_daily(1001, now=d4)
    assert res4.streak == 2  # Streak was frozen, not reset to 1!

    # Shield duration + 2 days
    shield_until = rewards_service.activate_shield(1001, duration_days=7, now=d4)
    assert (shield_until - d4).days == 9  # 7 + 2 = 9 days


def test_pet_dog_guard_and_bite(rewards_service: RewardsDBService):
    """Test Dog companion guarding against thieves and inflicting bite fine."""
    rewards_service.add_points(1001, 500, "THIEF")
    rewards_service.add_points(1002, 1000, "TARGET")
    rewards_service.adopt_pet(1002, "golden_dog")  # Target owns Guard Dog

    rewards_service.add_item(1001, "pickpocket", 1)
    res = rewards_service.execute_steal(1001, 1002, fixed_success=False)
    assert res.success is False
    assert res.fine_paid == 50  # 50 pt dog bite fine instead of 30 pt standard fine


def test_pet_owl_trivia_perk(rewards_service: RewardsDBService):
    """Test Scholar Owl granting +40 pts per quiz and 4 daily attempts."""
    rewards_service.add_points(1001, 1000, "START")
    rewards_service.adopt_pet(1001, "scholar_owl")

    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    # Attempt 1
    r1 = rewards_service.record_trivia_attempt(1001, is_correct=True, now=now)
    assert r1.points_awarded == 40
    # Attempt 2
    rewards_service.record_trivia_attempt(1001, is_correct=True, now=now)
    # Attempt 3
    rewards_service.record_trivia_attempt(1001, is_correct=True, now=now)
    # Attempt 4 (Unlocked by Owl!)
    r4 = rewards_service.record_trivia_attempt(1001, is_correct=True, now=now)
    assert r4.trivia_remaining == 0

    # Attempt 5 -> Max reached
    with pytest.raises(MaxTriviaReachedError):
        rewards_service.record_trivia_attempt(1001, is_correct=True, now=now)


def test_pet_axolotl_cashback(rewards_service: RewardsDBService):
    """Test Axolotl granting 5% cashback on shop purchases."""
    rewards_service.add_points(1001, 2000, "START")
    rewards_service.adopt_pet(1001, "pink_axolotl")
    # Cost was 150, balance is 1850

    # Buy 1-week shield (150 pts) -> 5% cashback = 7 pts refund
    res = rewards_service.record_redemption(1001, "shield_1w")
    assert res["status"] == "DELIVERED"
    # 1850 - 150 + 7 = 1707 pts
    assert rewards_service.get_balance(1001) == 1707


def test_pet_interactions(rewards_service: RewardsDBService):
    """Test feeding snacks and petting companion."""
    rewards_service.add_points(1001, 1000, "START")
    rewards_service.adopt_pet(1001, "tuxedo_cat")

    feed_res = rewards_service.interact_pet(1001, action="feed")
    assert feed_res.happiness > 0
    assert feed_res.xp > 0

    pet_res = rewards_service.interact_pet(1001, action="pet")
    assert "petted" in pet_res.message.lower() or "cuddled" in pet_res.message.lower()


def test_sell_pet_calculation_and_active_fallback(rewards_service: RewardsDBService):
    """Test selling pet calculates 60% refund + level bonuses, and re-assigns active companion."""
    rewards_service.add_points(1001, 3000, "START")

    # 1. Adopt Tuxedo Cat (50 pts) and Golden Dog (50 pts)
    rewards_service.adopt_pet(1001, "tuxedo_cat")
    rewards_service.adopt_pet(1001, "golden_dog")
    assert rewards_service.get_active_pet(1001).pet_id == "tuxedo_cat"

    # Level up Tuxedo Cat to Level 2
    for _ in range(4):
        rewards_service.interact_pet(1001, action="feed")
    active_cat = rewards_service.get_active_pet(1001)
    assert active_cat.level >= 2

    # Tuxedo Cat base: 50 -> 60% = 30 pts. Level bonus: +25 pts per level above 1
    bal_before = rewards_service.get_balance(1001)
    res_sell = rewards_service.sell_pet(1001, "tuxedo_cat")
    assert res_sell["base_refund"] == 30
    assert res_sell["level_bonus"] >= 25
    assert res_sell["refund_amount"] == res_sell["base_refund"] + res_sell["level_bonus"]
    assert rewards_service.get_balance(1001) == bal_before + res_sell["refund_amount"]

    # Cat is removed from collection
    pets_left = rewards_service.get_user_pets(1001)
    assert len(pets_left) == 1
    assert pets_left[0].pet_id == "golden_dog"

    # Golden Dog became the new active companion automatically!
    new_active = rewards_service.get_active_pet(1001)
    assert new_active is not None
    assert new_active.pet_id == "golden_dog"


def test_claim_starter_pet_success_and_protection(rewards_service: RewardsDBService):
    """Test claiming a free starter pet for 0 points and preventing duplicate claims."""
    # New user with 0 points
    assert rewards_service.get_balance(2001) == 0
    assert rewards_service.get_or_create_user(2001).has_claimed_starter is False

    # Claim free Tuxedo Cat
    pet_rec = rewards_service.claim_starter_pet(2001, "tuxedo_cat", nickname="LuckyCat")
    assert pet_rec.pet_id == "tuxedo_cat"
    assert pet_rec.nickname == "LuckyCat"
    assert pet_rec.is_active is True
    assert rewards_service.get_balance(2001) == 0  # 0 points spent (FREE!)
    assert rewards_service.get_or_create_user(2001).has_claimed_starter is True

    # Attempting to claim another free starter raises RewardsError
    with pytest.raises(RewardsError):
        rewards_service.claim_starter_pet(2001, "golden_dog")


def test_sell_nonexistent_pet_error(rewards_service: RewardsDBService):
    """Test selling a pet not owned raises RewardsError."""
    with pytest.raises(RewardsError):
        rewards_service.sell_pet(1001, "white_bunny")


def test_featured_pet_rotation_schedule(rewards_service: RewardsDBService):
    """Test 3-day rotating pet drop calculation."""
    anchor = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    drop_day1 = rewards_service.get_featured_pet(now=anchor)
    assert drop_day1["pet_id"] == "tuxedo_cat"
    assert drop_day1["cycle_day"] in (1, 2, 3)

    # Fast-forward 3 days (August 21) -> Should rotate to next pet (golden_dog)
    drop_cycle2 = rewards_service.get_featured_pet(now=anchor + timedelta(days=3))
    assert drop_cycle2["pet_id"] == "golden_dog"
    assert drop_cycle2["cycle_number"] == 1


def test_custom_wager_bet(rewards_service: RewardsDBService):
    """Test unlimited custom wager bet scaling with jackpot and double."""
    rewards_service.add_points(1001, 1000, "START")

    # Wager 200 pts with JACKPOT (3x profit = 4x payout)
    res_jp = rewards_service.play_bet(1001, wager=200, fixed_outcome=BetOutcome.JACKPOT)
    assert res_jp.wager == 200
    assert res_jp.points_delta == 600
    assert res_jp.total_payout == 800
    assert rewards_service.get_balance(1001) == 1600

    # Wager 100 pts with DOUBLE (1x profit = 2x payout)
    res_db = rewards_service.play_bet(1001, wager=100, fixed_outcome=BetOutcome.DOUBLE)
    assert res_db.points_delta == 100
    assert res_db.total_payout == 200
    assert rewards_service.get_balance(1001) == 1700


def test_slots_engine(rewards_service: RewardsDBService):
    """Test slots reel matching and multipliers."""
    rewards_service.add_points(1001, 1000, "START")

    # 3x Diamonds (10x multiplier)
    res_trip = rewards_service.play_slots(1001, wager=100, fixed_reels=["💎", "💎", "💎"])
    assert res_trip.multiplier == 10.0
    assert res_trip.points_won == 1000
    assert res_trip.points_delta == 900
    assert rewards_service.get_balance(1001) == 1900

    # 2x Cherries (0.5x multiplier)
    res_pair = rewards_service.play_slots(1001, wager=100, fixed_reels=["🍒", "🍒", "🍋"])
    assert res_pair.multiplier == 0.5
    assert res_pair.points_won == 50
    assert res_pair.points_delta == -50
    assert rewards_service.get_balance(1001) == 1850

    # No match (0x multiplier)
    res_bust = rewards_service.play_slots(1001, wager=100, fixed_reels=["🍒", "🍋", "🍇"])
    assert res_bust.multiplier == 0.0
    assert res_bust.points_won == 0
    assert res_bust.points_delta == -100
    assert rewards_service.get_balance(1001) == 1750


def test_coinflip_engine(rewards_service: RewardsDBService):
    """Test 50/50 coinflip win and loss."""
    rewards_service.add_points(1001, 1000, "START")

    # Correct guess
    res_win = rewards_service.play_coinflip(1001, choice="heads", wager=100, fixed_flip="heads")
    assert res_win.won is True
    assert res_win.points_delta == 100
    assert rewards_service.get_balance(1001) == 1100

    # Incorrect guess
    res_loss = rewards_service.play_coinflip(1001, choice="heads", wager=100, fixed_flip="tails")
    assert res_loss.won is False
    assert res_loss.points_delta == -100
    assert rewards_service.get_balance(1001) == 1000


def test_blackjack_engine(rewards_service: RewardsDBService):
    """Test blackjack gameplay: starting hand, hit, stand, and natural 21."""
    rewards_service.add_points(1001, 1000, "START")

    # 1. Natural 21 Blackjack (A + K vs 10 + 7)
    p_cards = [BlackjackCard("♠️", "A", 11), BlackjackCard("♥️", "K", 10)]
    d_cards = [BlackjackCard("♦️", "10", 10), BlackjackCard("♣️", "7", 7)]
    game_nat = rewards_service.start_blackjack(1001, wager=100, fixed_player_cards=p_cards, fixed_dealer_cards=d_cards)
    assert game_nat.status == "BLACKJACK"
    # 3:2 payout = +150 pts profit (total return 250 pts). Balance: 1000 - 100 + 250 = 1150
    assert rewards_service.get_balance(1001) == 1150

    # 2. Hit and Stand win (Player 10+6+4=20 vs Dealer 10+7=17)
    p_start = [BlackjackCard("♠️", "10", 10), BlackjackCard("♥️", "6", 6)]
    d_start = [BlackjackCard("♦️", "10", 10), BlackjackCard("♣️", "7", 7)]
    game_play = rewards_service.start_blackjack(1001, wager=100, fixed_player_cards=p_start, fixed_dealer_cards=d_start)
    assert game_play.status == "IN_PROGRESS"

    # Hit 4 -> 20
    game_hit = rewards_service.hit_blackjack(1001, fixed_card=BlackjackCard("♣️", "4", 4))
    assert game_hit.status == "IN_PROGRESS"

    # Stand -> Dealer 17 stands -> Player wins!
    game_stand = rewards_service.stand_blackjack(1001)
    assert game_stand.status == "PLAYER_WIN"
    # Balance: 1150 - 100 + 200 = 1250
    assert rewards_service.get_balance(1001) == 1250


def test_highlow_engine(rewards_service: RewardsDBService):
    """Test high-low card guessing, streak progression, and cashout."""
    rewards_service.add_points(1001, 1000, "START")

    # Start with 5 of Hearts
    game = rewards_service.start_highlow(1001, wager=100, fixed_card=BlackjackCard("♥️", "5", 5))
    assert game.status == "IN_PROGRESS"
    assert rewards_service.get_balance(1001) == 900

    # Guess Higher -> 9 of Spades (Correct!)
    game_g1 = rewards_service.guess_highlow(1001, guess="higher", fixed_next_card=BlackjackCard("♠️", "9", 9))
    assert game_g1.streak == 1
    assert game_g1.current_multiplier == 1.3

    # Guess Lower -> 3 of Diamonds (Correct!)
    game_g2 = rewards_service.guess_highlow(1001, guess="lower", fixed_next_card=BlackjackCard("♦️", "3", 3))
    assert game_g2.streak == 2
    assert game_g2.current_multiplier == 1.8

    # Cash out at 1.8x (100 * 1.8 = 180 pts payout)
    game_cash = rewards_service.cashout_highlow(1001)
    assert game_cash.status == "CASHED_OUT"
    assert game_cash.points_delta == 80
    # Balance: 900 + 180 = 1080
    assert rewards_service.get_balance(1001) == 1080


def test_work_and_scavenge_cooldowns(rewards_service: RewardsDBService):
    """Test work shift and campus scavenge cooldown enforcement."""
    rewards_service.add_points(1001, 0, "START")
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    # 1. Work shift
    res_work = rewards_service.execute_work(1001, now=now, fixed_job_index=0)
    assert res_work.points_earned >= 15
    assert rewards_service.get_balance(1001) == res_work.points_earned

    # Repeat work 10 mins later -> Cooldown error
    with pytest.raises(RewardsError):
        rewards_service.execute_work(1001, now=now + timedelta(minutes=10))

    # 2. Scavenge
    res_scav = rewards_service.execute_scavenge(1001, now=now, fixed_location_index=0)
    assert res_scav.points_earned >= 5
    bal_after_scav = rewards_service.get_balance(1001)

    # Repeat scavenge 5 mins later -> Cooldown error
    with pytest.raises(RewardsError):
        rewards_service.execute_scavenge(1001, now=now + timedelta(minutes=5))

    # Scavenge 31 mins later -> Success
    res_scav2 = rewards_service.execute_scavenge(1001, now=now + timedelta(minutes=31), fixed_location_index=0)
    assert rewards_service.get_balance(1001) == bal_after_scav + res_scav2.points_earned


def test_duel_resolution(rewards_service: RewardsDBService):
    """Test 1v1 PvP dice wager duels."""
    rewards_service.add_points(1001, 500, "START")
    rewards_service.add_points(1002, 500, "START")

    # Challenger (1001) rolls 85, Target (1002) rolls 40 -> Challenger wins 195 pts pot (5% server rake)
    duel_res = rewards_service.resolve_duel(1001, 1002, wager=100, fixed_c_roll=85, fixed_t_roll=40)
    assert duel_res.winner_id == 1001
    assert duel_res.pot_won == 195
    assert rewards_service.get_balance(1001) == 595
    assert rewards_service.get_balance(1002) == 400
    assert rewards_service.get_profile(1001).duel_wins == 1
    assert rewards_service.get_profile(1002).duel_losses == 1


def test_bounty_placement_and_claim_on_duel_win(rewards_service: RewardsDBService):
    """Test placing a bounty and claiming it upon winning a duel against the target."""
    rewards_service.add_points(1001, 500, "START")
    rewards_service.add_points(1002, 500, "START")
    rewards_service.add_points(1003, 500, "START")

    # User 1003 places 150 pts bounty on User 1002
    b_res = rewards_service.place_bounty(1003, 1002, 150)
    assert b_res["total_pool"] == 150
    assert rewards_service.get_balance(1003) == 350

    # Check active bounty board
    board = rewards_service.get_bounty_board()
    assert len(board) == 1
    assert board[0]["target_id"] == 1002
    assert board[0]["total_bounty"] == 150

    # User 1001 duels 1002 and wins!
    duel_res = rewards_service.resolve_duel(1001, 1002, wager=100, fixed_c_roll=99, fixed_t_roll=12)
    assert duel_res.winner_id == 1001
    assert duel_res.bounty_won == 150
    # Winner receives 195 pot + 150 bounty = 345 pts gain. Starting 500 - 100 + 345 = 745
    assert rewards_service.get_balance(1001) == 745
    assert rewards_service.get_profile(1001).bounties_claimed == 1

    # Bounty is now cleared
    assert len(rewards_service.get_bounty_board()) == 0


def test_rps_duel_game_logic(rewards_service: RewardsDBService):
    """Test Rock-Paper-Scissors clash resolution."""
    rewards_service.add_points(1001, 300, "START")
    rewards_service.add_points(1002, 300, "START")

    # Rock beats Scissors
    res_rock = rewards_service.resolve_rps_duel(1001, 1002, "rock", "scissors", wager=50)
    assert res_rock.winner_id == 1001
    assert res_rock.pot_won == 100
    assert rewards_service.get_balance(1001) == 350
    assert rewards_service.get_balance(1002) == 250

    # Tie refunds wagers
    res_tie = rewards_service.resolve_rps_duel(1001, 1002, "paper", "paper", wager=50)
    assert res_tie.is_tie is True
    assert rewards_service.get_balance(1001) == 350
    assert rewards_service.get_balance(1002) == 250


def test_roulette_duel_game_logic(rewards_service: RewardsDBService):
    """Test Uno Russian Roulette chamber mechanics."""
    rewards_service.add_points(1001, 400, "START")
    rewards_service.add_points(1002, 400, "START")

    game = rewards_service.start_roulette_game(1001, 1002, wager=100)
    assert len(game.chamber) == 6
    assert sum(game.chamber) == 1  # Exactly 1 bomb

    # Manually place bomb in slot 1 (second draw)
    game.chamber = [False, True, False, False, False, False]

    # Turn 1: Player 1001 pulls trigger -> Safe (slot 0)
    step1 = rewards_service.pull_roulette_trigger(1001, 1002)
    assert step1.is_over is False
    assert step1.current_turn_id == 1002

    # Turn 2: Player 1002 pulls trigger -> Bomb explodes (slot 1)!
    step2 = rewards_service.pull_roulette_trigger(1002, 1001)
    assert step2.is_over is True
    assert step2.exploded is True
    assert step2.winner_id == 1001
    assert step2.loser_id == 1002
    assert rewards_service.get_balance(1001) == 500  # 400 - 100 + 200 = 500
    assert rewards_service.get_balance(1002) == 300


def test_rpg_duel_combat_logic(rewards_service: RewardsDBService):
    """Test Turn-Based RPG combat rounds, damage, and parries."""
    rewards_service.add_points(1001, 500, "START")
    rewards_service.add_points(1002, 500, "START")

    game = rewards_service.start_rpg_game(1001, 1002, wager=100)
    assert game.c_hp == 100
    assert game.t_hp == 100

    # Round 1: Challenger strikes, Target blocks
    rewards_service.submit_rpg_action(1001, 1002, "strike")
    res_r1 = rewards_service.submit_rpg_action(1002, 1001, "block")
    assert res_r1.turn_number == 2
    # Target parried: challenger took 10 counter DMG, target took reduced DMG
    assert res_r1.c_hp == 90
    assert res_r1.t_hp < 100


def test_bank_deposit_and_withdraw(rewards_service: RewardsDBService):
    """Test depositing and withdrawing from protected campus bank."""
    rewards_service.add_points(1001, 1000, "START")

    # Deposit 600 pts
    dep_res = rewards_service.bank_deposit(1001, 600)
    assert dep_res["new_wallet"] == 400
    assert dep_res["new_bank"] == 600

    # Withdraw 250 pts
    wd_res = rewards_service.bank_withdraw(1001, 250)
    assert wd_res["new_wallet"] == 650
    assert wd_res["new_bank"] == 350
    assert rewards_service.get_profile(1001).bank_points == 350


