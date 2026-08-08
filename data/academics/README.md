# Academic Schedule Data Guide

This guide explains how to prepare, structure, and update academic schedule data when deploying or customizing Uno for your school or college block section.

---

## 📂 Directory Layout

Uno loads schedule data from static JSON files organized by school year and semester under the `data/academics/` directory:

```text
data/academics/
├── README.md
└── 2026-2027/
    ├── semester-1.json
    └── semester-2.json
```

---

## ⚙️ Selecting the Active Term

The active schedule file is selected dynamically in `.env` (or environment variables) without altering code:

```env
ACADEMIC_SCHOOL_YEAR=2026-2027
ACADEMIC_SEMESTER=1
ACADEMIC_TIMEZONE=Asia/Manila
```

Based on these settings, Uno automatically loads:
`data/academics/{ACADEMIC_SCHOOL_YEAR}/semester-{ACADEMIC_SEMESTER}.json`

Example: `data/academics/2026-2027/semester-1.json`

---

## 📋 Complete Schema Example

Here is a complete, valid schedule JSON file:

```json
{
  "school_year": "2026-2027",
  "semester": 1,
  "timezone": "Asia/Manila",
  "subjects": [
    {
      "code": "CIST_101",
      "name": "Introduction to Computing (Lecture)",
      "professor": "Jonathan Morano",
      "class_type": "Lecture",
      "schedules": [
        {
          "day": "Monday",
          "start": "10:00",
          "end": "12:00",
          "location": "Comp Lab 3"
        }
      ]
    },
    {
      "code": "GEC_STAS",
      "name": "Science, Technology and Society",
      "professor": "Roberto Vitancol",
      "class_type": "General Education",
      "schedules": [
        {
          "day": "Tuesday",
          "start": "07:00",
          "end": "08:30",
          "location": "GCA 307"
        },
        {
          "day": "Friday",
          "start": "07:00",
          "end": "08:30",
          "location": "MS Teams"
        }
      ]
    }
  ]
}
```

---

## 🔑 Required Schema Fields

### Top-Level Fields

- `school_year` (string): The academic school year string (e.g. `"2026-2027"`).
- `semester` (integer): The semester number (e.g. `1` or `2`).
- `timezone` (string): Valid IANA timezone name (e.g. `"Asia/Manila"`, `"America/New_York"`).
- `subjects` (array): Array of subject objects.

### Subject Fields

- `code` (string, required): Unique subject identifier (e.g. `"CIST_102"`). Must be unique within the JSON file.
- `name` (string, required): Display title of the subject.
- `professor` (string, required): Name of the instructor/professor.
- `class_type` (string, optional): Descriptive metadata (e.g. `"Lecture"`, `"Lab"`, `"General Education"`, `"PE"`, `"NSTP"`).
- `schedules` (array, required): Array of class meeting times. Must contain at least 1 meeting.

### Schedule Fields

- `day` (string, required): Full English day name (`Monday`, `Tuesday`, `Wednesday`, `Thursday`, `Friday`, `Saturday`, `Sunday`).
- `start` (string, required): Class start time in **24-hour `HH:MM`** format (e.g. `"07:00"`, `"13:30"`).
- `end` (string, required): Class end time in **24-hour `HH:MM`** format (e.g. `"10:00"`, `"16:00"`). Must be strictly after `start`.
- `location` (string, required): Physical room number, field, gym, or online platform (e.g. `"Comp Lab 4"`, `"GCA 307"`, `"MS Teams"`).

---

## ⏰ Time Format Rules

All `start` and `end` times **MUST** use 24-hour `HH:MM` format.

- ✅ Correct: `"07:00"`, `"08:30"`, `"13:00"`, `"18:00"`, `"21:00"`
- ❌ Incorrect: `"7 AM"`, `"8:30am"`, `"1:00 PM"`, `"6:00pm"`

---

## 📅 Multiple Weekly Meetings & Labs

If a subject meets multiple times a week (e.g. a lecture that meets on Tuesday in-person and Friday online), add multiple entries to the `schedules` array:

```json
{
  "code": "GEC_PCOM",
  "name": "Purposive Communication",
  "professor": "Risa Asuncion",
  "class_type": "General Education",
  "schedules": [
    {
      "day": "Tuesday",
      "start": "10:00",
      "end": "12:00",
      "location": "GCA 307"
    },
    {
      "day": "Friday",
      "start": "10:00",
      "end": "12:00",
      "location": "MS Teams"
    }
  ]
}
```

If a course has separate Lecture and Lab sections with different subject codes or times (e.g., `CIST_102` and `CIST102L`), define them as separate subject entries in the `subjects` array.

---

## 🔄 Updating Data for a New Semester or School Year

### New Semester Workflow

1. Keep existing semester files for historical reference.
2. Create a new file for the next semester (e.g. `data/academics/2026-2027/semester-2.json`).
3. Add the new subjects and schedules.
4. Update `.env`:
   ```env
   ACADEMIC_SEMESTER=2
   ```
5. Restart Uno.
6. Run `/schedule` in Discord to verify.

### New School Year Workflow

1. Create a new folder for the school year (e.g. `data/academics/2027-2028/`).
2. Add `semester-1.json` inside the new folder.
3. Update `.env`:
   ```env
   ACADEMIC_SCHOOL_YEAR=2027-2028
   ACADEMIC_SEMESTER=1
   ```
4. Restart Uno.

---

## 🛠️ Validation Troubleshooting

Uno validates schedule JSON files at startup and logs clear technical errors if validation fails:

- **Duplicate Code**: Ensure every subject has a unique `code`.
- **Invalid Weekday**: Ensure day names match English spelling (`Monday` to `Sunday`).
- **Malformed Time**: Ensure times use `HH:MM` format (`00:00` to `23:59`).
- **Start >= End**: Ensure `start` time is earlier than `end` time for every class meeting.
- **Empty Schedules**: Ensure `schedules` array is not empty.
- **Missing File**: Check that the JSON file exists at `data/academics/{ACADEMIC_SCHOOL_YEAR}/semester-{ACADEMIC_SEMESTER}.json`.

---

## 🔒 Privacy Guidelines

This data is stored as static configuration in your repository.

- ❌ **Do NOT include**: Professor phone numbers, personal email addresses, student IDs, Discord user IDs, LMS passwords, or private meeting links/passwords.
- ✅ **Do include**: Public course codes, official subject names, professor names, class types, scheduled meeting times, and room numbers.
