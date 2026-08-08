from datetime import datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import pytest
import zoneinfo

from bot.services.academic_schedule import (
    AcademicScheduleService,
    ScheduleDataNotFoundError,
    ScheduleValidationError,
    parse_hhmm_time,
    format_duration,
)

SEED_JSON_PATH = Path("data/academics/2026-2027/semester-1.json")


def test_loads_valid_semester_json():
    """Test loading the real seed semester JSON file."""
    service = AcademicScheduleService(
        data_dir=Path("data/academics"),
        school_year="2026-2027",
        semester=1,
        tz_name="Asia/Manila",
    )
    term = service.get_term()

    assert term.school_year == "2026-2027"
    assert term.semester == 1
    assert term.timezone == "Asia/Manila"
    assert len(term.subjects) == 11


def test_parses_multiple_schedules():
    """Test subject with multiple weekly meetings (e.g. GEC_STAS)."""
    service = AcademicScheduleService(
        data_dir=Path("data/academics"),
        school_year="2026-2027",
        semester=1,
    )
    stas = service.find_subjects("GEC_STAS")[0]

    assert stas.code == "GEC_STAS"
    assert len(stas.schedules) == 2
    assert stas.schedules[0].day == "Tuesday"
    assert stas.schedules[0].location == "GCA 307"
    assert stas.schedules[1].day == "Friday"
    assert stas.schedules[1].location == "MS Teams"


def test_rejects_duplicate_subject_codes():
    """Test validation fails when JSON contains duplicate subject codes."""
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "2026-2027"
        tmp_path.mkdir(parents=True)

        bad_data = {
            "school_year": "2026-2027",
            "semester": 1,
            "timezone": "Asia/Manila",
            "subjects": [
                {
                    "code": "CIST_101",
                    "name": "Course 1",
                    "professor": "Prof A",
                    "schedules": [{"day": "Monday", "start": "10:00", "end": "12:00", "location": "R1"}],
                },
                {
                    "code": "CIST_101",
                    "name": "Course 2",
                    "professor": "Prof B",
                    "schedules": [{"day": "Tuesday", "start": "10:00", "end": "12:00", "location": "R2"}],
                },
            ],
        }
        with open(tmp_path / "semester-1.json", "w") as f:
            json.dump(bad_data, f)

        service = AcademicScheduleService(data_dir=Path(tmp_dir))
        with pytest.raises(ScheduleValidationError, match="Duplicate subject code 'CIST_101'"):
            service.get_term()


def test_rejects_malformed_time():
    """Test validation fails on invalid 12h or non-numeric time strings."""
    with pytest.raises(ScheduleValidationError, match="Expected 24-hour 'HH:MM'"):
        parse_hhmm_time("7 AM", "test label")

    with pytest.raises(ScheduleValidationError, match="Hours must be 0-23"):
        parse_hhmm_time("25:00", "test label")


def test_rejects_invalid_weekday():
    """Test validation fails on unrecognized day name."""
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "2026-2027"
        tmp_path.mkdir(parents=True)

        bad_data = {
            "school_year": "2026-2027",
            "semester": 1,
            "timezone": "Asia/Manila",
            "subjects": [
                {
                    "code": "TEST1",
                    "name": "Test",
                    "professor": "Prof",
                    "schedules": [{"day": "Funday", "start": "10:00", "end": "12:00", "location": "R1"}],
                }
            ],
        }
        with open(tmp_path / "semester-1.json", "w") as f:
            json.dump(bad_data, f)

        service = AcademicScheduleService(data_dir=Path(tmp_dir))
        with pytest.raises(ScheduleValidationError, match="invalid day 'Funday'"):
            service.get_term()


def test_rejects_start_time_after_end_time():
    """Test validation fails when start time >= end time."""
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "2026-2027"
        tmp_path.mkdir(parents=True)

        bad_data = {
            "school_year": "2026-2027",
            "semester": 1,
            "timezone": "Asia/Manila",
            "subjects": [
                {
                    "code": "TEST1",
                    "name": "Test",
                    "professor": "Prof",
                    "schedules": [{"day": "Monday", "start": "14:00", "end": "12:00", "location": "R1"}],
                }
            ],
        }
        with open(tmp_path / "semester-1.json", "w") as f:
            json.dump(bad_data, f)

        service = AcademicScheduleService(data_dir=Path(tmp_dir))
        with pytest.raises(ScheduleValidationError, match="must be strictly before end time"):
            service.get_term()


def test_missing_active_file_handled():
    """Test missing file raises ScheduleDataNotFoundError."""
    service = AcademicScheduleService(
        data_dir=Path("data/academics"),
        school_year="9999-9999",
        semester=9,
    )
    with pytest.raises(ScheduleDataNotFoundError):
        service.get_term()


def test_get_today_classes_and_chronological_ordering():
    """Test get_today returns correct classes sorted chronologically for Monday."""
    service = AcademicScheduleService(data_dir=Path("data/academics"))
    tz = zoneinfo.ZoneInfo("Asia/Manila")

    # Mock datetime to a Monday (e.g. 2026-08-10 08:00 AM Manila time)
    monday_dt = datetime(2026, 8, 10, 8, 0, tzinfo=tz)

    today_classes = service.get_today(now=monday_dt)
    assert len(today_classes) == 3

    # Check chronological ordering: CIST101L (7:00), CIST_101 (10:00), PATHFIT1 (15:00)
    assert today_classes[0][0].code == "CIST101L"
    assert today_classes[1][0].code == "CIST_101"
    assert today_classes[2][0].code == "PATHFIT1"


def test_get_week_grouping():
    """Test get_week groups classes by day."""
    service = AcademicScheduleService(data_dir=Path("data/academics"))
    week = service.get_week()

    assert "Monday" in week
    assert len(week["Monday"]) == 3
    assert "Tuesday" in week
    assert len(week["Tuesday"]) == 4  # STAS, MATH, PCOM, PLM_IR01
    assert "Sunday" in week
    assert len(week["Sunday"]) == 0


def test_get_next_class_later_today():
    """Test get_next_class when there is a class scheduled later on the same day."""
    service = AcademicScheduleService(data_dir=Path("data/academics"))
    tz = zoneinfo.ZoneInfo("Asia/Manila")

    # Wednesday 2026-08-12 at 09:00 AM (Before CIST_102 at 10:00 AM)
    now_dt = datetime(2026, 8, 12, 9, 0, tzinfo=tz)

    next_info = service.get_next_class(now=now_dt)
    assert next_info is not None
    assert next_info["subject"].code == "CIST_102"
    assert next_info["is_current"] is False
    assert "Starts in 1 hour" in next_info["status_text"]


def test_get_next_class_currently_active():
    """Test get_next_class when user calls it during an active class."""
    service = AcademicScheduleService(data_dir=Path("data/academics"))
    tz = zoneinfo.ZoneInfo("Asia/Manila")

    # Wednesday 2026-08-12 at 10:30 AM (Inside CIST_102 10:00 - 12:00)
    now_dt = datetime(2026, 8, 12, 10, 30, tzinfo=tz)

    next_info = service.get_next_class(now=now_dt)
    assert next_info is not None
    assert next_info["subject"].code == "CIST_102"
    assert next_info["is_current"] is True
    assert "Currently in class · Ends in 1 hour 30 minutes" in next_info["status_text"]


def test_get_next_class_tomorrow():
    """Test get_next_class when the next class is tomorrow."""
    service = AcademicScheduleService(data_dir=Path("data/academics"))
    tz = zoneinfo.ZoneInfo("Asia/Manila")

    # Monday 2026-08-10 at 18:00 (All Monday classes finished)
    now_dt = datetime(2026, 8, 10, 18, 0, tzinfo=tz)

    next_info = service.get_next_class(now=now_dt)
    assert next_info is not None
    assert next_info["subject"].code == "GEC_STAS"
    assert "Starts tomorrow at 7:00 AM" in next_info["status_text"]


def test_get_next_class_weekend_wrapping():
    """Test get_next_class on Saturday night wraps to Monday morning."""
    service = AcademicScheduleService(data_dir=Path("data/academics"))
    tz = zoneinfo.ZoneInfo("Asia/Manila")

    # Saturday 2026-08-15 at 17:00 (After NSTP3)
    now_dt = datetime(2026, 8, 15, 17, 0, tzinfo=tz)

    next_info = service.get_next_class(now=now_dt)
    assert next_info is not None
    assert next_info["subject"].code == "CIST101L"
    assert "Starts Monday at 7:00 AM" in next_info["status_text"]


def test_find_subjects_searches():
    """Test exact code, case-insensitive code, subject name, and partial matches."""
    service = AcademicScheduleService(data_dir=Path("data/academics"))

    # 1. Exact code
    res1 = service.find_subjects("CIST_102")
    assert len(res1) == 1
    assert res1[0].code == "CIST_102"

    # 2. Case-insensitive code
    res2 = service.find_subjects("cist_102")
    assert len(res2) == 1
    assert res2[0].code == "CIST_102"

    # 3. Subject name
    res3 = service.find_subjects("Discrete Structures")
    assert len(res3) == 1
    assert res3[0].code == "BSCS_P01"

    # 4. Partial match broad query returning multiple
    res4 = service.find_subjects("programming")
    assert len(res4) == 2
    codes = {s.code for s in res4}
    assert codes == {"CIST_102", "CIST102L"}
