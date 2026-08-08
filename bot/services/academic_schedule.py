from dataclasses import dataclass
from datetime import datetime, time, timedelta
import json
import logging
from pathlib import Path
from typing import Any, Optional, Sequence
import zoneinfo

logger = logging.getLogger(__name__)

VALID_DAYS: Sequence[str] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

SEMESTER_NAMES = {
    1: "First Semester",
    2: "Second Semester",
    3: "Summer Term",
}


class ScheduleError(Exception):
    """Base exception for academic schedule operations."""

    pass


class ScheduleDataNotFoundError(ScheduleError):
    """Raised when the active semester JSON file is missing."""

    pass


class ScheduleValidationError(ScheduleError):
    """Raised when the JSON file contains invalid schema or data."""

    pass


@dataclass(frozen=True)
class ClassMeeting:
    """Represents a single weekly class meeting time and location."""

    day: str
    start: time
    end: time
    location: str


@dataclass(frozen=True)
class Subject:
    """Represents an academic subject with its professor and meeting schedule."""

    code: str
    name: str
    professor: str
    class_type: Optional[str]
    schedules: tuple[ClassMeeting, ...]


@dataclass(frozen=True)
class AcademicTerm:
    """Holds full academic term metadata and subject list."""

    school_year: str
    semester: int
    timezone: str
    subjects: tuple[Subject, ...]

    @property
    def semester_name(self) -> str:
        """Return human-readable semester title."""
        return SEMESTER_NAMES.get(self.semester, f"Semester {self.semester}")


def parse_hhmm_time(time_str: str, context_label: str) -> time:
    """Parse 24-hour HH:MM string into datetime.time object."""
    if not isinstance(time_str, str) or ":" not in time_str:
        raise ScheduleValidationError(
            f"Invalid time format '{time_str}' in {context_label}. Expected 24-hour 'HH:MM'."
        )

    parts = time_str.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ScheduleValidationError(
            f"Invalid time format '{time_str}' in {context_label}. Expected numeric 'HH:MM'."
        )

    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ScheduleValidationError(
            f"Time out of range '{time_str}' in {context_label}. Hours must be 0-23, minutes 0-59."
        )

    return time(hour=hh, minute=mm)


def format_duration(seconds: float) -> str:
    """Format total seconds into human-readable duration string."""
    total_minutes = max(1, int(seconds // 60))
    if total_minutes < 60:
        return f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"

    hours = total_minutes // 60
    rem_minutes = total_minutes % 60
    if rem_minutes == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"

    return f"{hours} hour{'s' if hours != 1 else ''} {rem_minutes} minute{'s' if rem_minutes != 1 else ''}"


def format_12h_time(t: time) -> str:
    """Format time object into human-readable 12-hour string (e.g., '7:00 AM', '1:00 PM')."""
    return t.strftime("%I:%M %p").lstrip("0")


class AcademicScheduleService:
    """Service handling loading, validation, and querying of local academic schedule JSON."""

    def __init__(
        self,
        data_dir: Path,
        school_year: str = "2026-2027",
        semester: int = 1,
        tz_name: str = "Asia/Manila",
    ):
        self.data_dir = Path(data_dir)
        self.school_year = school_year
        self.semester = semester
        self.tz_name = tz_name
        self._term: Optional[AcademicTerm] = None

    def load_data(self) -> AcademicTerm:
        """Load and validate academic schedule JSON file from disk."""
        target_path = (
            self.data_dir
            / self.school_year
            / f"semester-{self.semester}.json"
        )

        if not target_path.exists():
            logger.error(f"Academic schedule file not found at '{target_path}'")
            raise ScheduleDataNotFoundError(
                f"Academic schedule data file missing for SY {self.school_year} Semester {self.semester}."
            )

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Malformed JSON in schedule file '{target_path}': {e}")
            raise ScheduleValidationError(f"Malformed JSON in schedule data file: {e}") from e
        except Exception as e:
            logger.error(f"Failed to read schedule file '{target_path}': {e}")
            raise ScheduleError(f"Could not read schedule file: {e}") from e

        if not isinstance(data, dict):
            raise ScheduleValidationError("Root JSON structure must be an object/dict.")

        sy = data.get("school_year")
        sem = data.get("semester")
        tz = data.get("timezone", self.tz_name)
        subjects_raw = data.get("subjects")

        if not sy or not isinstance(sy, str):
            raise ScheduleValidationError("Missing or invalid 'school_year' string.")
        if not isinstance(sem, int) or sem <= 0:
            raise ScheduleValidationError("Missing or invalid positive integer 'semester'.")
        if not subjects_raw or not isinstance(subjects_raw, list):
            raise ScheduleValidationError("Missing or non-array 'subjects' list.")

        parsed_subjects = []
        seen_codes: set[str] = set()

        for idx, subj in enumerate(subjects_raw, start=1):
            if not isinstance(subj, dict):
                raise ScheduleValidationError(f"Subject #{idx} is not an object.")

            code = subj.get("code")
            name = subj.get("name")
            professor = subj.get("professor")
            class_type = subj.get("class_type")
            schedules_raw = subj.get("schedules")

            if not code or not isinstance(code, str) or not code.strip():
                raise ScheduleValidationError(f"Subject #{idx} has empty or missing 'code'.")
            code_clean = code.strip()

            if code_clean in seen_codes:
                raise ScheduleValidationError(f"Duplicate subject code '{code_clean}' found.")
            seen_codes.add(code_clean)

            if not name or not isinstance(name, str) or not name.strip():
                raise ScheduleValidationError(f"Subject '{code_clean}' has empty or missing 'name'.")
            if not professor or not isinstance(professor, str) or not professor.strip():
                raise ScheduleValidationError(
                    f"Subject '{code_clean}' has empty or missing 'professor'."
                )
            if not schedules_raw or not isinstance(schedules_raw, list):
                raise ScheduleValidationError(
                    f"Subject '{code_clean}' has missing or empty 'schedules' list."
                )

            parsed_meetings = []
            for s_idx, m_raw in enumerate(schedules_raw, start=1):
                if not isinstance(m_raw, dict):
                    raise ScheduleValidationError(
                        f"Schedule #{s_idx} in subject '{code_clean}' is not an object."
                    )

                day = m_raw.get("day")
                start_raw = m_raw.get("start")
                end_raw = m_raw.get("end")
                location = m_raw.get("location")

                if day not in VALID_DAYS:
                    raise ScheduleValidationError(
                        f"Subject '{code_clean}' has invalid day '{day}'. Valid days: {VALID_DAYS}."
                    )

                start_t = parse_hhmm_time(
                    start_raw, f"subject '{code_clean}' start time"
                )
                end_t = parse_hhmm_time(end_raw, f"subject '{code_clean}' end time")

                if start_t >= end_t:
                    raise ScheduleValidationError(
                        f"Subject '{code_clean}' schedule start time ({start_raw}) must be strictly before end time ({end_raw})."
                    )

                if not location or not isinstance(location, str) or not location.strip():
                    raise ScheduleValidationError(
                        f"Subject '{code_clean}' has empty or missing 'location'."
                    )

                parsed_meetings.append(
                    ClassMeeting(
                        day=day,
                        start=start_t,
                        end=end_t,
                        location=location.strip(),
                    )
                )

            parsed_subjects.append(
                Subject(
                    code=code_clean,
                    name=name.strip(),
                    professor=professor.strip(),
                    class_type=class_type.strip() if isinstance(class_type, str) else None,
                    schedules=tuple(parsed_meetings),
                )
            )

        self._term = AcademicTerm(
            school_year=sy,
            semester=sem,
            timezone=tz,
            subjects=tuple(parsed_subjects),
        )
        logger.info(
            f"Successfully loaded academic term SY {sy} Semester {sem} with {len(parsed_subjects)} subjects."
        )
        return self._term

    def get_term(self) -> AcademicTerm:
        """Get active AcademicTerm data, loading from disk if necessary."""
        if self._term is None:
            self.load_data()
        return self._term

    def _get_now_in_tz(self, now: Optional[datetime] = None) -> datetime:
        """Helper to resolve current datetime in the configured IANA timezone."""
        term = self.get_term()
        try:
            tz = zoneinfo.ZoneInfo(term.timezone)
        except Exception as e:
            logger.warning(f"Could not load ZoneInfo('{term.timezone}'), falling back to UTC+8: {e}")
            tz = timezone(timedelta(hours=8))

        if now is None:
            return datetime.now(tz)

        if now.tzinfo is None:
            return now.replace(tzinfo=tz)

        return now.astimezone(tz)

    def get_today(
        self, now: Optional[datetime] = None
    ) -> list[tuple[Subject, ClassMeeting]]:
        """Get list of (Subject, ClassMeeting) pairs scheduled for today, sorted chronologically."""
        term = self.get_term()
        current_dt = self._get_now_in_tz(now)
        today_name = VALID_DAYS[current_dt.weekday()]

        today_classes = []
        for subject in term.subjects:
            for meeting in subject.schedules:
                if meeting.day == today_name:
                    today_classes.append((subject, meeting))

        today_classes.sort(key=lambda item: item[1].start)
        return today_classes

    def get_week(self) -> dict[str, list[tuple[Subject, ClassMeeting]]]:
        """Get weekly schedule grouped by weekday name in chronological order."""
        term = self.get_term()
        weekly_map: dict[str, list[tuple[Subject, ClassMeeting]]] = {
            day: [] for day in VALID_DAYS
        }

        for subject in term.subjects:
            for meeting in subject.schedules:
                weekly_map[meeting.day].append((subject, meeting))

        for day in VALID_DAYS:
            weekly_map[day].sort(key=lambda item: item[1].start)

        return weekly_map

    def get_next_class(
        self, now: Optional[datetime] = None
    ) -> Optional[dict[str, Any]]:
        """Determine current active class or next upcoming class chronologically.

        Returns:
            Dict containing subject, meeting, is_current, meeting_dt, end_dt, status_text
            or None if no classes exist in term.
        """
        term = self.get_term()
        if not term.subjects:
            return None

        current_dt = self._get_now_in_tz(now)
        current_day_idx = current_dt.weekday()

        candidates = []

        for subject in term.subjects:
            for meeting in subject.schedules:
                meeting_day_idx = VALID_DAYS.index(meeting.day)
                day_offset = (meeting_day_idx - current_day_idx) % 7

                meeting_date = current_dt.date() + timedelta(days=day_offset)
                start_dt = datetime.combine(meeting_date, meeting.start, tzinfo=current_dt.tzinfo)
                end_dt = datetime.combine(meeting_date, meeting.end, tzinfo=current_dt.tzinfo)

                is_current = False

                if day_offset == 0:
                    if start_dt <= current_dt < end_dt:
                        is_current = True
                    elif current_dt >= end_dt:
                        # Meeting has passed today -> wraps to next week
                        start_dt += timedelta(days=7)
                        end_dt += timedelta(days=7)

                candidates.append(
                    {
                        "subject": subject,
                        "meeting": meeting,
                        "is_current": is_current,
                        "start_dt": start_dt,
                        "end_dt": end_dt,
                    }
                )

        if not candidates:
            return None

        # Prioritize currently active class first, then nearest future start_dt
        current_active = [c for c in candidates if c["is_current"]]
        if current_active:
            target = current_active[0]
            time_left_sec = (target["end_dt"] - current_dt).total_seconds()
            dur_str = format_duration(time_left_sec)
            status_text = f"Currently in class · Ends in {dur_str}"
        else:
            future_candidates = [c for c in candidates if c["start_dt"] > current_dt]
            if not future_candidates:
                return None

            target = min(future_candidates, key=lambda c: c["start_dt"])
            sec_until = (target["start_dt"] - current_dt).total_seconds()
            day_diff = (target["start_dt"].date() - current_dt.date()).days

            if day_diff == 0:
                status_text = f"Starts in {format_duration(sec_until)}"
            elif day_diff == 1:
                status_text = f"Starts tomorrow at {format_12h_time(target['meeting'].start)}"
            else:
                status_text = f"Starts {target['meeting'].day} at {format_12h_time(target['meeting'].start)}"

        return {
            "subject": target["subject"],
            "meeting": target["meeting"],
            "is_current": target["is_current"],
            "start_dt": target["start_dt"],
            "end_dt": target["end_dt"],
            "status_text": status_text,
        }

    def find_subjects(self, query: str) -> list[Subject]:
        """Search subjects by code, name, or partial match."""
        term = self.get_term()
        cleaned = query.strip()
        if not cleaned:
            return []

        lower_query = cleaned.lower()

        exact_code_matches = []
        code_sub_matches = []
        name_matches = []

        for subject in term.subjects:
            s_code_lower = subject.code.lower()
            s_name_lower = subject.name.lower()

            if s_code_lower == lower_query:
                exact_code_matches.append(subject)
            elif lower_query in s_code_lower:
                code_sub_matches.append(subject)
            elif lower_query in s_name_lower:
                name_matches.append(subject)

        combined = exact_code_matches + code_sub_matches + name_matches
        # Deduplicate while preserving search rank order
        seen = set()
        result = []
        for subj in combined:
            if subj.code not in seen:
                seen.add(subj.code)
                result.append(subj)

        return result
