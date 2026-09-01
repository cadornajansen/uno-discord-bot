from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from typing import Any, Optional

from bot.services.rewards_db import RewardsDBService, RewardsError


RAID_STAGES: tuple[dict[str, str], ...] = (
    {
        "prompt": "A Python loop never stops because its condition never becomes false. What kind of bug is this?",
        "answer": "infinite loop",
        "hint": "It describes a loop that runs forever.",
    },
    {
        "prompt": "Arrange these steps by replying with the letters: A) test, B) design, C) implement.",
        "answer": "bca",
        "hint": "Plan before coding, then verify the result.",
    },
    {
        "prompt": "What value does `len({1, 1, 2, 3})` return in Python?",
        "answer": "3",
        "hint": "A set keeps unique values.",
    },
)

ESCAPE_ROOMS: tuple[dict[str, str], ...] = (
    {
        "prompt": "Room 1 — Repair the condition: `while x ___ 10:` should run while x is below 10.",
        "answer": "<",
        "hint": "Use the less-than comparison operator.",
    },
    {
        "prompt": "Room 2 — Decode binary `01000001` as an ASCII character.",
        "answer": "a",
        "hint": "The decimal value is 65.",
    },
    {
        "prompt": "Room 3 — Which HTTP status code means Not Found?",
        "answer": "404",
        "hint": "It is the web's most familiar client error.",
    },
)

STARTUP_ACTIONS: dict[str, tuple[int, int, int, int]] = {
    "build": (0, 18, 0, 5),
    "research": (-5, 8, 14, 8),
    "market": (-10, 2, 0, 18),
    "stabilize": (-5, 5, 4, 16),
}

REVIEWABLE_ACTIONS = {
    "GIVE_SENT",
    "STEAL_VICTIM",
    "STEAL_FINE",
    "DUEL_WAGER",
    "BOUNTY_PLACED",
}


@dataclass(frozen=True)
class ActivityUpdate:
    message: str
    completed: bool = False
    reward: int = 0


class CommunityGamesService:
    """Persistent mechanics for raids, escape rooms, startups, reviews, and pulses."""

    def __init__(self, rewards: RewardsDBService):
        self.rewards = rewards
        self._lock = threading.RLock()
        self._init_tables()

    def _conn(self):
        return self.rewards._get_connection()

    @staticmethod
    def _now(now: Optional[datetime] = None) -> datetime:
        current = now or datetime.now(timezone.utc)
        return current if current.tzinfo else current.replace(tzinfo=timezone.utc)

    @staticmethod
    def _clean_answer(value: str) -> str:
        return "".join(value.casefold().strip().split())

    def _init_tables(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    activity_type TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    stage INTEGER NOT NULL DEFAULT 0,
                    hints_used INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL DEFAULT '{}',
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_activity_active
                    ON activity_sessions(server_id, activity_type, status);
                CREATE TABLE IF NOT EXISTS activity_participants (
                    session_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    correct_answers INTEGER NOT NULL DEFAULT 0,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS activity_answers (
                    session_id INTEGER NOT NULL,
                    stage INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    answer TEXT NOT NULL,
                    is_correct INTEGER NOT NULL,
                    answered_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, stage, user_id)
                );
                CREATE TABLE IF NOT EXISTS startup_projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phase INTEGER NOT NULL DEFAULT 1,
                    budget INTEGER NOT NULL DEFAULT 100,
                    quality INTEGER NOT NULL DEFAULT 20,
                    research INTEGER NOT NULL DEFAULT 10,
                    reputation INTEGER NOT NULL DEFAULT 10,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS startup_contributions (
                    project_id INTEGER NOT NULL,
                    phase INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, phase, user_id)
                );
                CREATE TABLE IF NOT EXISTS review_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    filer_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    transaction_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    response TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    resolution TEXT,
                    resolved_by INTEGER,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
                    snapshot_key TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    net_worth INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    PRIMARY KEY(snapshot_key, user_id)
                );
                CREATE TABLE IF NOT EXISTS community_reward_claims (
                    reward_type TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    claim_date TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    PRIMARY KEY(reward_type, user_id, claim_date)
                );
                """
            )
            conn.commit()

    def _award_daily_activity(self, user_id: int, amount: int, reward_type: str, description: str) -> bool:
        now = self._now()
        claim_date = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO community_reward_claims (reward_type, user_id, claim_date, claimed_at) VALUES (?, ?, ?, ?)",
                (reward_type, user_id, claim_date, now.isoformat()),
            )
            conn.commit()
        if cursor.rowcount == 0:
            return False
        self.rewards.add_points(user_id, amount, reward_type, description)
        return True

    def _active_session(self, server_id: int, activity_type: str) -> Optional[dict[str, Any]]:
        now = self._now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE activity_sessions SET status = 'EXPIRED' WHERE status IN ('OPEN', 'ACTIVE') AND expires_at <= ?",
                (now,),
            )
            row = conn.execute(
                "SELECT * FROM activity_sessions WHERE server_id = ? AND activity_type = ? AND status IN ('OPEN', 'ACTIVE') ORDER BY id DESC LIMIT 1",
                (server_id, activity_type),
            ).fetchone()
            conn.commit()
            return dict(row) if row else None

    def create_activity(self, server_id: int, owner_id: int, activity_type: str) -> dict[str, Any]:
        if activity_type not in {"raid", "escape"}:
            raise RewardsError("Unknown activity type.")
        with self._lock:
            if self._active_session(server_id, activity_type):
                raise RewardsError(f"A {activity_type} session is already open in this server.")
            now = self._now()
            status = "OPEN" if activity_type == "raid" else "ACTIVE"
            duration = timedelta(minutes=10 if activity_type == "raid" else 30)
            with self._conn() as conn:
                cursor = conn.execute(
                    "INSERT INTO activity_sessions (server_id, activity_type, owner_id, status, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (server_id, activity_type, owner_id, status, (now + duration).isoformat(), now.isoformat()),
                )
                session_id = int(cursor.lastrowid)
                conn.execute(
                    "INSERT INTO activity_participants (session_id, user_id, joined_at) VALUES (?, ?, ?)",
                    (session_id, owner_id, now.isoformat()),
                )
                conn.commit()
            return self.get_activity(server_id, activity_type)

    def get_activity(self, server_id: int, activity_type: str) -> dict[str, Any]:
        session = self._active_session(server_id, activity_type)
        if not session:
            raise RewardsError(f"There is no active {activity_type} session.")
        with self._conn() as conn:
            participants = conn.execute(
                "SELECT user_id, correct_answers FROM activity_participants WHERE session_id = ? ORDER BY joined_at",
                (session["id"],),
            ).fetchall()
        session["participants"] = [dict(row) for row in participants]
        stages = RAID_STAGES if activity_type == "raid" else ESCAPE_ROOMS
        session["prompt"] = stages[min(int(session["stage"]), len(stages) - 1)]["prompt"]
        return session

    def join_activity(self, server_id: int, user_id: int, activity_type: str) -> dict[str, Any]:
        with self._lock:
            session = self.get_activity(server_id, activity_type)
            if session["status"] != "OPEN" and activity_type == "raid":
                raise RewardsError("That Study Raid has already started.")
            limit = 8 if activity_type == "raid" else 4
            if len(session["participants"]) >= limit:
                raise RewardsError(f"This {activity_type} already has {limit} players.")
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO activity_participants (session_id, user_id, joined_at) VALUES (?, ?, ?)",
                    (session["id"], user_id, self._now().isoformat()),
                )
                conn.commit()
            return self.get_activity(server_id, activity_type)

    def launch_raid(self, server_id: int, owner_id: int) -> dict[str, Any]:
        with self._lock:
            session = self.get_activity(server_id, "raid")
            if session["owner_id"] != owner_id:
                raise RewardsError("Only the raid creator can launch it.")
            if len(session["participants"]) < 2:
                raise RewardsError("A Study Raid needs at least two players.")
            with self._conn() as conn:
                conn.execute("UPDATE activity_sessions SET status = 'ACTIVE' WHERE id = ?", (session["id"],))
                conn.commit()
            return self.get_activity(server_id, "raid")

    def answer_activity(self, server_id: int, user_id: int, activity_type: str, answer: str) -> ActivityUpdate:
        with self._lock:
            session = self.get_activity(server_id, activity_type)
            if session["status"] != "ACTIVE":
                raise RewardsError(f"The {activity_type} has not started yet.")
            if user_id not in {int(p["user_id"]) for p in session["participants"]}:
                raise RewardsError(f"Join the {activity_type} before answering.")
            stages = RAID_STAGES if activity_type == "raid" else ESCAPE_ROOMS
            stage = int(session["stage"])
            expected = self._clean_answer(stages[stage]["answer"])
            correct = self._clean_answer(answer) == expected
            now = self._now().isoformat()
            with self._conn() as conn:
                try:
                    conn.execute(
                        "INSERT INTO activity_answers (session_id, stage, user_id, answer, is_correct, answered_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (session["id"], stage, user_id, answer[:200], int(correct), now),
                    )
                except Exception as exc:
                    if "UNIQUE" in str(exc).upper():
                        raise RewardsError("You already answered this stage.") from exc
                    raise
                if correct:
                    conn.execute(
                        "UPDATE activity_participants SET correct_answers = correct_answers + 1 WHERE session_id = ? AND user_id = ?",
                        (session["id"], user_id),
                    )
                correct_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM activity_answers WHERE session_id = ? AND stage = ? AND is_correct = 1",
                    (session["id"], stage),
                ).fetchone()["count"]
                participant_count = len(session["participants"])
                target = max(1, (participant_count + 1) // 2) if activity_type == "raid" else 1
                if not correct or correct_count < target:
                    conn.commit()
                    return ActivityUpdate("Correct—waiting for more teammates." if correct else "That answer did not unlock the stage.")
                next_stage = stage + 1
                if next_stage < len(stages):
                    conn.execute("UPDATE activity_sessions SET stage = ? WHERE id = ?", (next_stage, session["id"]))
                    conn.commit()
                    return ActivityUpdate(f"Stage cleared. Next: {stages[next_stage]['prompt']}")
                conn.execute("UPDATE activity_sessions SET status = 'COMPLETE' WHERE id = ?", (session["id"],))
                rewards = conn.execute(
                    "SELECT user_id, correct_answers FROM activity_participants WHERE session_id = ?",
                    (session["id"],),
                ).fetchall()
                conn.commit()

            base = 100 if activity_type == "raid" else max(100, 200 - int(session["hints_used"]) * 25)
            rewarded_count = 0
            for row in rewards:
                personal = base + (int(row["correct_answers"]) * 20 if activity_type == "raid" else 0)
                if self._award_daily_activity(
                    int(row["user_id"]),
                    personal,
                    f"{activity_type.upper()}_COMPLETE",
                    f"Completed {activity_type} session {session['id']}",
                ):
                    rewarded_count += 1
            return ActivityUpdate(
                f"{activity_type.title()} completed. {rewarded_count} player(s) received today's activity reward.",
                completed=True,
                reward=base,
            )

    def use_escape_hint(self, server_id: int, user_id: int) -> str:
        with self._lock:
            session = self.get_activity(server_id, "escape")
            if user_id not in {int(p["user_id"]) for p in session["participants"]}:
                raise RewardsError("Join the escape room before requesting a hint.")
            with self._conn() as conn:
                conn.execute("UPDATE activity_sessions SET hints_used = hints_used + 1 WHERE id = ?", (session["id"],))
                conn.commit()
            return ESCAPE_ROOMS[int(session["stage"])]["hint"]

    def start_startup(self, server_id: int, user_id: int, name: str) -> dict[str, Any]:
        guild = self.rewards.get_guild_for_user(server_id, user_id)
        if not guild:
            raise RewardsError("Join or create a guild before starting a campus startup.")
        if int(guild["owner_id"]) != user_id:
            raise RewardsError("Only the guild leader can start a project.")
        with self._lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM startup_projects WHERE guild_id = ? AND status = 'ACTIVE'",
                (guild["id"],),
            ).fetchone()
            if existing:
                raise RewardsError("Your guild already has an active startup project.")
            now = self._now().isoformat()
            cursor = conn.execute(
                "INSERT INTO startup_projects (server_id, guild_id, name, created_at) VALUES (?, ?, ?, ?)",
                (server_id, guild["id"], name.strip()[:60], now),
            )
            conn.commit()
            return self.get_startup(server_id, user_id)

    def get_startup(self, server_id: int, user_id: int) -> dict[str, Any]:
        guild = self.rewards.get_guild_for_user(server_id, user_id)
        if not guild:
            raise RewardsError("You are not in a guild.")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM startup_projects WHERE guild_id = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1",
                (guild["id"],),
            ).fetchone()
            if not row:
                raise RewardsError("Your guild has no active startup project.")
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM startup_contributions WHERE project_id = ? AND phase = ?",
                (row["id"], row["phase"]),
            ).fetchone()["count"]
        result = dict(row)
        result["contributions"] = count
        result["guild"] = guild
        return result

    def contribute_startup(self, server_id: int, user_id: int, action: str) -> dict[str, Any]:
        clean = action.casefold().strip()
        if clean not in STARTUP_ACTIONS:
            raise RewardsError("Choose build, research, market, or stabilize.")
        with self._lock:
            project = self.get_startup(server_id, user_id)
            delta = STARTUP_ACTIONS[clean]
            with self._conn() as conn:
                try:
                    conn.execute(
                        "INSERT INTO startup_contributions (project_id, phase, user_id, action, created_at) VALUES (?, ?, ?, ?, ?)",
                        (project["id"], project["phase"], user_id, clean, self._now().isoformat()),
                    )
                except Exception as exc:
                    if "UNIQUE" in str(exc).upper():
                        raise RewardsError("You already contributed during this phase.") from exc
                    raise
                conn.execute(
                    "UPDATE startup_projects SET budget = MAX(0, budget + ?), quality = quality + ?, research = research + ?, reputation = reputation + ? WHERE id = ?",
                    (*delta, project["id"]),
                )
                conn.commit()
            return self.get_startup(server_id, user_id)

    def advance_startup(self, server_id: int, user_id: int) -> ActivityUpdate:
        with self._lock:
            project = self.get_startup(server_id, user_id)
            if int(project["guild"]["owner_id"]) != user_id:
                raise RewardsError("Only the guild leader can advance the project.")
            if int(project["contributions"]) < 1:
                raise RewardsError("At least one teammate must contribute before advancing.")
            phase = int(project["phase"])
            if phase < 3:
                with self._conn() as conn:
                    conn.execute("UPDATE startup_projects SET phase = phase + 1 WHERE id = ?", (project["id"],))
                    conn.commit()
                return ActivityUpdate(f"Project advanced to phase {phase + 1}.")
            score = int(project["quality"]) + int(project["research"]) + int(project["reputation"]) + int(project["budget"]) // 2
            reward = 250 if score >= 140 else 150
            with self._conn() as conn:
                conn.execute("UPDATE startup_projects SET status = 'COMPLETE' WHERE id = ?", (project["id"],))
                members = conn.execute("SELECT user_id FROM guild_members WHERE guild_id = ?", (project["guild_id"],)).fetchall()
                conn.commit()
            rewarded_count = 0
            for member in members:
                if self._award_daily_activity(
                    int(member["user_id"]),
                    reward,
                    "STARTUP_COMPLETE",
                    f"Completed startup project {project['name']}",
                ):
                    rewarded_count += 1
            return ActivityUpdate(
                f"Startup completed with a score of {score}. {rewarded_count} guild member(s) received today's {reward}-point reward.",
                completed=True,
                reward=reward,
            )

    def file_review(self, server_id: int, filer_id: int, target_id: int, transaction_id: int, reason: str) -> dict[str, Any]:
        if filer_id == target_id:
            raise RewardsError("A review case must name another participant.")
        with self._lock, self._conn() as conn:
            open_case = conn.execute("SELECT id FROM review_cases WHERE filer_id = ? AND status = 'OPEN'", (filer_id,)).fetchone()
            if open_case:
                raise RewardsError("You already have an open review case.")
            tx = conn.execute("SELECT * FROM transactions WHERE id = ? AND user_id = ?", (transaction_id, filer_id)).fetchone()
            if not tx or tx["action_type"] not in REVIEWABLE_ACTIONS:
                raise RewardsError("That transaction is not eligible for Campus Review.")
            if str(target_id) not in str(tx["description"] or ""):
                raise RewardsError("The named respondent is not connected to that transaction.")
            now = self._now()
            cursor = conn.execute(
                "INSERT INTO review_cases (server_id, filer_id, target_id, transaction_id, reason, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (server_id, filer_id, target_id, transaction_id, reason.strip()[:500], now.isoformat(), (now + timedelta(hours=24)).isoformat()),
            )
            conn.commit()
            return self.get_review(int(cursor.lastrowid), server_id=server_id)

    def get_reviewable_transactions(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in REVIEWABLE_ACTIONS)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, amount, action_type, description, created_at FROM transactions "
                f"WHERE user_id = ? AND amount < 0 AND action_type IN ({placeholders}) "
                "ORDER BY id DESC LIMIT ?",
                (user_id, *sorted(REVIEWABLE_ACTIONS), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_review(self, case_id: int, server_id: Optional[int] = None) -> dict[str, Any]:
        with self._conn() as conn:
            if server_id is None:
                row = conn.execute("SELECT * FROM review_cases WHERE id = ?", (case_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM review_cases WHERE id = ? AND server_id = ?",
                    (case_id, server_id),
                ).fetchone()
        if not row:
            raise RewardsError("Review case not found.")
        return dict(row)

    def respond_review(self, case_id: int, user_id: int, response: str, server_id: Optional[int] = None) -> dict[str, Any]:
        case = self.get_review(case_id, server_id=server_id)
        if int(case["target_id"]) != user_id or case["status"] != "OPEN":
            raise RewardsError("You cannot respond to this case.")
        if self._now() > datetime.fromisoformat(str(case["expires_at"])):
            raise RewardsError("The 24-hour response window has closed.")
        with self._conn() as conn:
            conn.execute("UPDATE review_cases SET response = ? WHERE id = ?", (response.strip()[:500], case_id))
            conn.commit()
        return self.get_review(case_id, server_id=server_id)

    def resolve_review(
        self,
        case_id: int,
        moderator_id: int,
        decision: str,
        note: str,
        server_id: Optional[int] = None,
    ) -> dict[str, Any]:
        clean = decision.casefold().strip()
        if clean not in {"dismiss", "uphold", "refund"}:
            raise RewardsError("Decision must be dismiss, uphold, or refund.")
        with self._lock:
            case = self.get_review(case_id, server_id=server_id)
            if case["status"] != "OPEN":
                raise RewardsError("This review case is already closed.")
            refunded = 0
            if clean == "refund":
                with self._conn() as conn:
                    tx = conn.execute("SELECT amount FROM transactions WHERE id = ?", (case["transaction_id"],)).fetchone()
                if tx and int(tx["amount"]) < 0:
                    refunded = abs(int(tx["amount"]))
                    self.rewards.add_points(int(case["filer_id"]), refunded, "REVIEW_REFUND", f"Campus Review case {case_id}")
            with self._conn() as conn:
                conn.execute(
                    "UPDATE review_cases SET status = 'CLOSED', resolution = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
                    (f"{clean}: {note.strip()[:400]}", moderator_id, self._now().isoformat(), case_id),
                )
                conn.commit()
            result = self.get_review(case_id, server_id=server_id)
            result["refunded"] = refunded
            return result

    def capture_economy_pulse(self, hours: int = 6, now: Optional[datetime] = None) -> dict[str, Any]:
        current = self._now(now)
        cutoff = current - timedelta(hours=hours)
        snapshot_key = current.strftime("%Y-%m-%dT%H")
        with self._lock, self._conn() as conn:
            previous_key_row = conn.execute(
                "SELECT snapshot_key FROM leaderboard_snapshots WHERE snapshot_key < ? ORDER BY snapshot_key DESC LIMIT 1",
                (snapshot_key,),
            ).fetchone()
            previous_key = previous_key_row["snapshot_key"] if previous_key_row else None
            previous_rows = conn.execute(
                "SELECT user_id, rank, net_worth FROM leaderboard_snapshots WHERE snapshot_key = ?",
                (previous_key,),
            ).fetchall() if previous_key else []
            previous = {int(row["user_id"]): dict(row) for row in previous_rows}
            users = conn.execute(
                "SELECT user_id, points, bank_points FROM users ORDER BY (points + bank_points) DESC, lifetime_points DESC"
            ).fetchall()
            conn.execute("DELETE FROM leaderboard_snapshots WHERE snapshot_key = ?", (snapshot_key,))
            current_rows: list[dict[str, int]] = []
            for rank, row in enumerate(users, start=1):
                net = int(row["points"]) + int(row["bank_points"])
                uid = int(row["user_id"])
                conn.execute(
                    "INSERT INTO leaderboard_snapshots (snapshot_key, user_id, rank, net_worth, captured_at) VALUES (?, ?, ?, ?, ?)",
                    (snapshot_key, uid, rank, net, current.isoformat()),
                )
                current_rows.append({"user_id": uid, "rank": rank, "net_worth": net})
            tx_rows = conn.execute(
                "SELECT amount, action_type FROM transactions WHERE created_at >= ?",
                (cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
            ).fetchall()
            casino = conn.execute(
                "SELECT COUNT(*) AS rounds, SUM(won) AS wins FROM gambling_rounds WHERE settled_at >= ?",
                (cutoff.isoformat(),),
            ).fetchone()
            study_count = conn.execute(
                "SELECT COUNT(*) AS count FROM transactions WHERE action_type = 'STUDY' AND created_at >= ?",
                (cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
            ).fetchone()["count"]
            conn.commit()

        movements = []
        growth = []
        for row in current_rows:
            old = previous.get(row["user_id"])
            if old:
                movement = int(old["rank"]) - row["rank"]
                if movement:
                    movements.append({**row, "movement": movement})
                delta = row["net_worth"] - int(old["net_worth"])
                if delta:
                    percent = round(delta / max(int(old["net_worth"]), 1) * 100)
                    growth.append({**row, "delta": delta, "percent": percent if int(old["net_worth"]) >= 500 else None})
            elif row["rank"] <= 10:
                movements.append({**row, "movement": None})
        movements.sort(key=lambda item: abs(item["movement"] or 999), reverse=True)
        growth.sort(key=lambda item: item["delta"], reverse=True)
        positive = sum(max(0, int(row["amount"])) for row in tx_rows)
        negative = abs(sum(min(0, int(row["amount"])) for row in tx_rows))
        rounds = int(casino["rounds"] or 0)
        wins = int(casino["wins"] or 0)
        return {
            "hours": hours,
            "earned": positive,
            "spent": negative,
            "transactions": len(tx_rows),
            "casino_rounds": rounds,
            "casino_win_rate": round(wins / rounds * 100) if rounds else 0,
            "study_sessions": int(study_count),
            "movements": movements[:5],
            "growth": [item for item in growth if item["delta"] >= 100][:3],
            "top": current_rows[:10],
        }
