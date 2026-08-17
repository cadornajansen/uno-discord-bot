import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import io
import logging
from pathlib import Path
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


class RewardsError(Exception):
    """Base exception for rewards and economy operations."""
    pass


class DailyAlreadyClaimedError(RewardsError):
    """Raised when user has already claimed their daily reward today."""
    def __init__(self, message: str, next_claim_time: Optional[datetime] = None):
        super().__init__(message)
        self.next_claim_time = next_claim_time


class InsufficientPointsError(RewardsError):
    """Raised when user lacks the points required for an action."""
    pass


class ShieldActiveError(RewardsError):
    """Raised when an action is blocked by an active Immunity Shield."""
    def __init__(self, message: str, shield_until: Optional[datetime] = None):
        super().__init__(message)
        self.shield_until = shield_until


class MaxBetsReachedError(RewardsError):
    """Raised when user reaches their daily gambling limit (3 bets/day)."""
    pass


from enum import Enum
import random


class ItemNotFoundError(RewardsError):
    """Raised when user attempts to consume an item they do not own."""
    pass


class BetOutcome(str, Enum):
    DOUBLE = "DOUBLE"
    SKILL_DROP = "SKILL_DROP"
    REFUND = "REFUND"
    BUST = "BUST"


ITEM_DEFINITIONS = {
    "pickpocket": {
        "name": "🦹 Pickpocket Card",
        "description": "Allows you to attempt to steal 10%–15% points from a classmate with `/steal`.",
        "usable": False,
    },
    "shield_1w": {
        "name": "🛡️ 1-Week Immunity Shield",
        "description": "Protects your wallet completely from all `/steal` attempts for 7 days.",
        "usable": True,
    },
    "double_daily": {
        "name": "⚡ 2x Daily Booster Card",
        "description": "Doubles the points awarded on your next `/daily` claim.",
        "usable": True,
    },
    "streak_bandage": {
        "name": "🩹 Streak Bandage",
        "description": "Repairs a broken `/daily` streak back to its previous number.",
        "usable": True,
    },
}


SHOP_CATALOG = {
    "pickpocket": {
        "name": "🦹 Pickpocket Card",
        "cost": 100,
        "category": "consumable",
        "description": "Consumable skill card that lets you attempt to steal 10%–15% points with `/steal`.",
    },
    "shield_1w": {
        "name": "🛡️ 1-Week Immunity Shield",
        "cost": 150,
        "category": "consumable",
        "description": "Consumable item that protects your points from `/steal` attempts for 7 days.",
    },
    "double_daily": {
        "name": "⚡ 2x Daily Booster Card",
        "cost": 120,
        "category": "consumable",
        "description": "Doubles the points earned on your next `/daily` attendance claim.",
    },
    "coffee": {
        "name": "☕ Intramuros Coffee Treat",
        "cost": 1200,
        "category": "physical",
        "description": "₱50–₱80 Iced Coffee / drink treat around PLM / Intramuros (7-Eleven / Lawson).",
    },
    "gcash_100": {
        "name": "💳 GCash Gift Card ₱100",
        "cost": 2200,
        "category": "physical",
        "description": "₱100 Direct GCash transfer to your Philippine mobile number.",
    },
    "printing_1m": {
        "name": "🖨️ Free Printing Service (1 Month)",
        "cost": 2800,
        "category": "physical",
        "description": "Free academic reviewer / project paper printing service for 30 days.",
    },
    "nitro_1m": {
        "name": "🚀 1 Month Discord Nitro",
        "cost": 5500,
        "category": "physical",
        "description": "1-Month Discord Nitro subscription gift code.",
    },
}


@dataclass(frozen=True)
class BetResult:
    outcome: BetOutcome
    points_delta: int
    new_balance: int
    bets_remaining: int
    reward_item_id: Optional[str] = None
    reward_item_name: Optional[str] = None


@dataclass(frozen=True)
class StealResult:
    success: bool
    blocked_by_shield: bool
    points_stolen: int
    fine_paid: int
    thief_new_balance: int
    target_new_balance: int


@dataclass(frozen=True)
class UseItemResult:
    item_id: str
    item_name: str
    description: str
    shield_until: Optional[datetime] = None


@dataclass(frozen=True)
class UserRecord:
    user_id: int
    points: int
    lifetime_points: int
    daily_streak: int
    last_daily_claim: Optional[str]
    daily_bets_count: int
    last_bet_date: Optional[str]
    shield_until: Optional[str]
    created_at: str


@dataclass(frozen=True)
class DailyClaimResult:
    points_awarded: int
    base_points: int
    streak_bonus: int
    streak: int
    new_balance: int
    milestone_3k_unlocked: bool


@dataclass(frozen=True)
class UserLeaderboardEntry:
    rank: int
    user_id: int
    points: int
    daily_streak: int
    lifetime_points: int


@dataclass(frozen=True)
class UserProfile:
    user_id: int
    points: int
    lifetime_points: int
    daily_streak: int
    rank: int
    has_shield: bool
    shield_until: Optional[datetime]
    inventory: dict[str, int]
    badges: list[str]


class RewardsDBService:
    """Thread-safe SQLite database service managing student economy, streaks, and inventory."""

    def __init__(self, db_path: Path | str = "data/rewards.db"):
        self.db_path = Path(db_path)
        self._is_memory = str(self.db_path) == ":memory:"
        self._mem_conn: Optional[sqlite3.Connection] = None

        if self._is_memory:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory and self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    points INTEGER DEFAULT 0,
                    lifetime_points INTEGER DEFAULT 0,
                    daily_streak INTEGER DEFAULT 0,
                    last_daily_claim TEXT,
                    daily_bets_count INTEGER DEFAULT 0,
                    last_bet_date TEXT,
                    shield_until TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    user_id INTEGER,
                    item_id TEXT,
                    quantity INTEGER DEFAULT 1,
                    PRIMARY KEY (user_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    action_type TEXT,
                    description TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    item_name TEXT,
                    points_spent INTEGER,
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def get_or_create_user(self, user_id: int) -> UserRecord:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (user_id, points, lifetime_points, daily_streak) VALUES (?, 0, 0, 0)",
                    (user_id,),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

            return UserRecord(
                user_id=row["user_id"],
                points=row["points"],
                lifetime_points=row["lifetime_points"],
                daily_streak=row["daily_streak"],
                last_daily_claim=row["last_daily_claim"],
                daily_bets_count=row["daily_bets_count"],
                last_bet_date=row["last_bet_date"],
                shield_until=row["shield_until"],
                created_at=row["created_at"],
            )

    def get_balance(self, user_id: int) -> int:
        user = self.get_or_create_user(user_id)
        return user.points

    def claim_daily(self, user_id: int, now: Optional[datetime] = None) -> DailyClaimResult:
        """Process daily point claim with streak multipliers and 3k milestone detection."""
        current_time = now or datetime.now(timezone.utc)
        today_str = current_time.strftime("%Y-%m-%d")
        yesterday_str = (current_time - timedelta(days=1)).strftime("%Y-%m-%d")

        user = self.get_or_create_user(user_id)

        if user.last_daily_claim == today_str:
            # Calculate next midnight claim time
            tomorrow = (current_time + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            raise DailyAlreadyClaimedError(
                "You have already claimed your daily reward today! Come back tomorrow.",
                next_claim_time=tomorrow,
            )

        # Streak calculation
        if user.last_daily_claim == yesterday_str:
            new_streak = user.daily_streak + 1
        else:
            new_streak = 1

        base_points = 30
        streak_bonus = min((new_streak - 1) * 5, 35)
        total_points = base_points + streak_bonus

        new_balance = user.points + total_points
        new_lifetime = user.lifetime_points + total_points
        milestone_unlocked = (user.lifetime_points < 3000 <= new_lifetime)

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = points + ?,
                    lifetime_points = lifetime_points + ?,
                    daily_streak = ?,
                    last_daily_claim = ?
                WHERE user_id = ?
                """,
                (total_points, total_points, new_streak, today_str, user_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, 'DAILY', ?)
                """,
                (user_id, total_points, f"Daily Claim (Streak: {new_streak}d, Bonus: +{streak_bonus}pts)"),
            )
            conn.commit()

        return DailyClaimResult(
            points_awarded=total_points,
            base_points=base_points,
            streak_bonus=streak_bonus,
            streak=new_streak,
            new_balance=new_balance,
            milestone_3k_unlocked=milestone_unlocked,
        )

    def add_points(self, user_id: int, amount: int, action_type: str, description: str = "") -> int:
        """Add points to user balance and lifetime total."""
        self.get_or_create_user(user_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = points + ?,
                    lifetime_points = lifetime_points + ?
                WHERE user_id = ?
                """,
                (amount, amount if amount > 0 else 0, user_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, amount, action_type, description),
            )
            conn.commit()
            row = conn.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row["points"]

    def deduct_points(self, user_id: int, amount: int, action_type: str, description: str = "") -> int:
        """Deduct points from user balance."""
        user = self.get_or_create_user(user_id)
        if user.points < amount:
            raise InsufficientPointsError(
                f"Insufficient points. You have {user.points} pts, but need {amount} pts."
            )

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = points - ? WHERE user_id = ?",
                (amount, user_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, -amount, action_type, description),
            )
            conn.commit()
            row = conn.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row["points"]

    def has_active_shield(self, user_id: int, now: Optional[datetime] = None) -> bool:
        """Check if user has an active Immunity Shield."""
        current_time = now or datetime.now(timezone.utc)
        user = self.get_or_create_user(user_id)
        if not user.shield_until:
            return False

        try:
            shield_dt = datetime.fromisoformat(user.shield_until)
            if shield_dt.tzinfo is None:
                shield_dt = shield_dt.replace(tzinfo=timezone.utc)
            return shield_dt > current_time
        except ValueError:
            return False

    def activate_shield(self, user_id: int, duration_days: int = 7, now: Optional[datetime] = None) -> datetime:
        """Activate Immunity Shield for specified duration (default 7 days)."""
        current_time = now or datetime.now(timezone.utc)
        shield_until = current_time + timedelta(days=duration_days)
        iso_str = shield_until.isoformat()

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET shield_until = ? WHERE user_id = ?",
                (iso_str, user_id),
            )
            conn.commit()
        return shield_until

    def add_item(self, user_id: int, item_id: str, quantity: int = 1) -> None:
        self.get_or_create_user(user_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO inventory (user_id, item_id, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + ?
                """,
                (user_id, item_id, quantity, quantity),
            )
            conn.commit()

    def remove_item(self, user_id: int, item_id: str, quantity: int = 1) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?",
                (user_id, item_id),
            ).fetchone()
            if not row or row["quantity"] < quantity:
                raise ItemNotFoundError(f"You do not have enough of item '{item_id}'.")

            new_qty = row["quantity"] - quantity
            if new_qty > 0:
                conn.execute(
                    "UPDATE inventory SET quantity = ? WHERE user_id = ? AND item_id = ?",
                    (new_qty, user_id, item_id),
                )
            else:
                conn.execute(
                    "DELETE FROM inventory WHERE user_id = ? AND item_id = ?",
                    (user_id, item_id),
                )
            conn.commit()
            return True

    def get_inventory(self, user_id: int) -> dict[str, int]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT item_id, quantity FROM inventory WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return {row["item_id"]: row["quantity"] for row in rows}

    def get_leaderboard(self, limit: int = 10, offset: int = 0) -> tuple[list[UserLeaderboardEntry], int]:
        """Fetch sorted leaderboard entries with pagination."""
        with self._get_connection() as conn:
            total_count = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()["count"]
            rows = conn.execute(
                """
                SELECT user_id, points, daily_streak, lifetime_points
                FROM users
                ORDER BY points DESC, lifetime_points DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            entries = [
                UserLeaderboardEntry(
                    rank=offset + i + 1,
                    user_id=r["user_id"],
                    points=r["points"],
                    daily_streak=r["daily_streak"],
                    lifetime_points=r["lifetime_points"],
                )
                for i, r in enumerate(rows)
            ]
            return entries, total_count

    def get_profile(self, user_id: int, now: Optional[datetime] = None) -> UserProfile:
        """Fetch comprehensive user profile including rank, badges, and inventory."""
        current_time = now or datetime.now(timezone.utc)
        user = self.get_or_create_user(user_id)

        # Compute rank
        with self._get_connection() as conn:
            rank_row = conn.execute(
                "SELECT COUNT(*) + 1 as rank FROM users WHERE points > ?",
                (user.points,),
            ).fetchone()
            user_rank = rank_row["rank"]

        # Parse shield
        has_shield = False
        shield_dt = None
        if user.shield_until:
            try:
                s_dt = datetime.fromisoformat(user.shield_until)
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=timezone.utc)
                if s_dt > current_time:
                    has_shield = True
                    shield_dt = s_dt
            except ValueError:
                pass

        # Badges
        badges = []
        if user.lifetime_points >= 3000:
            badges.append("🍫 Exam Survivor")
        if user.daily_streak >= 7:
            badges.append("🔥 7-Day Streak")
        if user_rank == 1:
            badges.append("👑 Top 1 Scholar")
        elif user_rank <= 3:
            badges.append("🌟 Top 3 Elite")

        inv = self.get_inventory(user_id)

        return UserProfile(
            user_id=user.user_id,
            points=user.points,
            lifetime_points=user.lifetime_points,
            daily_streak=user.daily_streak,
            rank=user_rank,
            has_shield=has_shield,
            shield_until=shield_dt,
            inventory=inv,
            badges=badges,
        )

    def record_redemption(self, user_id: int, item_id: str) -> dict:
        """Deduct points and log a prize redemption or consumable purchase."""
        if item_id not in SHOP_CATALOG:
            raise RewardsError(f"Item '{item_id}' is not available in the shop.")

        item = SHOP_CATALOG[item_id]
        points_cost = item["cost"]
        item_name = item["name"]

        # Deduct points
        self.deduct_points(user_id, points_cost, "SHOP_PURCHASE", f"Purchased {item_name}")

        # If consumable item, automatically grant to inventory
        if item.get("category") == "consumable":
            self.add_item(user_id, item_id, 1)
            status = "DELIVERED"
        else:
            status = "PENDING"

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO redemptions (user_id, item_name, points_spent, status)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, item_name, points_cost, status),
            )
            conn.commit()
            redemption_id = cursor.lastrowid

        return {
            "id": redemption_id,
            "user_id": user_id,
            "item_id": item_id,
            "item_name": item_name,
            "points_spent": points_cost,
            "category": item.get("category"),
            "status": status,
        }

    def update_redemption_status(self, redemption_id: int, status: str) -> dict:
        """Approve or reject a redemption. If rejected, automatically refunds points."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM redemptions WHERE id = ?", (redemption_id,)
            ).fetchone()
            if not row:
                raise RewardsError(f"Redemption ID #{redemption_id} not found.")

            user_id = row["user_id"]
            points_spent = row["points_spent"]
            item_name = row["item_name"]
            prev_status = row["status"]

            if prev_status != "PENDING" and status in ("APPROVED", "REJECTED"):
                raise RewardsError(f"Redemption #{redemption_id} is already {prev_status}.")

            conn.execute(
                "UPDATE redemptions SET status = ? WHERE id = ?",
                (status, redemption_id),
            )
            conn.commit()

        # If rejected, refund points to user
        if status == "REJECTED":
            self.add_points(user_id, points_spent, "REDEEM_REFUND", f"Refund for rejected {item_name}")

        return {
            "id": redemption_id,
            "user_id": user_id,
            "item_name": item_name,
            "points_spent": points_spent,
            "status": status,
        }

    def get_user_transactions(self, user_id: int, limit: int = 5) -> list[dict]:
        """Fetch latest transactions for a user."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT amount, action_type, description, created_at
                FROM transactions
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def play_bet(
        self,
        user_id: int,
        now: Optional[datetime] = None,
        fixed_outcome: Optional[BetOutcome] = None,
        fixed_skill: Optional[str] = None,
    ) -> BetResult:
        """Place a 50 pt bet (max 3/day). Outcomes: Double (25%), Skill Drop (25%), Refund (15%), Bust (35%)."""
        BET_COST = 50
        MAX_BETS = 3
        current_time = now or datetime.now(timezone.utc)
        today_str = current_time.strftime("%Y-%m-%d")

        user = self.get_or_create_user(user_id)
        if user.points < BET_COST:
            raise InsufficientPointsError(
                f"You need at least {BET_COST} pts to place a bet! You have {user.points:,} pts."
            )

        if user.last_bet_date == today_str and user.daily_bets_count >= MAX_BETS:
            raise MaxBetsReachedError("You've used all 3 of your bets today! Come back tomorrow.")

        new_bets_count = (user.daily_bets_count + 1) if user.last_bet_date == today_str else 1
        bets_remaining = MAX_BETS - new_bets_count

        # Determine outcome
        if fixed_outcome is not None:
            outcome = fixed_outcome
        else:
            roll = random.random()
            if roll < 0.25:
                outcome = BetOutcome.DOUBLE
            elif roll < 0.50:
                outcome = BetOutcome.SKILL_DROP
            elif roll < 0.65:
                outcome = BetOutcome.REFUND
            else:
                outcome = BetOutcome.BUST

        points_delta = 0
        reward_item_id = None
        reward_item_name = None

        if outcome == BetOutcome.DOUBLE:
            points_delta = 50  # Won 100 - 50 cost = +50 net
            new_balance = user.points + points_delta
            new_lifetime = user.lifetime_points + 50
        elif outcome == BetOutcome.SKILL_DROP:
            points_delta = -50  # Deducted 50 cost
            new_balance = user.points - 50
            new_lifetime = user.lifetime_points
            possible_skills = ["pickpocket", "shield_1w", "double_daily"]
            reward_item_id = fixed_skill if fixed_skill in possible_skills else random.choice(possible_skills)
            reward_item_name = ITEM_DEFINITIONS[reward_item_id]["name"]
            self.add_item(user_id, reward_item_id, 1)
        elif outcome == BetOutcome.REFUND:
            points_delta = 0
            new_balance = user.points
            new_lifetime = user.lifetime_points
        else:  # BUST
            points_delta = -50
            new_balance = user.points - 50
            new_lifetime = user.lifetime_points

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = ?,
                    lifetime_points = ?,
                    daily_bets_count = ?,
                    last_bet_date = ?
                WHERE user_id = ?
                """,
                (new_balance, new_lifetime, new_bets_count, today_str, user_id),
            )
            action_desc = f"Bet Outcome: {outcome.value} ({'+' if points_delta > 0 else ''}{points_delta} pts)"
            if reward_item_name:
                action_desc += f" + Won {reward_item_name}"
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, 'BET', ?)
                """,
                (user_id, points_delta, action_desc),
            )
            conn.commit()

        return BetResult(
            outcome=outcome,
            points_delta=points_delta,
            new_balance=new_balance,
            bets_remaining=bets_remaining,
            reward_item_id=reward_item_id,
            reward_item_name=reward_item_name,
        )

    def execute_steal(
        self,
        thief_id: int,
        target_id: int,
        now: Optional[datetime] = None,
        fixed_success: Optional[bool] = None,
        fixed_amount: Optional[int] = None,
    ) -> StealResult:
        """Attempt to steal 10-15% of target points using a Pickpocket Card (checked against target shield)."""
        if thief_id == target_id:
            raise RewardsError("You cannot pickpocket yourself!")

        target = self.get_or_create_user(target_id)
        if target.points < 20:
            raise RewardsError(f"That classmate only has {target.points} pts. They're too broke to steal from (< 20 pts)!")

        # Consume pickpocket card
        self.remove_item(thief_id, "pickpocket", 1)

        # Check target immunity shield
        if self.has_active_shield(target_id, now=now):
            thief = self.get_or_create_user(thief_id)
            return StealResult(
                success=False,
                blocked_by_shield=True,
                points_stolen=0,
                fine_paid=0,
                thief_new_balance=thief.points,
                target_new_balance=target.points,
            )

        # Roll steal success (65% success, 35% caught)
        is_success = fixed_success if fixed_success is not None else (random.random() < 0.65)

        if is_success:
            pct = random.uniform(0.10, 0.15)
            calc_stolen = int(target.points * pct)
            stolen = fixed_amount if fixed_amount is not None else min(80, max(10, calc_stolen))
            stolen = min(stolen, target.points)

            target_new = self.deduct_points(target_id, stolen, "STEAL_VICTIM", f"Stolen by user {thief_id}")
            thief_new = self.add_points(thief_id, stolen, "STEAL_SUCCESS", f"Stolen from user {target_id}")

            return StealResult(
                success=True,
                blocked_by_shield=False,
                points_stolen=stolen,
                fine_paid=0,
                thief_new_balance=thief_new,
                target_new_balance=target_new,
            )
        else:
            # Thief caught red-handed!
            thief = self.get_or_create_user(thief_id)
            fine = min(30, thief.points)
            if fine > 0:
                thief_new = self.deduct_points(thief_id, fine, "STEAL_FINE", f"Caught stealing from user {target_id}")
                target_new = self.add_points(target_id, fine, "STEAL_COMPENSATION", f"Compensation from caught thief {thief_id}")
            else:
                thief_new = thief.points
                target_new = target.points

            return StealResult(
                success=False,
                blocked_by_shield=False,
                points_stolen=0,
                fine_paid=fine,
                thief_new_balance=thief_new,
                target_new_balance=target_new,
            )

    def use_item(self, user_id: int, item_id: str, now: Optional[datetime] = None) -> UseItemResult:
        """Consume and activate an item from user's inventory."""
        if item_id not in ITEM_DEFINITIONS or not ITEM_DEFINITIONS[item_id]["usable"]:
            raise RewardsError(f"Item '{item_id}' cannot be activated directly.")

        self.remove_item(user_id, item_id, 1)

        shield_until = None
        if item_id == "shield_1w":
            shield_until = self.activate_shield(user_id, duration_days=7, now=now)
            desc = f"Activated 7-Day Immunity Shield! Protected until <t:{int(shield_until.timestamp())}:f>."
        elif item_id == "double_daily":
            desc = "Activated 2x Daily Booster! Your next `/daily` claim will reward double points."
        else:
            desc = f"Activated {ITEM_DEFINITIONS[item_id]['name']}!"

        return UseItemResult(
            item_id=item_id,
            item_name=ITEM_DEFINITIONS[item_id]["name"],
            description=desc,
            shield_until=shield_until,
        )

    def export_csv(self) -> str:
        """Export users and points to a clean CSV string."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT user_id, points, lifetime_points, daily_streak, last_daily_claim, shield_until, created_at
                FROM users
                ORDER BY points DESC
                """
            ).fetchall()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["user_id", "points", "lifetime_points", "daily_streak", "last_daily_claim", "shield_until", "created_at"])
            for r in rows:
                writer.writerow([r["user_id"], r["points"], r["lifetime_points"], r["daily_streak"], r["last_daily_claim"], r["shield_until"], r["created_at"]])
            return output.getvalue()
