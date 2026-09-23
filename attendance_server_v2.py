from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
import os
import hashlib
import hmac
import secrets
from typing import List, Optional
from datetime import datetime, timedelta

app = FastAPI()

DB_PATH = "/data/cloud.db"


# =========================================================
# DB
# =========================================================

def get_conn():
    os.makedirs("/data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        display_name TEXT,
        first_name TEXT,
        last_name TEXT,
        group_name TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        attended_date TEXT,
        present INTEGER DEFAULT 1,
        finalized INTEGER DEFAULT 0,
        UNIQUE(client_id, attended_date)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_date TEXT,
        end_date TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # ---------------------------------------------------------
    # CHALLENGE ATTENDANCE SCHEDULE
    # ---------------------------------------------------------
    # Comma-separated Python weekday numbers:
    # Monday=0, Tuesday=1, Wednesday=2, Thursday=3,
    # Friday=4, Saturday=5, Sunday=6
    #
    # Existing challenges default to Monday/Wednesday.
    # Future challenges can use any combination.

    try:
        cur.execute("""
            ALTER TABLE challenges
            ADD COLUMN class_days TEXT DEFAULT '0,2'
        """)
    except Exception:
        pass

    try:
        cur.execute("""
            ALTER TABLE challenges
            ADD COLUMN special_class_dates TEXT DEFAULT ''
        """)
    except Exception:
        pass

    try:
        cur.execute("""
            ALTER TABLE challenges
            ADD COLUMN no_class_dates TEXT DEFAULT ''
        """)
    except Exception:
        pass

    conn.commit()
    conn.close()


# =========================================================
# MODELS
# =========================================================


def upgrade_db():
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("ALTER TABLE attendance ADD COLUMN present INTEGER DEFAULT 1")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE attendance ADD COLUMN finalized INTEGER DEFAULT 0")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE clients ADD COLUMN baseline_score REAL DEFAULT 0")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE clients ADD COLUMN snapshot_score REAL DEFAULT 0")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE clients ADD COLUMN previous_total REAL DEFAULT 0")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE clients ADD COLUMN challenge_active INTEGER DEFAULT 0")
    except Exception:
        pass

    # 13E — private client PIN authentication. The PIN itself is never stored.
    for sql in (
        "ALTER TABLE clients ADD COLUMN checkin_pin_hash TEXT",
        "ALTER TABLE clients ADD COLUMN checkin_pin_salt TEXT",
        "ALTER TABLE clients ADD COLUMN checkin_pin_setup_allowed INTEGER DEFAULT 0",
    ):
        try:
            cur.execute(sql)
        except Exception:
            pass
    # =====================================================
    # STUDENT ATTENDANCE CHECK-IN SESSION
    # =====================================================
    # Instructor-controlled gate for student QR check-in.
    # This does NOT replace the existing attendance table.

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_checkin_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TEXT NOT NULL UNIQUE,
            is_open INTEGER NOT NULL DEFAULT 0,
            opened_at TEXT,
            closed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


# =========================================================
# MODELS
# =========================================================

class SyncPayload(BaseModel):
    clients: List[dict]


class SavePayload(BaseModel):
    group: str
    selected_records: List[dict]


class DatePayload(BaseModel):
    date: str
    group: Optional[str] = None


# =========================================================
# HELPERS
# =========================================================
def get_active_class_schedule(check_date=None):
    """
    Determine whether a date is a valid attendance/class day
    for the currently active TSHRT challenge.

    Priority:
      1. Date must be inside the active challenge.
      2. no_class_dates always blocks attendance.
      3. special_class_dates always allows attendance.
      4. Otherwise class_days determines attendance.

    Returns a dictionary describing the decision.
    """

    if check_date is None:
        check_dt = datetime.now()
    elif isinstance(check_date, datetime):
        check_dt = check_date
    else:
        try:
            check_dt = datetime.strptime(str(check_date), "%Y-%m-%d")
        except ValueError:
            return {
                "ok": False,
                "is_class_day": False,
                "reason": "INVALID_DATE",
                "date": str(check_date)
            }

    date_text = check_dt.strftime("%Y-%m-%d")

    conn = get_conn()
    cur = conn.cursor()

    challenge = cur.execute("""
        SELECT
            start_date,
            end_date,
            active,
            COALESCE(class_days, '0,2') AS class_days,
            COALESCE(special_class_dates, '') AS special_class_dates,
            COALESCE(no_class_dates, '') AS no_class_dates
        FROM challenges
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    if not challenge:
        return {
            "ok": True,
            "is_class_day": False,
            "reason": "NO_ACTIVE_CHALLENGE",
            "date": date_text
        }

    start_date = str(challenge["start_date"] or "").strip()
    end_date = str(challenge["end_date"] or "").strip()

    if date_text < start_date or date_text > end_date:
        return {
            "ok": True,
            "is_class_day": False,
            "reason": "OUTSIDE_ACTIVE_CHALLENGE",
            "date": date_text,
            "start_date": start_date,
            "end_date": end_date
        }

    class_days = {
        x.strip()
        for x in str(challenge["class_days"] or "0,2").split(",")
        if x.strip()
    }

    special_dates = {
        x.strip()
        for x in str(challenge["special_class_dates"] or "").split(",")
        if x.strip()
    }

    no_class_dates = {
        x.strip()
        for x in str(challenge["no_class_dates"] or "").split(",")
        if x.strip()
    }

    # Explicit cancellation wins over everything.
    if date_text in no_class_dates:
        return {
            "ok": True,
            "is_class_day": False,
            "reason": "NO_CLASS_DATE",
            "date": date_text
        }

    # Explicit special/make-up class.
    if date_text in special_dates:
        return {
            "ok": True,
            "is_class_day": True,
            "reason": "SPECIAL_CLASS_DATE",
            "date": date_text
        }

    weekday = str(check_dt.weekday())

    if weekday in class_days:
        return {
            "ok": True,
            "is_class_day": True,
            "reason": "SCHEDULED_CLASS_DAY",
            "date": date_text
        }

    return {
        "ok": True,
        "is_class_day": False,
        "reason": "NOT_SCHEDULED",
        "date": date_text
    }
# =========================================================
# ATTENDANCE SCHEDULE DIAGNOSTIC
# =========================================================

@app.get("/debug/class-day")
def debug_class_day(date: Optional[str] = None):
    """
    Read-only diagnostic for the TSHRT class-day engine.
    Does not create, modify, or delete attendance.
    """

    result = get_active_class_schedule(date)

    return {
        "ok": True,
        "requested_date": date,
        "schedule_decision": result
    }


# =========================================================
# STUDENT CHECK-IN SESSION TABLE DIAGNOSTIC
# =========================================================

@app.get("/debug/checkin-session-table")
def debug_checkin_session_table():
    """
    Read-only diagnostic for the student QR check-in session table.
    Confirms the table exists in the live database and reports its
    schema and row count. Does not create, modify, or delete data.
    """

    conn = get_conn()
    cur = conn.cursor()

    try:
        table = cur.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'attendance_checkin_sessions'
            LIMIT 1
        """).fetchone()

        if not table:
            return {
                "ok": False,
                "database": DB_PATH,
                "table": "attendance_checkin_sessions",
                "exists": False,
                "message": "Student check-in session table was not found."
            }

        columns = cur.execute(
            "PRAGMA table_info(attendance_checkin_sessions)"
        ).fetchall()

        row_count = cur.execute(
            "SELECT COUNT(*) AS count FROM attendance_checkin_sessions"
        ).fetchone()["count"]

        return {
            "ok": True,
            "database": DB_PATH,
            "table": "attendance_checkin_sessions",
            "exists": True,
            "row_count": row_count,
            "columns": [dict(row) for row in columns]
        }

    finally:
        conn.close()
# =========================================================
# ATTENDANCE SCHEDULE MANAGER
# =========================================================

@app.get("/attendance-schedule", response_class=HTMLResponse)
def attendance_schedule_manager():
    """
    Instructor management page for the active challenge
    attendance schedule.

    This page changes attendance authorization rules only.
    It does NOT modify historical attendance records.
    """

    conn = get_conn()
    cur = conn.cursor()

    challenge = cur.execute("""
        SELECT
            id,
            start_date,
            end_date,
            COALESCE(class_days, '0,2') AS class_days,
            COALESCE(special_class_dates, '') AS special_class_dates,
            COALESCE(no_class_dates, '') AS no_class_dates
        FROM challenges
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    if not challenge:
        return """
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width, initial-scale=1.0">
            <title>TSHRT Attendance Schedule</title>
        </head>

        <body style="
            margin:0;
            background:#111;
            color:white;
            font-family:Arial, sans-serif;
            text-align:center;
        ">
            <div style="padding:50px 20px;">
                <h1 style="color:#d4af37;">TSHRT</h1>
                <h2>Attendance Schedule</h2>
                <p>There is currently no active challenge.</p>
            </div>
        </body>
        </html>
        """

    selected_days = {
        x.strip()
        for x in str(challenge["class_days"] or "0,2").split(",")
        if x.strip()
    }

    weekdays = [
        ("0", "Monday"),
        ("1", "Tuesday"),
        ("2", "Wednesday"),
        ("3", "Thursday"),
        ("4", "Friday"),
        ("5", "Saturday"),
        ("6", "Sunday"),
    ]

    day_controls = ""

    for day_number, day_name in weekdays:

        checked = "checked" if day_number in selected_days else ""

        day_controls += f"""
        <label class="day-option">
            <input type="checkbox"
                   name="class_days"
                   value="{day_number}"
                   {checked}>
            <span>{day_name}</span>
        </label>
        """

    return f"""
<!DOCTYPE html>
<html>

<head>

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>TSHRT Attendance Schedule</title>

    <style>

        body {{
            margin:0;
            background:#111;
            color:white;
            font-family:Arial, sans-serif;
        }}

        .header {{
            background:#000;
            border-bottom:4px solid #d4af37;
            padding:24px 15px;
            text-align:center;
        }}

        .header h1 {{
            color:#d4af37;
            margin:0;
            font-size:30px;
        }}

        .container {{
            max-width:650px;
            margin:auto;
            padding:25px 18px 50px 18px;
        }}

        .card {{
            background:#1b1b1b;
            border:1px solid #444;
            border-radius:12px;
            padding:20px;
            margin-bottom:20px;
        }}

        .card h2 {{
            color:#d4af37;
            margin-top:0;
        }}

        .challenge-dates {{
            line-height:1.7;
            font-size:17px;
        }}

        .day-option {{
            display:flex;
            align-items:center;
            gap:14px;
            background:#262626;
            padding:15px;
            margin:8px 0;
            border-radius:8px;
            font-size:18px;
        }}

        .day-option input {{
            width:22px;
            height:22px;
        }}

        textarea {{
            width:100%;
            box-sizing:border-box;
            min-height:90px;
            background:#111;
            color:white;
            border:1px solid #666;
            border-radius:8px;
            padding:12px;
            font-size:16px;
        }}

        .hint {{
            color:#aaa;
            font-size:14px;
            line-height:1.4;
        }}

        .save {{
            width:100%;
            background:#d4af37;
            color:#000;
            border:none;
            border-radius:9px;
            padding:17px;
            font-size:19px;
            font-weight:bold;
            cursor:pointer;
        }}

    </style>

</head>

<body>

<div class="header">
    <h1>TSHRT</h1>
    <p>Attendance Schedule Manager</p>
</div>

<div class="container">

    <div class="card">

        <h2>ACTIVE CHALLENGE</h2>

        <div class="challenge-dates">
            <strong>Start:</strong> {challenge["start_date"]}<br>
            <strong>End:</strong> {challenge["end_date"]}
        </div>

    </div>

    <form method="post"
          action="/attendance-schedule/save">

        <div class="card">

            <h2>REGULAR CLASS DAYS</h2>

            {day_controls}

        </div>

        <div class="card">

            <h2>SPECIAL CLASS DATES</h2>

            <p class="hint">
                Optional makeup or extra class dates.<br>
                Use YYYY-MM-DD. Separate multiple dates with commas.
            </p>

            <textarea
                name="special_class_dates"
                placeholder="2026-09-19, 2026-10-03">{challenge["special_class_dates"]}</textarea>

        </div>

        <div class="card">

            <h2>NO-CLASS DATES</h2>

            <p class="hint">
                Holidays, cancellations, or other dates when a
                normally scheduled class will not meet.<br>
                Use YYYY-MM-DD. Separate multiple dates with commas.
            </p>

            <textarea
                name="no_class_dates"
                placeholder="2026-11-25">{challenge["no_class_dates"]}</textarea>

        </div>

        <button class="save" type="submit">
            SAVE ATTENDANCE SCHEDULE
        </button>

    </form>

</div>

</body>
</html>
"""
# =========================================================
# ATTENDANCE SCHEDULE MANAGER — SAVE
# =========================================================

@app.post("/attendance-schedule/save", response_class=HTMLResponse)
def save_attendance_schedule(
    class_days: Optional[List[str]] = Form(None),
    special_class_dates: str = Form(""),
    no_class_dates: str = Form("")
):
    """
    Validate and save attendance schedule settings for the
    currently active challenge.

    This changes attendance authorization rules only.
    Historical attendance records are never modified.
    """

    # -----------------------------------------------------
    # VALIDATE REGULAR CLASS DAYS
    # -----------------------------------------------------

    selected_days = class_days or []

    valid_day_values = {"0", "1", "2", "3", "4", "5", "6"}

    selected_days = [
        str(day).strip()
        for day in selected_days
        if str(day).strip() in valid_day_values
    ]

    # Remove duplicates and keep weekday order.
    selected_days = sorted(
        set(selected_days),
        key=lambda x: int(x)
    )

    if not selected_days:
        return HTMLResponse(
            content="""
            <html>
            <head>
                <meta name="viewport"
                      content="width=device-width, initial-scale=1.0">
                <title>Schedule Error</title>
            </head>

            <body style="
                margin:0;
                background:#111;
                color:white;
                font-family:Arial, sans-serif;
                text-align:center;
            ">

                <div style="padding:50px 20px;">

                    <h1 style="color:#d4af37;">
                        TSHRT
                    </h1>

                    <h2>Schedule Not Saved</h2>

                    <p>
                        Select at least one regular class day.
                    </p>

                    <a href="/attendance-schedule"
                       style="
                           display:inline-block;
                           margin-top:20px;
                           padding:14px 22px;
                           background:#d4af37;
                           color:#000;
                           text-decoration:none;
                           border-radius:8px;
                           font-weight:bold;
                       ">
                        RETURN TO SCHEDULE
                    </a>

                </div>

            </body>
            </html>
            """,
            status_code=400
        )

    # -----------------------------------------------------
    # DATE LIST VALIDATOR
    # -----------------------------------------------------

    def validate_date_list(raw_text):
        """
        Accept comma-separated YYYY-MM-DD dates.
        Returns normalized list or raises ValueError.
        """

        raw_text = (raw_text or "").strip()

        if not raw_text:
            return []

        normalized = []

        for item in raw_text.split(","):

            date_text = item.strip()

            if not date_text:
                continue

            try:
                parsed = datetime.strptime(
                    date_text,
                    "%Y-%m-%d"
                )
            except ValueError:
                raise ValueError(
                    f"Invalid date: {date_text}. "
                    "Use YYYY-MM-DD."
                )

            normalized.append(
                parsed.strftime("%Y-%m-%d")
            )

        return sorted(set(normalized))

    try:
        special_dates = validate_date_list(
            special_class_dates
        )

        no_class_dates_list = validate_date_list(
            no_class_dates
        )

    except ValueError as e:

        return HTMLResponse(
            content=f"""
            <html>
            <head>
                <meta name="viewport"
                      content="width=device-width, initial-scale=1.0">
                <title>Schedule Error</title>
            </head>

            <body style="
                margin:0;
                background:#111;
                color:white;
                font-family:Arial, sans-serif;
                text-align:center;
            ">

                <div style="padding:50px 20px;">

                    <h1 style="color:#d4af37;">
                        TSHRT
                    </h1>

                    <h2>Schedule Not Saved</h2>

                    <p>{str(e)}</p>

                    <p>
                        No schedule changes were made.
                    </p>

                    <a href="/attendance-schedule"
                       style="
                           display:inline-block;
                           margin-top:20px;
                           padding:14px 22px;
                           background:#d4af37;
                           color:#000;
                           text-decoration:none;
                           border-radius:8px;
                           font-weight:bold;
                       ">
                        RETURN TO SCHEDULE
                    </a>

                </div>

            </body>
            </html>
            """,
            status_code=400
        )

    # -----------------------------------------------------
    # PREVENT DATE CONFLICTS
    # -----------------------------------------------------

    conflicts = sorted(
        set(special_dates) &
        set(no_class_dates_list)
    )

    if conflicts:

        conflict_text = ", ".join(conflicts)

        return HTMLResponse(
            content=f"""
            <html>
            <head>
                <meta name="viewport"
                      content="width=device-width, initial-scale=1.0">
                <title>Schedule Conflict</title>
            </head>

            <body style="
                margin:0;
                background:#111;
                color:white;
                font-family:Arial, sans-serif;
                text-align:center;
            ">

                <div style="padding:50px 20px;">

                    <h1 style="color:#d4af37;">
                        TSHRT
                    </h1>

                    <h2>Schedule Not Saved</h2>

                    <p>
                        The following date appears as both
                        a Special Class Date and a No-Class Date:
                    </p>

                    <p style="
                        color:#d4af37;
                        font-weight:bold;
                    ">
                        {conflict_text}
                    </p>

                    <p>
                        Remove the conflict and try again.
                    </p>

                    <a href="/attendance-schedule"
                       style="
                           display:inline-block;
                           margin-top:20px;
                           padding:14px 22px;
                           background:#d4af37;
                           color:#000;
                           text-decoration:none;
                           border-radius:8px;
                           font-weight:bold;
                       ">
                        RETURN TO SCHEDULE
                    </a>

                </div>

            </body>
            </html>
            """,
            status_code=400
        )

    # -----------------------------------------------------
    # SAVE ACTIVE CHALLENGE SCHEDULE
    # -----------------------------------------------------

    conn = get_conn()
    cur = conn.cursor()

    try:

        challenge = cur.execute("""
            SELECT id
            FROM challenges
            WHERE active = 1
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if not challenge:
            conn.close()

            return HTMLResponse(
                content="""
                <html>
                <body style="
                    background:#111;
                    color:white;
                    font-family:Arial, sans-serif;
                    text-align:center;
                    padding:50px;
                ">
                    <h1 style="color:#d4af37;">TSHRT</h1>
                    <h2>Schedule Not Saved</h2>
                    <p>There is no active challenge.</p>
                    <a href="/attendance-schedule"
                       style="color:#d4af37;">
                        Return to Schedule
                    </a>
                </body>
                </html>
                """,
                status_code=400
            )

        class_days_text = ",".join(selected_days)
        special_dates_text = ",".join(special_dates)
        no_class_dates_text = ",".join(
            no_class_dates_list
        )

        cur.execute("""
            UPDATE challenges
            SET
                class_days = ?,
                special_class_dates = ?,
                no_class_dates = ?
            WHERE id = ?
        """, (
            class_days_text,
            special_dates_text,
            no_class_dates_text,
            challenge["id"]
        ))

        conn.commit()

    except Exception as e:

        conn.rollback()
        conn.close()

        return HTMLResponse(
            content=f"""
            <html>
            <body style="
                background:#111;
                color:white;
                font-family:Arial, sans-serif;
                text-align:center;
                padding:50px;
            ">
                <h1 style="color:#d4af37;">TSHRT</h1>
                <h2>Schedule Not Saved</h2>
                <p>{str(e)}</p>
                <p>No schedule changes were made.</p>
                <a href="/attendance-schedule"
                   style="color:#d4af37;">
                    Return to Schedule
                </a>
            </body>
            </html>
            """,
            status_code=500
        )

    conn.close()

    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    day_names = {
        "0": "Monday",
        "1": "Tuesday",
        "2": "Wednesday",
        "3": "Thursday",
        "4": "Friday",
        "5": "Saturday",
        "6": "Sunday"
    }

    selected_day_names = ", ".join(
        day_names[x] for x in selected_days
    )

    special_display = (
        ", ".join(special_dates)
        if special_dates
        else "None"
    )

    no_class_display = (
        ", ".join(no_class_dates_list)
        if no_class_dates_list
        else "None"
    )

    return f"""
<!DOCTYPE html>
<html>

<head>

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>Schedule Saved</title>

</head>

<body style="
    margin:0;
    background:#111;
    color:white;
    font-family:Arial, sans-serif;
    text-align:center;
">

    <div style="
        background:#000;
        border-bottom:4px solid #d4af37;
        padding:25px;
    ">

        <h1 style="
            color:#d4af37;
            margin:0;
        ">
            TSHRT
        </h1>

        <p>Attendance Schedule Manager</p>

    </div>

    <div style="
        max-width:650px;
        margin:auto;
        padding:40px 20px;
    ">

        <h2 style="color:#d4af37;">
            SCHEDULE SAVED
        </h2>

        <p>
            <strong>Regular Class Days:</strong><br>
            {selected_day_names}
        </p>

        <p>
            <strong>Special Class Dates:</strong><br>
            {special_display}
        </p>

        <p>
            <strong>No-Class Dates:</strong><br>
            {no_class_display}
        </p>

        <p style="
            color:#aaa;
            margin-top:25px;
        ">
            Historical attendance records were not changed.
        </p>

        <a href="/attendance-schedule"
           style="
               display:inline-block;
               margin-top:20px;
               padding:14px 22px;
               background:#d4af37;
               color:#000;
               text-decoration:none;
               border-radius:8px;
               font-weight:bold;
           ">
            RETURN TO SCHEDULE
        </a>

    </div>

</body>
</html>
"""
def parse_name(display_name: str):
    display_name = (display_name or "").strip()
    if not display_name:
        return "", ""

    if "," in display_name:
        parts = [p.strip() for p in display_name.split(",", 1)]
        last = parts[0]
        first = parts[1] if len(parts) > 1 else ""
        return first, last

    parts = display_name.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if len(parts) == 1:
        return parts[0], ""
    return "", ""


def group_match_sql():
    return "LOWER(TRIM(COALESCE(group_name, ''))) = LOWER(TRIM(?))"


def get_active_challenge_dates(cur):
    row = cur.execute("""
        SELECT start_date, end_date
        FROM challenges
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()
    if row:
        return row["start_date"], row["end_date"]
    return None, None


@app.get("/challenge/active")
def active_challenge():
    conn = get_conn()
    cur = conn.cursor()

    row = cur.execute("""
        SELECT
            start_date,
            end_date,
            COALESCE(special_class_dates, '') AS special_class_dates,
            COALESCE(no_class_dates, '') AS no_class_dates
        FROM challenges
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    if not row:
        return {
            "ok": False,
            "start_date": None,
            "end_date": None,
            "special_class_dates": [],
            "no_class_dates": []
        }

    special_dates = [
        x.strip()
        for x in str(row["special_class_dates"] or "").split(",")
        if x.strip()
    ]

    no_class_dates = [
        x.strip()
        for x in str(row["no_class_dates"] or "").split(",")
        if x.strip()
    ]

    return {
        "ok": True,
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "special_class_dates": special_dates,
        "no_class_dates": no_class_dates
    }

def build_leaderboard_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    start_date, end_date = get_active_challenge_dates(cur)

    if start_date and end_date:
        attendance_join = """
            LEFT JOIN attendance a
                ON c.client_id = a.client_id
                AND COALESCE(a.present, 1) = 1
                AND a.attended_date >= ?
                AND a.attended_date <= ?
        """
        params = (start_date, end_date, group)
    else:
        attendance_join = """
            LEFT JOIN attendance a
                ON c.client_id = a.client_id
                AND COALESCE(a.present, 1) = 1
        """
        params = (group,)

    rows = cur.execute(f"""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.display_name,
            COALESCE(c.baseline_score, 0) AS baseline_score,
            COALESCE(c.snapshot_score, 0) AS snapshot_score,
            COALESCE(c.previous_total, 0) AS previous_total,
            COUNT(a.attended_date) AS attendance_count
        FROM clients c
        {attendance_join}
        WHERE {group_match_sql()}
        GROUP BY
            c.client_id,
            c.first_name,
            c.last_name,
            c.display_name,
            c.baseline_score,
            c.snapshot_score,
            c.previous_total
    """, params).fetchall()

    conn.close()

    results = []
    for r in rows:
        first = (r["first_name"] or "").strip()
        last = (r["last_name"] or "").strip()
        display = (r["display_name"] or "").strip()

        if first or last:
            name = f"{last}, {first}".strip(", ")
        else:
            name = display

        baseline = r["baseline_score"] or 0
        snapshot = r["snapshot_score"] or 0
        attendance = r["attendance_count"] or 0
        previous = r["previous_total"] or 0

        current = baseline + snapshot + attendance
        lifetime = previous + current

        results.append({
            "client_id": r["client_id"],
            "name": name,
            "attendance": attendance,
            "baseline": round(baseline, 2),
            "snapshot": round(snapshot, 2),
            "current_score": round(current, 2),
            "lifetime_score": round(lifetime, 2),
        })

    # Permanent dual-ranking model. Scores are unchanged; only rank metadata is added.
    current_order = sorted(
        results,
        key=lambda x: (-x["current_score"], -x["lifetime_score"], x["name"].lower())
    )
    lifetime_order = sorted(
        results,
        key=lambda x: (-x["lifetime_score"], -x["current_score"], x["name"].lower())
    )

    current_rank = {row["client_id"]: i for i, row in enumerate(current_order, start=1)}
    lifetime_rank = {row["client_id"]: i for i, row in enumerate(lifetime_order, start=1)}

    for row in results:
        row["current_rank"] = current_rank[row["client_id"]]
        row["lifetime_rank"] = lifetime_rank[row["client_id"]]

    # A page titled Challenge Leaderboard should default to the active challenge.
    return current_order


# =========================================================
# BASIC
# =========================================================

@app.get("/")
def home():
    return {"ok": True, "service": "TSHRT Attendance Server"}


@app.get("/wake")
def wake():
    return {"ok": True, "status": "awake"}

@app.get("/debug/clients")
def debug_clients():
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT
            client_id,
            display_name,
            first_name,
            last_name,
            group_name,
            COALESCE(baseline_score, 0) AS baseline_score,
            COALESCE(snapshot_score, 0) AS snapshot_score,
            COALESCE(previous_total, 0) AS previous_total,
            COALESCE(challenge_active, 0) AS challenge_active
        FROM clients
        ORDER BY group_name, last_name, first_name
    """).fetchall()

    conn.close()

    return {"ok": True, "count": len(rows), "clients": [dict(r) for r in rows]}
    
@app.get("/debug/client_ids")
def debug_client_ids():

    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT
            client_id,
            display_name
        FROM clients
        ORDER BY display_name
    """).fetchall()

    conn.close()

    return {
        "ok": True,
        "rows": [dict(r) for r in rows]
    }

# =========================================================
# STARTUP
# =========================================================
@app.get("/debug/seed_previous_totals")
def seed_previous_totals():

    updates = {
        "Deborah_Crawford": 49,
        "Bennie_Feagin": 49,
        "Tracy_DeLa_Cruz": 42,
        "Luis_Ibarra": 42,
        "Michelle_Lozano": 42,
        "Eduardo_Carrasco": 41,
        "Viviana_Example": 40,
        "Aracely_Gomez": 40,
        "Paloma_Lozano": 39,
        "Paola_Sandoval": 37,
        "Stephanie_Morales": 35,
        "Melizza_Feagin": 32,
        "America_Martinez": 31,
        "Mariana_Ibarra": 29,
        "Rosalba_Cortez": 28,
        "Freddy_Vasquez": 27,
        "Briseidy_Alaniz": 21,
        "Erica_Torres": 21
    }

    conn = get_conn()
    cur = conn.cursor()

    for client_id, total in updates.items():

        cur.execute("""
            UPDATE clients
            SET previous_total = ?,
                baseline_score = 0,
                snapshot_score = 0,
                challenge_active = 0
            WHERE client_id = ?
        """, (total, client_id))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "updated": updates
    }
@app.get("/admin/reactivate_all")
def reactivate_all():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE clients
        SET challenge_active = 1
        WHERE group_name = 'ABC Class'
    """)

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "message": "ABC Class reactivated"
    }
@app.get("/debug/challenge")
def debug_challenge():
    conn = get_conn()
    cur = conn.cursor()
    active = cur.execute("""
        SELECT *
        FROM challenges
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()
    conn.close()
    return {"ok": True, "active_challenge": dict(active) if active else None}

@app.get("/debug/set_previous")
def debug_set_previous(client_id: str, amount: float):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE clients
        SET previous_total = ?
        WHERE client_id = ?
    """, (amount, client_id))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "client_id": client_id,
        "previous_total": amount
    }
# =========================================================
# ATTENDANCE DATA
# =========================================================

@app.get("/attendance/data")
def attendance_data(group: str):

    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT
            client_id,
            first_name,
            last_name,
            display_name,
            group_name
        FROM clients
        WHERE {group_match_sql()}
        ORDER BY last_name, first_name, display_name
    """, (group,)).fetchall()

    clients = []

    for r in rows:

        first_name = (r["first_name"] or "").strip()
        last_name = (r["last_name"] or "").strip()
        display_name = (r["display_name"] or "").strip()

        if (not first_name or not last_name) and display_name:
            p_first, p_last = parse_name(display_name)
            first_name = first_name or p_first
            last_name = last_name or p_last

        clients.append({
            "client_id": r["client_id"],
            "first_name": first_name,
            "last_name": last_name,
            "display_name": display_name
        })

    attendance_rows = cur.execute("""
        SELECT
            client_id,
            attended_date,
            COALESCE(present,1) AS present
        FROM attendance
    """).fetchall()

    attendance_map = {}

    for row in attendance_rows:

        key = f"{row['client_id']}|{row['attended_date']}"

        attendance_map[key] = bool(row["present"])

    finalized_rows = cur.execute("""
        SELECT DISTINCT attended_date
        FROM attendance
        WHERE COALESCE(finalized,0)=1
    """).fetchall()

    finalized_dates = [
        r["attended_date"]
        for r in finalized_rows
    ]

    conn.close()

    return {
        "ok": True,
        "clients": clients,
        "attendance": attendance_map,
        "finalized_dates": finalized_dates
    } 


@app.get("/attendance/load")
def load_attendance(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT a.client_id, a.attended_date
        FROM attendance a
        JOIN clients c ON a.client_id = c.client_id
        WHERE {group_match_sql()}
          AND COALESCE(a.present, 1) = 1
    """, (group,)).fetchall()

    finalized_rows = cur.execute(f"""
        SELECT DISTINCT a.attended_date
        FROM attendance a
        JOIN clients c ON a.client_id = c.client_id
        WHERE {group_match_sql()}
          AND COALESCE(a.finalized, 0) = 1
    """, (group,)).fetchall()

    conn.close()

    selected = {}
    for r in rows:
        selected[f"{r['client_id']}|{r['attended_date']}"] = True

    finalized_dates = [r["attended_date"] for r in finalized_rows]

    return {
        "ok": True,
        "selected": selected,
        "finalized_dates": finalized_dates
    }


# =========================================================
# SAVE / FINALIZE
# =========================================================

@app.post("/attendance/save")
def save_attendance(payload: SavePayload):
    group = (payload.group or "").strip()
    records = payload.selected_records or []

    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT client_id, display_name, first_name, last_name
        FROM clients
        WHERE {group_match_sql()}
    """, (group,)).fetchall()

    valid_ids = set()
    name_to_id = {}

    for row in rows:
        cid = row["client_id"]
        display_name = (row["display_name"] or "").strip()
        first = (row["first_name"] or "").strip()
        last = (row["last_name"] or "").strip()

        valid_ids.add(cid)

        if display_name:
            name_to_id[display_name.lower()] = cid

        if first or last:
            comma_name = f"{last}, {first}".strip(", ").lower()
            straight_name = f"{first} {last}".strip().lower()
            if comma_name:
                name_to_id[comma_name] = cid
            if straight_name:
                name_to_id[straight_name] = cid

    finalized_rows = cur.execute("""
        SELECT DISTINCT attended_date
        FROM attendance
        WHERE COALESCE(finalized, 0) = 1
    """).fetchall()
    finalized_dates = {r["attended_date"] for r in finalized_rows}

    selected_set = set()

    for rec in records:
        raw_client = str(rec.get("client_id", "")).strip()
        attended_date = str(rec.get("attended_date", "")).strip()

        if not raw_client or not attended_date:
            continue

        if raw_client in valid_ids:
            cid = raw_client
        else:
            cid = name_to_id.get(raw_client.lower())

        if not cid:
            continue

        if attended_date in finalized_dates:
            continue

        selected_set.add((cid, attended_date))

    cur.execute(f"""
        DELETE FROM attendance
        WHERE client_id IN (
            SELECT client_id
            FROM clients
            WHERE {group_match_sql()}
        )
        AND COALESCE(finalized, 0) = 0
    """, (group,))

    for cid, attended_date in selected_set:
        cur.execute("""
            INSERT INTO attendance (client_id, attended_date, present, finalized)
            VALUES (?, ?, 1, 0)
            ON CONFLICT(client_id, attended_date) DO UPDATE SET
                present = 1
        """, (cid, attended_date))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "saved_count": len(selected_set),
        "group": group
    }


@app.post("/attendance/finalize")
def finalize_date(payload: DatePayload):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE attendance
        SET finalized = 1
        WHERE attended_date = ?
    """, (payload.date,))

    conn.commit()
    conn.close()

    return {"ok": True, "date": payload.date, "action": "finalized"}


@app.post("/attendance/finalize_bulk")
def finalize_bulk(payload: dict):
    dates = payload.get("dates", [])

    if not dates:
        return {"ok": False, "message": "No dates provided"}

    conn = get_conn()
    cur = conn.cursor()

    for d in dates:
        cur.execute("""
            UPDATE attendance
            SET finalized = 1
            WHERE attended_date = ?
        """, (d,))

    conn.commit()
    conn.close()

    return {"ok": True, "finalized_dates": dates}


@app.post("/attendance/unfinalize")
def unfinalize_date(payload: DatePayload):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE attendance
        SET finalized = 0
        WHERE attended_date = ?
    """, (payload.date,))

    conn.commit()
    conn.close()

    return {"ok": True, "date": payload.date, "action": "unfinalized"}


# =========================================================
# LEADERBOARD / DISPLAY
# =========================================================

@app.get("/leaderboard")
def leaderboard(group: str):
    return {"ok": True, "leaderboard": build_leaderboard_data(group)}
    
@app.get("/leaderboard/data")
def leaderboard_data(group: str = "ABC Class"):

    return {
        "ok": True,
        "rows": build_leaderboard_data(group)
    }

@app.get("/board", response_class=HTMLResponse)
def leaderboard_page():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>TSHRT Leaderboard</title>
<style>
@media print {
    .controls, .legend, #status { display:none !important; }
    body { background:white !important; color:black !important; padding:0; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th, td { border:1px solid black; padding:6px; text-align:center; }
    #viewTitle { color:black !important; }
}
body { background:#0f172a; color:white; font-family:Arial; padding:20px; }
h2 { margin-bottom:10px; }
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:12px 0; }
button, select { font-size:14px; padding:8px 12px; border-radius:6px; border:1px solid #475569; }
button { cursor:pointer; background:#1e293b; color:white; }
button:hover { background:#334155; }
button.active-view { background:#fbbf24; color:#111827; font-weight:bold; border-color:#fbbf24; }
table { border-collapse:collapse; width:100%; margin-top:8px; }
th, td { border:1px solid #334155; padding:10px; text-align:center; }
th { background:#1e293b; }
.rank { font-weight:bold; }
.gold { color:#fbbf24; font-weight:bold; }
#status { margin:8px 0; color:#cbd5e1; min-height:20px; }
.legend { margin-top:25px; padding:15px; border:1px solid #334155; background:#111827; border-radius:10px; font-size:14px; line-height:1.8; }
</style>
</head>
<body>

<h2>🔥 TSHRT Challenge Leaderboard</h2>
<div id="challengeDates" style="color:#cbd5e1;margin-bottom:8px;"></div>

<div class="controls">
    <label for="group"><b>Group:</b></label>
    <select id="group" onchange="loadBoard()">
        <option>ABC Class</option>
        <option>Gym</option>
        <option>Personal</option>
    </select>
    <button id="btnCurrent" class="active-view" onclick="setView('current')">Current Challenge</button>
    <button id="btnLifetime" onclick="setView('lifetime')">Lifetime / Overall</button>
    <button id="btnCombined" onclick="setView('combined')">Combined Standings</button>
    <button onclick="window.print()">🖨️ Print Current View</button>
</div>

<div id="status">Loading leaderboard...</div>
<div id="viewTitle" style="margin:14px 0 8px 0;font-weight:bold;color:#fbbf24;"></div>
<table id="table"></table>

<div class="legend">
<h3 style="margin-top:0;">📘 Leaderboard Legend</h3>
<div>🔥 <b>Elite</b> = Outstanding consistency and performance</div>
<div>👍 <b>Consistent</b> = Solid steady progress</div>
<div>➖ <b>Stable</b> = Maintaining current condition</div>
<div>⚠️ <b>Needs Attention</b> = Metrics or attendance slipping</div>
<div>🚨 <b>Risk</b> = Immediate coaching intervention recommended</div>
</div>

<script>
let leaderboardRows = [];
let activeView = "current";

function formatDelta(v) {
    v = Number(v || 0);
    if (v >= 5) return "🔥 Excellent (+" + v + ")";
    if (v >= 1) return "👍 Improving (+" + v + ")";
    if (v <= -5) return "⚠️ Needs Attention (" + v + ")";
    if (v < 0) return "➖ Stable (" + v + ")";
    return "➖ Stable (0)";
}

function formatAttendance(v) {
    v = Number(v || 0);
    if (v >= 8) return v + " 🔥 Elite";
    if (v >= 6) return v + " 👍 Consistent";
    if (v >= 4) return v + " ➖ Stable";
    if (v >= 2) return v + " ⚠️ Slipping";
    return v + " 🚨 Risk";
}

function setView(view) {
    activeView = view;
    document.getElementById("btnCurrent").classList.toggle("active-view", view === "current");
    document.getElementById("btnLifetime").classList.toggle("active-view", view === "lifetime");
    document.getElementById("btnCombined").classList.toggle("active-view", view === "combined");
    renderBoard();
}

function renderBoard() {
    const table = document.getElementById("table");
    const status = document.getElementById("status");
    const titleBox = document.getElementById("viewTitle");

    if (!Array.isArray(leaderboardRows) || leaderboardRows.length === 0) {
        table.innerHTML = "";
        titleBox.textContent = "";
        status.textContent = "No leaderboard records were returned for this group.";
        return;
    }

    let rows = leaderboardRows.slice();
    let html = "";
    let title = "";

    if (activeView === "lifetime") {
        rows.sort((a,b) => (Number(b.lifetime_score) - Number(a.lifetime_score)) || (Number(b.current_score) - Number(a.current_score)) || String(a.name).localeCompare(String(b.name)));
        title = "LIFETIME / OVERALL STANDINGS";
        html = "<tr><th>Overall Rank</th><th>Name</th><th>Att</th><th>Base</th><th>Δ</th><th>Current</th><th>Lifetime</th><th>Challenge Rank</th></tr>";
    } else if (activeView === "combined") {
        rows.sort((a,b) => Number(a.current_rank) - Number(b.current_rank));
        title = "COMBINED CHALLENGE + LIFETIME STANDINGS";
        html = "<tr><th>Challenge Rank</th><th>Overall Rank</th><th>Name</th><th>Att</th><th>Base</th><th>Δ</th><th>Current</th><th>Lifetime</th></tr>";
    } else {
        rows.sort((a,b) => (Number(b.current_score) - Number(a.current_score)) || (Number(b.lifetime_score) - Number(a.lifetime_score)) || String(a.name).localeCompare(String(b.name)));
        title = "CURRENT CHALLENGE STANDINGS";
        html = "<tr><th>Challenge Rank</th><th>Name</th><th>Att</th><th>Base</th><th>Δ</th><th>Current</th><th>Lifetime</th><th>Overall Rank</th></tr>";
    }

    for (const r of rows) {
        const currentRank = Number(r.current_rank || 0);
        const lifetimeRank = Number(r.lifetime_rank || 0);
        const primaryRank = activeView === "lifetime" ? lifetimeRank : currentRank;
        const cls = primaryRank === 1 ? "gold" : "";

        html += "<tr>";
        if (activeView === "combined") {
            html += "<td class='rank " + (currentRank === 1 ? "gold" : "") + "'>" + currentRank + "</td>";
            html += "<td class='rank " + (lifetimeRank === 1 ? "gold" : "") + "'>" + lifetimeRank + "</td>";
            html += "<td>" + r.name + "</td>";
        } else {
            html += "<td class='rank " + cls + "'>" + primaryRank + "</td>";
            html += "<td>" + r.name + "</td>";
        }

        html += "<td>" + formatAttendance(r.attendance) + "</td>";
        html += "<td>" + r.baseline + "</td>";
        html += "<td>" + formatDelta(r.snapshot) + "</td>";
        html += "<td>" + r.current_score + "</td>";
        html += "<td>" + r.lifetime_score + "</td>";
        if (activeView === "lifetime") html += "<td class='rank'>" + currentRank + "</td>";
        if (activeView === "current") html += "<td class='rank'>" + lifetimeRank + "</td>";
        html += "</tr>";
    }

    titleBox.textContent = title;
    table.innerHTML = html;
    status.textContent = rows.length + " clients loaded.";
}

async function loadChallengeDates() {
    try {
        const res = await fetch("/challenge/active");
        const data = await res.json();
        if (data && data.ok && data.start_date && data.end_date) {
            document.getElementById("challengeDates").textContent = "Active Challenge: " + data.start_date + " through " + data.end_date;
        }
    } catch (err) {
        console.error("Challenge date load error:", err);
    }
}

async function loadBoard() {
    const status = document.getElementById("status");
    status.textContent = "Loading leaderboard...";
    try {
        const g = document.getElementById("group").value;
        const res = await fetch("/leaderboard/data?group=" + encodeURIComponent(g), {cache:"no-store"});
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        if (!data || data.ok !== true) throw new Error("Leaderboard API returned an error");
        leaderboardRows = Array.isArray(data.rows) ? data.rows : [];
        renderBoard();
    } catch (err) {
        leaderboardRows = [];
        document.getElementById("table").innerHTML = "";
        document.getElementById("viewTitle").textContent = "";
        status.textContent = "Leaderboard failed to load: " + err.message;
        console.error("Leaderboard Error:", err);
    }
}

window.addEventListener("load", async () => {
    await loadChallengeDates();
    await loadBoard();
});
</script>

</body>
</html>
"""


# =========================================================
# SYNC
# =========================================================

@app.post("/sync")
def sync_clients(payload: dict):
    """
    Synchronize local TSHRT clients to the cloud.

    Production identity rule:
        The incoming client_id is authoritative.
        Local TSHRT sends permanent Last_First IDs.

    If another cloud row has the same display name under a different ID:
        1. Preserve its attendance.
        2. Preserve its strongest score values.
        3. Remove the obsolete client row.
        4. Upsert the incoming permanent ID.
    """

    conn = get_conn()
    cur = conn.cursor()

    clients = payload.get("clients", [])
    received = 0
    duplicates_removed = 0
    attendance_moved = 0
    attendance_collisions = 0

    try:
        cur.execute("BEGIN")

        for c in clients:
            incoming_id = str(c.get("client_id", "")).strip()
            display_name = str(c.get("display_name", "")).strip()

            if not incoming_id or not display_name:
                continue

            tests = c.get("tests", [])

            baseline = 0.0
            latest = 0.0

            valid_scores = []
            for test in tests:
                if not isinstance(test, dict):
                    continue

                score = test.get("score")
                if score is None:
                    continue

                try:
                    valid_scores.append(float(score))
                except (TypeError, ValueError):
                    continue

            if valid_scores:
                baseline = valid_scores[0]
                latest = valid_scores[-1]

            snapshot = latest - baseline
            incoming_previous = float(c.get("previous_total", 0) or 0)

            old_rows = cur.execute("""
                SELECT
                    client_id,
                    COALESCE(baseline_score, 0) AS baseline_score,
                    COALESCE(snapshot_score, 0) AS snapshot_score,
                    COALESCE(previous_total, 0) AS previous_total
                FROM clients
                WHERE LOWER(TRIM(COALESCE(display_name, '')))
                      = LOWER(TRIM(?))
                  AND client_id <> ?
            """, (display_name, incoming_id)).fetchall()

            for old_row in old_rows:
                old_id = old_row["client_id"]

                baseline = max(
                    baseline,
                    float(old_row["baseline_score"] or 0)
                )
                snapshot = max(
                    snapshot,
                    float(old_row["snapshot_score"] or 0)
                )
                incoming_previous = max(
                    incoming_previous,
                    float(old_row["previous_total"] or 0)
                )

                old_attendance = cur.execute("""
                    SELECT
                        attended_date,
                        COALESCE(present, 1) AS present,
                        COALESCE(finalized, 0) AS finalized
                    FROM attendance
                    WHERE client_id = ?
                """, (old_id,)).fetchall()

                for row in old_attendance:
                    existing = cur.execute("""
                        SELECT id
                        FROM attendance
                        WHERE client_id = ?
                          AND attended_date = ?
                        LIMIT 1
                    """, (
                        incoming_id,
                        row["attended_date"]
                    )).fetchone()

                    if existing:
                        cur.execute("""
                            UPDATE attendance
                            SET present = MAX(COALESCE(present, 1), ?),
                                finalized = MAX(COALESCE(finalized, 0), ?)
                            WHERE client_id = ?
                              AND attended_date = ?
                        """, (
                            int(row["present"] or 1),
                            int(row["finalized"] or 0),
                            incoming_id,
                            row["attended_date"]
                        ))
                        attendance_collisions += 1
                    else:
                        cur.execute("""
                            INSERT INTO attendance (
                                client_id,
                                attended_date,
                                present,
                                finalized
                            )
                            VALUES (?, ?, ?, ?)
                        """, (
                            incoming_id,
                            row["attended_date"],
                            int(row["present"] or 1),
                            int(row["finalized"] or 0)
                        ))
                        attendance_moved += 1

                cur.execute(
                    "DELETE FROM attendance WHERE client_id = ?",
                    (old_id,)
                )
                cur.execute(
                    "DELETE FROM clients WHERE client_id = ?",
                    (old_id,)
                )

                duplicates_removed += 1

            cur.execute("""
                INSERT INTO clients (
                    client_id,
                    display_name,
                    first_name,
                    last_name,
                    group_name,
                    baseline_score,
                    snapshot_score,
                    previous_total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    group_name = excluded.group_name,
                    baseline_score = excluded.baseline_score,
                    snapshot_score = excluded.snapshot_score,
                    previous_total = excluded.previous_total
            """, (
                incoming_id,
                display_name,
                c.get("first_name"),
                c.get("last_name"),
                c.get("group_name"),
                float(baseline),
                float(snapshot),
                float(incoming_previous)
            ))

            received += 1

        conn.commit()

        return {
            "ok": True,
            "received": received,
            "duplicates_removed": duplicates_removed,
            "attendance_moved": attendance_moved,
            "attendance_collisions": attendance_collisions
        }

    except Exception as exc:
        conn.rollback()

        return {
            "ok": False,
            "error": str(exc),
            "message": "Sync failed. Transaction rolled back."
        }

    finally:
        conn.close()



# =========================================================
# ATTENDANCE UI
# =========================================================

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>TSHRT Attendance Board</title>
<style>
body { background:#0f172a; color:white; font-family:Arial, sans-serif; margin:0; padding:18px; }
h2 { margin:0 0 16px 0; }
.controls { margin-bottom:16px; line-height:2.0; }
table { border-collapse:collapse; }
td, th { border:1px solid #334155; padding:8px; text-align:center; }
.name { text-align:left; background:#1f2937; min-width:220px; position:sticky; left:0; z-index:2; }
th { background:#1e293b; font-size:12px; min-width:110px; vertical-align:bottom; }
.cell { width:40px; height:40px; cursor:pointer; background:#0b1836; }
.active { background:#22c55e; }
.finalized-col { box-shadow: inset 0 0 0 2px #d4af37; }
.locked { background:#475569; cursor:not-allowed; }
.wrap { overflow-x:auto; margin-top:12px; }
button { margin-right:6px; }
.legend { margin-top:10px; font-size:12px; color:#cbd5e1; }
#dateSelector { margin-top:10px; }
.status { margin:10px 0; color:#cbd5e1; font-size:13px; }
</style>
</head>
<body>

<h2>TSHRT Attendance Board</h2>

<div class="controls">
Group:
<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>

Start: <input type="date" id="start" value="2026-04-22">
End: <input type="date" id="end" value="2026-06-17">

Days:
<label><input type="checkbox" class="daybox" value="0">Sun</label>
<label><input type="checkbox" class="daybox" value="1" checked>Mon</label>
<label><input type="checkbox" class="daybox" value="2">Tue</label>
<label><input type="checkbox" class="daybox" value="3" checked>Wed</label>
<label><input type="checkbox" class="daybox" value="4">Thu</label>
<label><input type="checkbox" class="daybox" value="5">Fri</label>
<label><input type="checkbox" class="daybox" value="6">Sat</label>

<button onclick="loadBoard()">Load</button>
<button onclick="saveBoard()">Save</button>
<button onclick="finalizeSelected()">Finalize Selected Dates</button>
<button onclick="unfinalizeDate()">Unfinalize</button>
<button onclick="wakeServer()">Wake</button>
</div>

<div id="status" class="status">Loading attendance board...</div>

<h3 style="margin-top:10px;">Finalize Dates</h3>
<div id="dateSelector" style="
    margin-top:15px;
    padding:10px;
    border:1px solid #334155;
    background:#111827;
    border-radius:8px;
"></div>

<div class="legend">Gold border = finalized / locked date.</div>

<div class="wrap">
    <table id="grid"></table>
</div>

<script>
let state = {
    clients: [],
    dates: [],
    selected: {},
    finalizedDates: new Set(),
    specialDates: new Set(),
    noClassDates: new Set()
};

function setStatus(message) {
    const el = document.getElementById("status");
    if (el) {
        el.textContent = message;
    }
}

async function fetchJsonWithTimeout(url, timeoutMs = 8000) {

    const controller = new AbortController();

    const timeout = setTimeout(() => {
        controller.abort();
    }, timeoutMs);

    try {

        const response = await fetch(url, {
            signal: controller.signal
        });

        clearTimeout(timeout);

        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }

        return await response.json();

    } catch(err) {

        clearTimeout(timeout);
        throw err;
    }
}

function getSelectedDays() {
    return Array.from(document.querySelectorAll(".daybox:checked")).map(function(c) {
        return parseInt(c.value);
    });
}

function buildDates() {
    const startValue = document.getElementById("start").value;
    const endValue = document.getElementById("end").value;

    if (!startValue || !endValue) {
        return [];
    }

    const selectedDays = getSelectedDays();

    if (selectedDays.length === 0) {
        return [];
    }

    const dates = [];
    let cursor = new Date(startValue + "T12:00:00");
    const end = new Date(endValue + "T12:00:00");

    let safetyCounter = 0;

    while (cursor <= end && safetyCounter < 400) {
        const y = cursor.getFullYear();
        const m = String(cursor.getMonth() + 1).padStart(2, "0");
        const d = String(cursor.getDate()).padStart(2, "0");
        const dateStr = y + "-" + m + "-" + d;

        const isRegularDay = selectedDays.indexOf(cursor.getDay()) !== -1;
        const isSpecialDay = state.specialDates.has(dateStr);
        const isNoClassDay = state.noClassDates.has(dateStr);

        if (!isNoClassDay && (isRegularDay || isSpecialDay)) {
            dates.push(dateStr);
        }

        cursor.setDate(cursor.getDate() + 1);
        safetyCounter += 1;
    }

    return dates;
}

function formatHeaderDate(dateStr) {
    const dt = new Date(dateStr + "T12:00:00");
    const weekdays = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
    const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    const dayName = weekdays[dt.getDay()];
    const dayNum = dt.getDate();
    const monthName = months[dt.getMonth()];
    const yearShort = String(dt.getFullYear()).slice(-2);
    return dayName + ", " + dayNum + " " + monthName + " " + yearShort;
}

function safeDisplayName(c) {
    const last = c.last_name || "";
    const first = c.first_name || "";

    if (last || first) {
        let name = (last + ", " + first).trim();

        if (name.charAt(0) === ",") {
            name = name.substring(1).trim();
        }

        return name;
    }

    return c.display_name || "Unknown";
}

async function loadBoard() {
    try {
        setStatus("Loading clients...");

        const groupName = document.getElementById("group").value;

        state.dates = buildDates();

        const clientsData = await fetchJsonWithTimeout(
            "/attendance/data?group=" + encodeURIComponent(groupName),
            8000
        );

        if (!clientsData.ok) {
            throw new Error("Client load failed");
        }

        state.clients = clientsData.clients || [];

        setStatus("Loading saved attendance...");

        let attData = {
            ok: true,
            selected: {},
            finalized_dates: []
        };

        try {
            attData = await fetchJsonWithTimeout(
                "/attendance/load?group=" + encodeURIComponent(groupName),
                8000
            );
        } catch (attendanceError) {
            console.warn("Attendance load warning:", attendanceError);
            attData = {
                ok: true,
                selected: {},
                finalized_dates: []
            };
        }

        state.selected = attData.selected || {};
        state.finalizedDates = new Set(attData.finalized_dates || []);

        render();

        setStatus("Loaded " + state.clients.length + " clients and " + state.dates.length + " class dates.");
    } catch (err) {
        console.error("LOAD ERROR:", err);
        setStatus("Load failed: " + err.message);
        renderEmpty();
    }
}

function renderEmpty() {
    console.log("Rendering Empty Grid...");
    document.getElementById("grid").innerHTML = "";
    console.log("Empty Grid Rendered");
}

function render() {
    let html = "<tr><th class='name'>Name</th>";

    for (let i = 0; i < state.dates.length; i++) {
        const dateStr = state.dates[i];
        const cls = state.finalizedDates.has(dateStr) ? "finalized-col" : "";
        html += "<th class='" + cls + "'>" + formatHeaderDate(dateStr) + "</th>";
    }

    html += "</tr>";

    for (let cIndex = 0; cIndex < state.clients.length; cIndex++) {
        const client = state.clients[cIndex];

        if (!client || !client.client_id) {
            continue;
        }

        html += "<tr>";
        html += "<td class='name'>" + safeDisplayName(client) + "</td>";

        for (let dIndex = 0; dIndex < state.dates.length; dIndex++) {
            const dateStr = state.dates[dIndex];
            const key = client.client_id + "|" + dateStr;
            const locked = state.finalizedDates.has(dateStr);

            let classes = state.selected[key] ? "cell active" : "cell";

            if (locked) {

                classes += " locked finalized-col";

                html += "<td class='" + classes + "'></td>";

            } else {

               html += `<td class="${classes}" onclick="toggleCell('${client.client_id}','${dateStr}')">&nbsp;</td>`;

            }
        }

        html += "</tr>";
    }

    document.getElementById("grid").innerHTML = html;

    let selectorHTML = "<b>Select Dates to Finalize:</b><br>";

    for (let i = 0; i < state.dates.length; i++) {
        const dateStr = state.dates[i];
        const checked = state.finalizedDates.has(dateStr) ? "checked" : "";

        selectorHTML += "<label style='margin-right:10px;'>";
        selectorHTML += "<input type='checkbox' class='finalizeBox' value='" + dateStr + "' " + checked + "> ";
        selectorHTML += formatHeaderDate(dateStr);
        selectorHTML += "</label><br>";
    }

    document.getElementById("dateSelector").innerHTML = selectorHTML;
}

function toggleCell(clientId, dateStr) {
    if (state.finalizedDates.has(dateStr)) {
        return;
    }

    const key = clientId + "|" + dateStr;

    if (state.selected[key]) {
        delete state.selected[key];
    } else {
        state.selected[key] = true;
    }

    render();
}

async function saveBoard() {
    try {
        const groupName = document.getElementById("group").value;
        const selectedRecords = [];

        for (const key in state.selected) {
            const parts = key.split("|");

            if (parts.length !== 2) {
                continue;
            }

            selectedRecords.push({
                client_id: parts[0],
                attended_date: parts[1]
            });
        }

        const response = await fetch("/attendance/save", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                group: groupName,
                selected_records: selectedRecords
            })
        });

        const data = await response.json();

        if (!response.ok || data.ok === false) {
            throw new Error("Save failed");
        }

        alert("Saved " + data.saved_count + " attendance records.");
        await loadBoard();
    } catch (err) {
        console.error("SAVE ERROR:", err);
        alert("Save failed. Press F12 and check Console.");
    }
}

async function finalizeSelected() {
    const boxes = document.querySelectorAll(".finalizeBox:checked");
    const dates = Array.from(boxes).map(function(b) {
        return b.value;
    });

    if (dates.length === 0) {
        alert("No dates selected.");
        return;
    }

    try {
        await saveBoard();

        const response = await fetch("/attendance/finalize_bulk", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ dates: dates })
        });

        const data = await response.json();

        if (!response.ok || data.ok === false) {
            throw new Error("Finalize failed");
        }

        alert("Finalized " + dates.length + " dates.");
        await loadBoard();
    } catch (err) {
        console.error("FINALIZE ERROR:", err);
        alert("Finalize failed.");
    }
}

async function unfinalizeDate() {
    const dateStr = prompt("Enter date to unfinalize (YYYY-MM-DD)");

    if (!dateStr) {
        return;
    }

    try {
        const response = await fetch("/attendance/unfinalize", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ date: dateStr })
        });

        const data = await response.json();

        if (!response.ok || data.ok === false) {
            throw new Error("Unfinalize failed");
        }

        alert("Unfinalized " + dateStr);
        await loadBoard();
    } catch (err) {
        console.error("UNFINALIZE ERROR:", err);
        alert("Unfinalize failed.");
    }
}

async function wakeServer() {
    try {
        await fetch("/wake");
        alert("Server Awake");
    } catch (err) {
        console.error("WAKE ERROR:", err);
        alert("Wake failed.");
    }
}

async function loadActiveChallenge(){
    try{
        const r=await fetch("/challenge/active");
        const d=await r.json();
        if(d.ok){
            document.getElementById("start").value=d.start_date;
            document.getElementById("end").value=d.end_date;
            state.specialDates = new Set(d.special_class_dates || []);
            state.noClassDates = new Set(d.no_class_dates || []);
        }
    }catch(e){
        console.warn(e);
    }
}

window.onload = async function() {

    console.log("TSHRT Attendance Script Started");

    try {

        await loadActiveChallenge();
        await loadBoard();

        console.log("Board Loaded Successfully");

    } catch(err) {

        console.error("WINDOW LOAD ERROR:", err);

        setStatus("Window load failed: " + err.message);

    }
};
</script>

</body>
</html>
"""


# =========================================================
# CHALLENGE MANAGEMENT (SAFE ADD)
# =========================================================

@app.post("/challenge/close")
def close_challenge():
    conn = get_conn()
    cur = conn.cursor()

    start_date, end_date = get_active_challenge_dates(cur)
    if not start_date or not end_date:
        return {"ok": False, "message": "No active challenge found"}

    rows = cur.execute("""
        SELECT client_id,
               COALESCE(baseline_score,0) AS baseline_score,
               COALESCE(snapshot_score,0) AS snapshot_score,
               COALESCE(previous_total,0) AS previous_total
        FROM clients
    """).fetchall()

    for r in rows:
        client_id = r["client_id"]
        baseline = r["baseline_score"]
        snapshot = r["snapshot_score"]
        previous = r["previous_total"]

        att = cur.execute("""
            SELECT COUNT(*)
            FROM attendance
            WHERE client_id = ?
              AND COALESCE(present,1) = 1
              AND COALESCE(finalized,0) = 1
              AND attended_date >= ?
              AND attended_date <= ?
        """, (client_id, start_date, end_date)).fetchone()[0]

        current_total = baseline + snapshot + att
        new_lifetime = previous + current_total

        cur.execute("""
            UPDATE clients
            SET previous_total = ?,
                baseline_score = 0,
                snapshot_score = 0,
                challenge_active = 0
            WHERE client_id = ?
        """, (new_lifetime, client_id))

    cur.execute("""
        UPDATE challenges
        SET active = 0
        WHERE active = 1
    """)

    conn.commit()
    conn.close()

    return {"ok": True, "message": "Challenge closed successfully"}

@app.get("/debug/client/{client_id}")
def debug_client(client_id: str):

    conn = get_conn()
    cur = conn.cursor()

    row = cur.execute("""
        SELECT
            client_id,
            display_name,
            baseline_score,
            snapshot_score,
            previous_total
        FROM clients
        WHERE client_id = ?
    """, (client_id,)).fetchone()

    conn.close()

    if not row:
        return {"ok": False}

    r = dict(row)

    current = (
        (r["baseline_score"] or 0)
        + (r["snapshot_score"] or 0)
    )

    return {
        "ok": True,
        "client": r,
        "calculated_current_without_attendance": current
    }
@app.get("/admin/rebuild_lifetime")
def rebuild_lifetime():

    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT
            client_id,
            COALESCE(baseline_score,0) AS baseline_score,
            COALESCE(snapshot_score,0) AS snapshot_score
        FROM clients
    """).fetchall()

    updated = []

    for r in rows:

        client_id = r["client_id"]

        baseline = r["baseline_score"] or 0
        snapshot = r["snapshot_score"] or 0

        attendance = cur.execute("""
            SELECT COUNT(*)
            FROM attendance
            WHERE client_id = ?
              AND COALESCE(present,1) = 1
        """, (client_id,)).fetchone()[0]

        current = baseline + snapshot + attendance

        previous_total = max(0, current)

        cur.execute("""
            UPDATE clients
            SET previous_total = ?
            WHERE client_id = ?
        """, (previous_total, client_id))

        updated.append({
            "client_id": client_id,
            "previous_total": previous_total
        })

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "updated": updated
    }
@app.post("/challenge/start")
def start_challenge(start_date: str, weeks: int = 8):
    conn = get_conn()
    cur = conn.cursor()

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        conn.close()
        return {"ok": False, "message": "Invalid start_date format. Use YYYY-MM-DD"}

    end_dt = start_dt + timedelta(weeks=weeks)

    cur.execute("""
        UPDATE challenges
        SET active = 0
        WHERE active = 1
    """)

    cur.execute("""
        INSERT INTO challenges (start_date, end_date, active)
        VALUES (?, ?, 1)
    """, (start_date, end_dt.strftime("%Y-%m-%d")))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "start": start_date,
        "end": end_dt.strftime("%Y-%m-%d"),
        "weeks": weeks,
        "message": "New challenge scheduled"
    }



# =========================================================
# ADMIN - DUPLICATE CLIENT MERGE
# TEMPORARY PRODUCTION REPAIR ENDPOINT
# =========================================================

@app.get("/admin/merge_duplicate_clients")
def merge_duplicate_clients(execute: bool = False):
    """
    Preview or execute a safe merge of duplicate cloud clients.

    Canonical rule for TSHRT:
        Keep Last_First because that matches permanent client_id values,
        local JSON records, cloud_sync, reports, and the rest of TSHRT.

    Preview only:
        /admin/merge_duplicate_clients

    Execute:
        /admin/merge_duplicate_clients?execute=true

    Safety rules:
    - Preview mode makes no changes.
    - Execute mode creates a database backup first.
    - All changes occur inside one transaction.
    - Any verification failure rolls back the transaction.
    - Attendance rows are merged without violating UNIQUE(client_id, attended_date).
    - All tables with a client_id column are updated to the kept ID.
    - Safe to rerun after completion.
    """

    import re
    import shutil
    from pathlib import Path
    from datetime import datetime

    SCORE_COLUMNS = [
        "baseline_score",
        "snapshot_score",
        "previous_total",
        "challenge_active",
    ]

    LEGACY_CLIENT_ALIASES = {
        # Historical attendance alias left behind from early Viviana cleanup.
        # Must be merged through merge_attendance() so UNIQUE(client_id, attended_date) collisions are handled safely.
        "Viviana_Example": "Viviana_Fuentes",
    }

    def clean_token(value):
        value = (value or "").strip()
        value = re.sub(r"[^A-Za-z0-9]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value

    def split_display_name(display_name):
        display_name = (display_name or "").strip()
        if not display_name:
            return "", ""

        if "," in display_name:
            last, first = [p.strip() for p in display_name.split(",", 1)]
            return first, last

        parts = display_name.split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        if len(parts) == 1:
            return parts[0], ""
        return "", ""

    def last_first_id_for_row(row):
        first = (row["first_name"] or "").strip() if "first_name" in row.keys() else ""
        last = (row["last_name"] or "").strip() if "last_name" in row.keys() else ""

        if not first or not last:
            parsed_first, parsed_last = split_display_name(row["display_name"] if "display_name" in row.keys() else "")
            first = first or parsed_first
            last = last or parsed_last

        first = clean_token(first)
        last = clean_token(last)

        if first and last:
            return f"{last}_{first}"
        if first:
            return first
        return clean_token(row["display_name"] if "display_name" in row.keys() else row["client_id"])

    def get_columns(cur, table):
        return [r["name"] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]

    def get_client_id_tables(cur):
        rows = cur.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """).fetchall()

        tables = []
        for r in rows:
            table = r["name"]
            if "client_id" in get_columns(cur, table):
                tables.append(table)
        return tables

    def count_attendance(cur, client_id):
        return cur.execute("""
            SELECT COUNT(*)
            FROM attendance
            WHERE client_id = ?
              AND COALESCE(present,1) = 1
        """, (client_id,)).fetchone()[0]

    def score_strength(cur, row):
        client_id = row["client_id"]
        baseline = float(row["baseline_score"] or 0) if "baseline_score" in row.keys() else 0
        snapshot = float(row["snapshot_score"] or 0) if "snapshot_score" in row.keys() else 0
        previous = float(row["previous_total"] or 0) if "previous_total" in row.keys() else 0
        attendance = count_attendance(cur, client_id)
        return previous + baseline + snapshot + attendance

    def choose_keep_id(cur, records):
        """
        Production rule:
        1. Keep Last_First if it already exists.
        2. If Last_First does not exist, keep the strongest existing row.
        """
        ids = {r["client_id"] for r in records if r["client_id"]}

        # Prefer Last_First derived from the actual row names.
        for r in records:
            candidate = last_first_id_for_row(r)
            if candidate in ids:
                return candidate

        # Fallback: strongest record, ties favor longer descriptive ID and not placeholder.
        scored = []
        for r in records:
            cid = r["client_id"]
            placeholder_penalty = -1 if str(cid).lower() in ("new_client", "test", "sample") else 0
            scored.append((
                score_strength(cur, r),
                placeholder_penalty,
                len(cid or ""),
                cid,
            ))
        scored.sort(reverse=True)
        return scored[0][3]

    def build_plans(cur):
        rows = cur.execute("""
            SELECT *
            FROM clients
            WHERE TRIM(COALESCE(display_name,'')) <> ''
            ORDER BY display_name, client_id
        """).fetchall()

        groups = {}
        for r in rows:
            key = (r["display_name"] or "").strip().lower()
            groups.setdefault(key, []).append(r)

        plans = []
        for _key, records in groups.items():
            ids = sorted({r["client_id"] for r in records if r["client_id"]})
            if len(ids) <= 1:
                continue

            keep_id = choose_keep_id(cur, records)
            remove_ids = [cid for cid in ids if cid != keep_id]

            plans.append({
                "display_name": records[0]["display_name"],
                "keep_id": keep_id,
                "remove_ids": remove_ids,
                "all_ids": ids,
                "canonical_rule": "Last_First preferred",
            })

        return plans

    def merge_attendance(cur, old_id, keep_id):
        moved = 0
        collisions = 0

        rows = cur.execute("""
            SELECT attended_date,
                   COALESCE(present,1) AS present,
                   COALESCE(finalized,0) AS finalized
            FROM attendance
            WHERE client_id = ?
        """, (old_id,)).fetchall()

        for r in rows:
            existing = cur.execute("""
                SELECT id
                FROM attendance
                WHERE client_id = ?
                  AND attended_date = ?
                LIMIT 1
            """, (keep_id, r["attended_date"])).fetchone()

            if existing:
                collisions += 1
                cur.execute("""
                    UPDATE attendance
                    SET present = MAX(COALESCE(present,1), ?),
                        finalized = MAX(COALESCE(finalized,0), ?)
                    WHERE client_id = ?
                      AND attended_date = ?
                """, (
                    int(r["present"] or 1),
                    int(r["finalized"] or 0),
                    keep_id,
                    r["attended_date"],
                ))

                cur.execute("""
                    DELETE FROM attendance
                    WHERE client_id = ?
                      AND attended_date = ?
                """, (old_id, r["attended_date"]))
            else:
                moved += 1
                cur.execute("""
                    UPDATE attendance
                    SET client_id = ?
                    WHERE client_id = ?
                      AND attended_date = ?
                """, (keep_id, old_id, r["attended_date"]))

        return moved, collisions

    def merge_client_scores(cur, old_id, keep_id):
        old_row = cur.execute("SELECT * FROM clients WHERE client_id = ?", (old_id,)).fetchone()
        keep_row = cur.execute("SELECT * FROM clients WHERE client_id = ?", (keep_id,)).fetchone()
        if not old_row or not keep_row:
            return False

        updates = {}
        for col in SCORE_COLUMNS:
            if col in old_row.keys() and col in keep_row.keys():
                old_value = float(old_row[col] or 0)
                keep_value = float(keep_row[col] or 0)
                updates[col] = max(old_value, keep_value)

        if "challenge_active" in updates:
            updates["challenge_active"] = int(updates["challenge_active"])

        if updates:
            set_clause = ", ".join([f"{col} = ?" for col in updates.keys()])
            params = list(updates.values()) + [keep_id]
            cur.execute(f"UPDATE clients SET {set_clause} WHERE client_id = ?", params)

        return True

    def update_other_client_id_tables(cur, tables, old_id, keep_id):
        updated = 0
        for table in tables:
            if table in ("clients", "attendance"):
                continue
            count = cur.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE client_id = ?',
                (old_id,)
            ).fetchone()[0]
            if count:
                cur.execute(
                    f'UPDATE "{table}" SET client_id = ? WHERE client_id = ?',
                    (keep_id, old_id)
                )
                updated += count
        return updated

    def duplicate_groups(cur):
        return cur.execute("""
            SELECT LOWER(TRIM(display_name)) AS name_key, COUNT(*) AS c
            FROM clients
            WHERE TRIM(COALESCE(display_name,'')) <> ''
            GROUP BY LOWER(TRIM(display_name))
            HAVING COUNT(*) > 1
        """).fetchall()

    def orphan_refs(cur, tables):
        valid_ids = {
            r["client_id"]
            for r in cur.execute("SELECT client_id FROM clients").fetchall()
        }
        problems = []
        for table in tables:
            if table == "clients":
                continue
            rows = cur.execute(
                f'SELECT DISTINCT client_id FROM "{table}" WHERE client_id IS NOT NULL'
            ).fetchall()
            for r in rows:
                if r["client_id"] not in valid_ids:
                    problems.append({
                        "table": table,
                        "client_id": r["client_id"],
                    })
        return problems

    conn = get_conn()
    cur = conn.cursor()

    try:
        tables = get_client_id_tables(cur)
        plans = build_plans(cur)

        report = {
            "ok": True,
            "execute": execute,
            "mode": "EXECUTE" if execute else "PREVIEW_ONLY",
            "canonical_rule": "Last_First preferred",
            "backup": None,
            "tables_with_client_id": tables,
            "clients_before": cur.execute("SELECT COUNT(*) FROM clients").fetchone()[0],
            "duplicate_groups_before": len(duplicate_groups(cur)),
            "plans_found": len(plans),
            "plans": plans,
            "summary": {
                "attendance_moved": 0,
                "attendance_collisions": 0,
                "other_rows_updated": 0,
                "clients_removed": 0,
                "skipped": 0,
            },
            "verification": {},
        }

        if not execute:
            conn.close()
            return report

        db_file = Path(DB_PATH)
        backup_dir = db_file.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"cloud_backup_before_duplicate_merge_{stamp}.db"
        shutil.copy2(DB_PATH, backup_path)
        report["backup"] = str(backup_path)

        cur.execute("BEGIN")

        for plan in plans:
            keep_id = plan["keep_id"]

            for old_id in plan["remove_ids"]:
                if old_id == keep_id:
                    report["summary"]["skipped"] += 1
                    continue

                old_exists = cur.execute("SELECT 1 FROM clients WHERE client_id = ?", (old_id,)).fetchone()
                keep_exists = cur.execute("SELECT 1 FROM clients WHERE client_id = ?", (keep_id,)).fetchone()

                if not old_exists or not keep_exists:
                    report["summary"]["skipped"] += 1
                    continue

                moved, collisions = merge_attendance(cur, old_id, keep_id)
                report["summary"]["attendance_moved"] += moved
                report["summary"]["attendance_collisions"] += collisions

                report["summary"]["other_rows_updated"] += update_other_client_id_tables(
                    cur, tables, old_id, keep_id
                )

                merge_client_scores(cur, old_id, keep_id)

                cur.execute("DELETE FROM clients WHERE client_id = ?", (old_id,))
                report["summary"]["clients_removed"] += 1

        # Normalize known legacy aliases through the same collision-safe attendance merge logic.
        # Do NOT use a direct UPDATE on attendance here; the attendance table has
        # UNIQUE(client_id, attended_date), and direct updates can collide.
        for alias_old_id, alias_keep_id in LEGACY_CLIENT_ALIASES.items():

            keep_exists = cur.execute(
                "SELECT 1 FROM clients WHERE client_id = ?",
                (alias_keep_id,)
            ).fetchone()

            if not keep_exists:
                report["summary"]["skipped"] += 1
                continue

            moved, collisions = merge_attendance(cur, alias_old_id, alias_keep_id)
            report["summary"]["attendance_moved"] += moved
            report["summary"]["attendance_collisions"] += collisions

            report["summary"]["other_rows_updated"] += update_other_client_id_tables(
                cur, tables, alias_old_id, alias_keep_id
            )

        integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
        remaining_duplicates = duplicate_groups(cur)
        remaining_orphans = orphan_refs(cur, tables)
        clients_after = cur.execute("SELECT COUNT(*) FROM clients").fetchone()[0]

        report["clients_after"] = clients_after
        report["duplicate_groups_after"] = len(remaining_duplicates)
        report["verification"] = {
            "sqlite_integrity": integrity,
            "remaining_duplicate_groups": [dict(r) for r in remaining_duplicates],
            "orphan_references": remaining_orphans,
            "passed": integrity == "ok" and len(remaining_duplicates) == 0 and len(remaining_orphans) == 0,
        }

        if not report["verification"]["passed"]:
            conn.rollback()
            report["ok"] = False
            report["rolled_back"] = True
            report["message"] = "Verification failed. Transaction rolled back."
            conn.close()
            return report

        conn.commit()
        report["rolled_back"] = False
        report["message"] = "Duplicate client merge completed successfully."
        conn.close()
        return report

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        return {
            "ok": False,
            "execute": execute,
            "error": str(e),
            "message": "Merge failed. Transaction rolled back.",
        }

# =========================================================
# STARTUP
# =========================================================
# =========================================================
# PHONE ATTENDANCE — PHASE 1
# =========================================================

@app.get("/phone-attendance", response_class=HTMLResponse)
def phone_attendance(date: Optional[str] = None):
    """
    Mobile-friendly instructor attendance page.
    Uses the existing TSHRT clients and attendance system.
    """

    # ---------------------------------------------------------
    # CLASS-DAY SAFETY CHECK
    # ---------------------------------------------------------

    schedule = get_active_class_schedule(date)

    today = schedule.get(
        "date",
        datetime.now().strftime("%Y-%m-%d")
    )

    if not schedule.get("is_class_day", False):

        reason = schedule.get("reason", "NOT_SCHEDULED")

        messages = {
            "NO_ACTIVE_CHALLENGE":
                "There is currently no active TSHRT challenge.",

            "OUTSIDE_ACTIVE_CHALLENGE":
                "Today is outside the active challenge dates.",

            "NO_CLASS_DATE":
                "Today has been designated as a NO-CLASS day.",

            "NOT_SCHEDULED":
                "Today is not a scheduled ABC Class day.",

            "INVALID_DATE":
                "The attendance date is invalid."
        }

        message = messages.get(
            reason,
            "Attendance is not available today."
        )

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>TSHRT Attendance</title>

    <style>
        body {{
            margin:0;
            background:#111;
            color:white;
            font-family:Arial, sans-serif;
            text-align:center;
        }}

        .header {{
            background:#000;
            border-bottom:4px solid #d4af37;
            padding:25px 15px;
        }}

        .header h1 {{
            margin:0;
            color:#d4af37;
            font-size:30px;
        }}

        .container {{
            max-width:600px;
            margin:auto;
            padding:50px 20px;
        }}

        .status {{
            border:2px solid #d4af37;
            border-radius:12px;
            padding:30px 20px;
            background:#1c1c1c;
        }}

        .status h2 {{
            color:#d4af37;
            font-size:27px;
            margin-top:0;
        }}

        .date {{
            font-size:21px;
            margin:20px 0;
        }}

        .message {{
            font-size:18px;
            line-height:1.5;
            color:#ddd;
        }}

        .locked {{
            margin-top:25px;
            font-weight:bold;
            color:#aaa;
        }}
    </style>
</head>

<body>

<div class="header">
    <h1>TSHRT</h1>
    <p>ABC Class Attendance</p>
</div>

<div class="container">

    <form method="get" action="/phone-attendance" style="margin-bottom:20px;">
        <label for="date" style="display:block;margin-bottom:8px;font-weight:bold;">Attendance Date</label>
        <input id="date" name="date" type="date" value="{today}"
               style="font-size:18px;padding:12px;border-radius:8px;border:1px solid #666;background:#222;color:white;">
        <button type="submit"
                style="font-size:18px;padding:12px 16px;margin-left:6px;border:0;border-radius:8px;background:#d4af37;color:#000;font-weight:bold;">
            LOAD DATE
        </button>
    </form>

    <div class="status">

        <h2>NO CLASS TODAY</h2>

        <div class="date">
            {today}
        </div>

        <div class="message">
            {message}
        </div>

        <div class="locked">
            Attendance entry is disabled.
        </div>

    </div>

</div>

</body>
</html>
"""

    conn = get_conn()
    cur = conn.cursor()

    clients = cur.execute("""
        SELECT client_id, display_name, first_name, last_name
        FROM clients
        WHERE LOWER(TRIM(COALESCE(group_name, ''))) = 'abc class'
        ORDER BY last_name, first_name, display_name
    """).fetchall()

    present_rows = cur.execute("""
        SELECT a.client_id
        FROM attendance a
        JOIN clients c ON c.client_id = a.client_id
        WHERE a.attended_date = ?
          AND COALESCE(a.present, 1) = 1
          AND LOWER(TRIM(COALESCE(c.group_name, ''))) = 'abc class'
    """, (today,)).fetchall()

    present_ids = {row["client_id"] for row in present_rows}

    # ---------------------------------------------------------
    # 13C — INSTRUCTOR-CONTROLLED STUDENT QR SESSION
    # ---------------------------------------------------------
    session_row = cur.execute("""
        SELECT is_open, opened_at, closed_at
        FROM attendance_checkin_sessions
        WHERE session_date = ?
    """, (today,)).fetchone()

    session_is_open = bool(session_row and session_row["is_open"] == 1)
    session_status = "OPEN" if session_is_open else "CLOSED"
    session_action = "close" if session_is_open else "open"
    session_button = "CLOSE CLIENT CHECK-IN" if session_is_open else "OPEN CLIENT CHECK-IN"
    session_color = "#2e7d32" if session_is_open else "#8b1e1e"

    conn.close()

    student_buttons = ""

    for row in clients:
        client_id = row["client_id"]

        display_name = (row["display_name"] or "").strip()

        if not display_name:
            first = (row["first_name"] or "").strip()
            last = (row["last_name"] or "").strip()
            display_name = f"{first} {last}".strip()

        checked = "checked" if client_id in present_ids else ""

        student_buttons += f"""
        <label class="student">
            <input type="checkbox"
                   name="client_ids"
                   value="{client_id}"
                   {checked}>
            <span>{display_name}</span>
        </label>
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>TSHRT Attendance</title>

    <style>
        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            background: #111;
            color: white;
            font-family: Arial, sans-serif;
        }}

        .header {{
            background: #000;
            border-bottom: 4px solid #d4af37;
            padding: 22px 15px;
            text-align: center;
        }}

        .header h1 {{
            color: #d4af37;
            margin: 0;
            font-size: 28px;
        }}

        .header p {{
            margin: 6px 0 0;
            color: #ddd;
        }}

        .container {{
            max-width: 650px;
            margin: auto;
            padding: 15px;
        }}

        .date {{
            background: #222;
            border: 1px solid #444;
            padding: 14px;
            border-radius: 8px;
            margin-bottom: 15px;
            text-align: center;
            font-size: 18px;
        }}

        .student {{
            display: flex;
            align-items: center;
            background: #222;
            border: 1px solid #444;
            border-radius: 8px;
            margin-bottom: 9px;
            padding: 15px;
            font-size: 19px;
            cursor: pointer;
        }}

        .student:has(input:checked) {{
            background: #3a3215;
            border: 2px solid #d4af37;
        }}

        .student input {{
            width: 24px;
            height: 24px;
            margin-right: 14px;
            accent-color: #d4af37;
        }}

        .save {{
            position: sticky;
            bottom: 10px;
            width: 100%;
            padding: 18px;
            margin-top: 15px;
            background: #d4af37;
            color: #000;
            border: none;
            border-radius: 8px;
            font-size: 20px;
            font-weight: bold;
            cursor: pointer;
        }}

        .count {{
            text-align: center;
            color: #bbb;
            margin-bottom: 12px;
        }}
    </style>
</head>

<body>

<div class="header">
    <h1>TSHRT</h1>
    <p>ABC Class Attendance</p>
</div>

<div class="container">

    <form method="get" action="/phone-attendance" style="margin-bottom:15px;text-align:center;">
        <label for="date" style="display:block;margin-bottom:8px;font-weight:bold;">Attendance Date</label>
        <input id="date" name="date" type="date" value="{today}"
               style="font-size:18px;padding:12px;border-radius:8px;border:1px solid #666;background:#222;color:white;">
        <button type="submit"
                style="font-size:18px;padding:12px 16px;margin-left:6px;border:0;border-radius:8px;background:#d4af37;color:#000;font-weight:bold;">
            LOAD DATE
        </button>
    </form>

    <div class="date">
        Attendance Date: <strong>{today}</strong>
    </div>

    <div style="background:#1c1c1c;border:2px solid #d4af37;border-radius:10px;padding:16px;margin-bottom:18px;text-align:center;">
        <div style="font-size:17px;color:#ddd;margin-bottom:8px;">Client Self Check-In</div>
        <div style="font-size:26px;font-weight:bold;color:{session_color};margin-bottom:12px;">{session_status}</div>
        <form method="post" action="/phone-attendance/checkin-session">
            <input type="hidden" name="attended_date" value="{today}">
            <input type="hidden" name="action" value="{session_action}">
            <button type="submit" style="width:100%;padding:15px;border:0;border-radius:8px;background:{session_color};color:white;font-size:18px;font-weight:bold;cursor:pointer;">
                {session_button}
            </button>
        </form>
        <div style="font-size:13px;color:#aaa;margin-top:10px;">
            Client self check-in can only be accepted while this session is OPEN.<br><br>
            <a href="/phone-attendance/pin-manager" style="color:#d4af37;font-weight:bold;">CLIENT PIN MANAGER</a>
        </div>
    </div>

    <div class="count">
        Select everyone present.
    </div>

    <form method="post" action="/phone-attendance/save">

        <input type="hidden"
               name="attended_date"
               value="{today}">

        {student_buttons}

        <button class="save" type="submit">
            SAVE ATTENDANCE
        </button>

    </form>

</div>

</body>
</html>
"""

init_db()
upgrade_db()
# =========================================================
# 13C — INSTRUCTOR OPEN / CLOSE STUDENT QR CHECK-IN
# =========================================================

@app.post("/phone-attendance/checkin-session", response_class=HTMLResponse)
def set_phone_checkin_session(
    attended_date: str = Form(...),
    action: str = Form(...)
):
    """Open or close the student QR check-in gate for one valid class date."""
    schedule = get_active_class_schedule(attended_date)
    if not schedule.get("is_class_day", False):
        return HTMLResponse(
            content=f"Student check-in cannot be changed for {attended_date}: not a valid class date.",
            status_code=400
        )

    action = (action or "").strip().lower()
    if action not in {"open", "close"}:
        return HTMLResponse(content="Invalid check-in session action.", status_code=400)

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()

    if action == "open":
        cur.execute("""
            INSERT INTO attendance_checkin_sessions
                (session_date, is_open, opened_at, closed_at)
            VALUES (?, 1, ?, NULL)
            ON CONFLICT(session_date) DO UPDATE SET
                is_open = 1,
                opened_at = excluded.opened_at,
                closed_at = NULL
        """, (attended_date, now_text))
    else:
        cur.execute("""
            INSERT INTO attendance_checkin_sessions
                (session_date, is_open, opened_at, closed_at)
            VALUES (?, 0, NULL, ?)
            ON CONFLICT(session_date) DO UPDATE SET
                is_open = 0,
                closed_at = excluded.closed_at
        """, (attended_date, now_text))

    conn.commit()
    conn.close()

    return HTMLResponse(
        content=f'''<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="1;url=/phone-attendance?date={attended_date}">
<title>TSHRT Check-In Session</title></head>
<body style="margin:0;background:#111;color:white;font-family:Arial,sans-serif;text-align:center;">
<div style="max-width:600px;margin:70px auto;padding:25px;">
<h1 style="color:#d4af37;">Student Check-In {action.upper()}</h1>
<p style="font-size:20px;">{attended_date}</p>
<p>Returning to Phone Attendance...</p>
<a href="/phone-attendance?date={attended_date}" style="color:#d4af37;">Return Now</a>
</div></body></html>'''
    )


# =========================================================
# 13D / 13E — CLIENT SELF CHECK-IN + PRIVATE PIN GATE
# =========================================================

PIN_ITERATIONS = 200_000


def _get_open_student_checkin_session(cur):
    return cur.execute("""SELECT session_date, opened_at FROM attendance_checkin_sessions WHERE is_open=1 ORDER BY COALESCE(opened_at,created_at) DESC,id DESC LIMIT 1""").fetchone()


def _hash_checkin_pin(pin: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), PIN_ITERATIONS).hex()


def _valid_pin(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 6


def _esc(value) -> str:
    return str(value or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")


@app.get("/phone-attendance/pin-manager", response_class=HTMLResponse)
def client_pin_manager():
    conn=get_conn(); cur=conn.cursor()
    clients=cur.execute("""SELECT client_id,display_name,first_name,last_name,checkin_pin_hash,checkin_pin_setup_allowed FROM clients WHERE LOWER(TRIM(COALESCE(group_name,'')))='abc class' ORDER BY last_name,first_name,display_name""").fetchall(); conn.close()
    rows=[]
    for c in clients:
        name=(c['display_name'] or '').strip() or f"{c['first_name'] or ''} {c['last_name'] or ''}".strip()
        has_pin=bool(c['checkin_pin_hash']); allowed=bool(c['checkin_pin_setup_allowed'])
        status="PIN ACTIVE" if has_pin else ("SETUP AUTHORIZED" if allowed else "NO PIN")
        action="reset" if has_pin else ("cancel" if allowed else "authorize")
        label="RESET PIN" if has_pin else ("CANCEL SETUP" if allowed else "AUTHORIZE PIN SETUP")
        rows.append(f'''<div class="row"><div><strong>{_esc(name)}</strong><br><span>{status}</span></div><form method="post" action="/phone-attendance/pin-manager"><input type="hidden" name="client_id" value="{_esc(c['client_id'])}"><input type="hidden" name="action" value="{action}"><button>{label}</button></form></div>''')
    return HTMLResponse(f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSHRT Client PIN Manager</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#111;color:#fff;font-family:Arial}}header{{background:#000;border-bottom:4px solid #d4af37;text-align:center;padding:20px}}h1{{color:#d4af37;margin:0}}main{{max-width:700px;margin:auto;padding:18px}}.row{{display:flex;justify-content:space-between;gap:12px;align-items:center;background:#1c1c1c;border:1px solid #555;border-radius:10px;padding:14px;margin:10px 0}}span{{color:#aaa;font-size:13px}}button{{background:#d4af37;border:0;border-radius:7px;padding:11px;font-weight:bold}}a{{color:#d4af37}}</style></head><body><header><h1>TSHRT</h1><p>Client PIN Manager</p></header><main><p>Authorize first-time setup or reset a forgotten PIN. PINs are never displayed.</p>{''.join(rows)}<p><a href="/phone-attendance">Return to Phone Attendance</a></p></main></body></html>''')


@app.post("/phone-attendance/pin-manager", response_class=HTMLResponse)
def client_pin_manager_action(client_id: str=Form(...), action: str=Form(...)):
    conn=get_conn(); cur=conn.cursor()
    exists=cur.execute("SELECT 1 FROM clients WHERE client_id=? AND LOWER(TRIM(COALESCE(group_name,'')))='abc class'",(client_id,)).fetchone()
    if not exists:
        conn.close(); return HTMLResponse("Invalid client.",status_code=400)
    if action=="authorize": cur.execute("UPDATE clients SET checkin_pin_setup_allowed=1 WHERE client_id=?",(client_id,))
    elif action=="reset": cur.execute("UPDATE clients SET checkin_pin_hash=NULL,checkin_pin_salt=NULL,checkin_pin_setup_allowed=1 WHERE client_id=?",(client_id,))
    elif action=="cancel": cur.execute("UPDATE clients SET checkin_pin_setup_allowed=0 WHERE client_id=?",(client_id,))
    else:
        conn.close(); return HTMLResponse("Invalid action.",status_code=400)
    conn.commit(); conn.close(); return HTMLResponse('<meta http-equiv="refresh" content="0;url=/phone-attendance/pin-manager">')


@app.get("/student-checkin", response_class=HTMLResponse)
def student_checkin_page():
    conn=get_conn(); cur=conn.cursor(); session=_get_open_student_checkin_session(cur)
    if not session:
        conn.close(); return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSHRT Client Check-In</title></head><body style="margin:0;background:#111;color:white;font-family:Arial;text-align:center"><div style="background:#000;border-bottom:4px solid #d4af37;padding:24px"><h1 style="color:#d4af37;margin:0">TSHRT</h1><p>Client Self Check-In</p></div><div style="max-width:600px;margin:55px auto;padding:20px"><h2>CHECK-IN CLOSED</h2><p>Your coach has not opened check-in.</p></div></body></html>''')
    session_date=session['session_date']; schedule=get_active_class_schedule(session_date)
    if not schedule.get('is_class_day',False):
        conn.close(); return HTMLResponse("Check-in is unavailable for this date.",status_code=409)
    clients=cur.execute("""SELECT client_id,display_name,first_name,last_name,checkin_pin_hash,checkin_pin_setup_allowed FROM clients WHERE LOWER(TRIM(COALESCE(group_name,'')))='abc class' ORDER BY last_name,first_name,display_name""").fetchall(); conn.close()
    options=['<option value="">-- SELECT YOUR NAME --</option>']
    for c in clients:
        name=(c['display_name'] or '').strip() or f"{c['first_name'] or ''} {c['last_name'] or ''}".strip(); mode='auth' if c['checkin_pin_hash'] else ('setup' if c['checkin_pin_setup_allowed'] else 'locked')
        options.append(f'<option value="{_esc(c["client_id"])}" data-mode="{mode}">{_esc(name)}</option>')
    return HTMLResponse(f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSHRT Client Check-In</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#111;color:#fff;font-family:Arial}}header{{background:#000;border-bottom:4px solid #d4af37;text-align:center;padding:22px}}h1{{color:#d4af37;margin:0}}main{{max-width:600px;margin:auto;padding:20px}}.card{{background:#1c1c1c;border:2px solid #d4af37;border-radius:12px;padding:22px}}select,input,button{{width:100%;font-size:20px;padding:15px;margin:9px 0;border-radius:8px}}button{{background:#d4af37;border:0;font-weight:bold}}.open{{color:#4caf50;text-align:center;font-size:24px;font-weight:bold}}#setup,#locked{{display:none}}small{{color:#aaa}}</style></head><body><header><h1>TSHRT</h1><p>Client Self Check-In</p></header><main><div class="card"><div class="open">CHECK-IN OPEN</div><p style="text-align:center">Attendance Date: <b>{session_date}</b></p><form method="post" action="/student-checkin"><select name="client_id" id="client" required>{''.join(options)}</select><div id="auth"><input type="password" inputmode="numeric" pattern="[0-9]*" name="pin" id="pin" placeholder="PRIVATE PIN" maxlength="6"></div><div id="setup"><p>Create your private 4–6 digit PIN.</p><input type="password" inputmode="numeric" pattern="[0-9]*" name="new_pin" id="newpin" placeholder="CREATE PIN" maxlength="6"><input type="password" inputmode="numeric" pattern="[0-9]*" name="confirm_pin" id="confirm" placeholder="CONFIRM PIN" maxlength="6"></div><div id="locked"><p>PIN setup has not been authorized. Ask your coach to authorize setup.</p></div><button id="submit">CHECK IN</button></form><small>Your PIN is private and is never displayed or stored in readable form.</small></div></main><script>const c=document.getElementById('client'),a=document.getElementById('auth'),s=document.getElementById('setup'),l=document.getElementById('locked'),b=document.getElementById('submit');function mode(){{let o=c.options[c.selectedIndex],m=o?o.dataset.mode:'';a.style.display=m==='auth'?'block':'none';s.style.display=m==='setup'?'block':'none';l.style.display=m==='locked'?'block':'none';b.style.display=m==='locked'?'none':'block';document.getElementById('pin').required=m==='auth';document.getElementById('newpin').required=m==='setup';document.getElementById('confirm').required=m==='setup';b.textContent=m==='setup'?'CREATE PIN & CHECK IN':'CHECK IN'}}c.addEventListener('change',mode);mode();</script></body></html>''')


@app.post("/student-checkin", response_class=HTMLResponse)
def student_checkin_submit(client_id: str=Form(...), pin: str=Form(""), new_pin: str=Form(""), confirm_pin: str=Form("")):
    conn=get_conn(); cur=conn.cursor(); session=_get_open_student_checkin_session(cur)
    if not session:
        conn.close(); return HTMLResponse("CHECK-IN CLOSED",status_code=409)
    session_date=session['session_date']; schedule=get_active_class_schedule(session_date)
    if not schedule.get('is_class_day',False): conn.close(); return HTMLResponse("Check-in is unavailable for this date.",status_code=409)
    c=cur.execute("""SELECT client_id,display_name,first_name,last_name,checkin_pin_hash,checkin_pin_salt,checkin_pin_setup_allowed FROM clients WHERE client_id=? AND LOWER(TRIM(COALESCE(group_name,'')))='abc class' LIMIT 1""",(client_id,)).fetchone()
    if not c: conn.close(); return HTMLResponse("Invalid client selection.",status_code=400)
    if c['checkin_pin_hash']:
        if not _valid_pin(pin) or not c['checkin_pin_salt']: conn.close(); return HTMLResponse("PIN REQUIRED",status_code=401)
        if not hmac.compare_digest(_hash_checkin_pin(pin,c['checkin_pin_salt']),c['checkin_pin_hash']): conn.close(); return HTMLResponse("INCORRECT PIN — attendance was not changed.",status_code=401)
    else:
        if not c['checkin_pin_setup_allowed']: conn.close(); return HTMLResponse("PIN setup has not been authorized by your coach.",status_code=403)
        if not _valid_pin(new_pin): conn.close(); return HTMLResponse("PIN must contain 4–6 digits.",status_code=400)
        if new_pin!=confirm_pin: conn.close(); return HTMLResponse("PIN entries do not match.",status_code=400)
        salt=secrets.token_hex(16); digest=_hash_checkin_pin(new_pin,salt); cur.execute("UPDATE clients SET checkin_pin_hash=?,checkin_pin_salt=?,checkin_pin_setup_allowed=0 WHERE client_id=?",(digest,salt,client_id))
    finalized=cur.execute("SELECT 1 FROM attendance WHERE attended_date=? AND COALESCE(finalized,0)=1 LIMIT 1",(session_date,)).fetchone()
    if finalized: conn.rollback(); conn.close(); return HTMLResponse("Attendance for this date has been finalized.",status_code=409)
    already=cur.execute("SELECT 1 FROM attendance WHERE client_id=? AND attended_date=? AND present=1",(client_id,session_date)).fetchone()
    if already: conn.commit(); conn.close(); return HTMLResponse("ALREADY CHECKED IN — no duplicate attendance was created.",status_code=200)
    cur.execute("""INSERT INTO attendance(client_id,attended_date,present,finalized) VALUES(?,?,1,0) ON CONFLICT(client_id,attended_date) DO UPDATE SET present=1""",(client_id,session_date)); conn.commit(); conn.close()
    name=(c['display_name'] or '').strip() or f"{c['first_name'] or ''} {c['last_name'] or ''}".strip()
    return HTMLResponse(f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSHRT Check-In Complete</title></head><body style="margin:0;background:#111;color:#fff;font-family:Arial;text-align:center"><div style="background:#000;border-bottom:4px solid #d4af37;padding:24px"><h1 style="color:#d4af37;margin:0">TSHRT</h1></div><div style="max-width:600px;margin:55px auto;padding:20px"><div style="background:#1c1c1c;border:2px solid #d4af37;border-radius:12px;padding:30px"><div style="font-size:64px">&#10003;</div><h2 style="color:#d4af37">CHECK-IN COMPLETE</h2><p style="font-size:23px"><b>{_esc(name)}</b></p><p>Present for <b>{session_date}</b></p><p style="color:#aaa">You may close this page.</p></div></div></body></html>''')

# =========================================================
# PHONE ATTENDANCE — SAVE
# =========================================================

@app.post("/phone-attendance/save", response_class=HTMLResponse)
def save_phone_attendance(
    attended_date: str = Form(...),
    client_ids: Optional[List[str]] = Form(None)
):
    """
    Saves instructor-selected attendance using the existing
    TSHRT attendance table.

    Safe behavior:
    - Only selected students are marked present.
    - Existing attendance for the same student/date is updated.
    - No duplicate attendance record is intentionally created.
    - Existing finalized status is preserved.
    """
    # ---------------------------------------------------------
    # SERVER-SIDE CLASS-DAY SAFETY LOCK
    # ---------------------------------------------------------
    # Never trust the page alone. Before writing attendance,
    # independently verify that the submitted date is a valid
    # class day for the active challenge.

    schedule = get_active_class_schedule(attended_date)

    if not schedule.get("is_class_day", False):

        reason = schedule.get("reason", "NOT_SCHEDULED")

        messages = {
            "NO_ACTIVE_CHALLENGE":
                "There is currently no active TSHRT challenge.",

            "OUTSIDE_ACTIVE_CHALLENGE":
                "This date is outside the active challenge dates.",

            "NO_CLASS_DATE":
                "This date has been designated as a NO-CLASS day.",

            "NOT_SCHEDULED":
                "This date is not a scheduled ABC Class day.",

            "INVALID_DATE":
                "The submitted attendance date is invalid."
        }

        message = messages.get(
            reason,
            "Attendance is not allowed for this date."
        )

        return f"""
<!DOCTYPE html>
<html>

<head>
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>Attendance Blocked</title>
</head>

<body style="
    margin:0;
    background:#111;
    color:white;
    font-family:Arial, sans-serif;
    text-align:center;
">

    <div style="
        background:#000;
        border-bottom:4px solid #d4af37;
        padding:25px;
    ">

        <h1 style="
            color:#d4af37;
            margin:0;
        ">
            TSHRT
        </h1>

        <p>ABC Class Attendance</p>

    </div>

    <div style="
        max-width:600px;
        margin:auto;
        padding:50px 20px;
    ">

        <div style="
            border:2px solid #d4af37;
            border-radius:12px;
            padding:30px 20px;
            background:#1c1c1c;
        ">

            <h2 style="
                color:#d4af37;
                margin-top:0;
            ">
                ATTENDANCE BLOCKED
            </h2>

            <p style="font-size:20px;">
                {attended_date}
            </p>

            <p style="
                font-size:18px;
                line-height:1.5;
            ">
                {message}
            </p>

            <p style="
                margin-top:25px;
                color:#aaa;
                font-weight:bold;
            ">
                No attendance records were changed.
            </p>

            <a href="/phone-attendance"
               style="
                   display:inline-block;
                   margin-top:20px;
                   padding:14px 22px;
                   background:#d4af37;
                   color:#000;
                   text-decoration:none;
                   border-radius:8px;
                   font-weight:bold;
               ">
                RETURN TO ATTENDANCE
            </a>

        </div>

    </div>

</body>
</html>
"""

    selected_ids = client_ids or []

    conn = get_conn()
    cur = conn.cursor()

    saved = 0

    try:
        # Only ABC Class client IDs are valid for this instructor page.
        valid_rows = cur.execute("""
            SELECT client_id
            FROM clients
            WHERE LOWER(TRIM(COALESCE(group_name, ''))) = 'abc class'
        """).fetchall()
        valid_ids = {row["client_id"] for row in valid_rows}
        selected_ids = [cid for cid in selected_ids if cid in valid_ids]

        # A finalized date is locked everywhere, including phone attendance.
        finalized = cur.execute("""
            SELECT 1
            FROM attendance
            WHERE attended_date = ?
              AND COALESCE(finalized, 0) = 1
            LIMIT 1
        """, (attended_date,)).fetchone()

        if finalized:
            conn.close()
            return HTMLResponse(
                content=f"""
                <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
                <body style="background:#111;color:white;font-family:Arial;text-align:center;padding:40px;">
                    <h1 style="color:#d4af37;">TSHRT ATTENDANCE</h1>
                    <h2>DATE IS FINALIZED</h2>
                    <p>{attended_date} is locked. Unfinalize the date before changing attendance.</p>
                    <a href="/phone-attendance?date={attended_date}" style="color:#d4af37;font-size:20px;">Return to Attendance</a>
                </body></html>
                """,
                status_code=409
            )

        cur.execute("BEGIN")

        # Phone attendance is authoritative for this ABC Class date:
        # clear the editable ABC records for the date, then write the
        # students currently checked PRESENT. This makes the phone page
        # and Attendance Board read the exact same attendance state.
        cur.execute("""
            DELETE FROM attendance
            WHERE attended_date = ?
              AND COALESCE(finalized, 0) = 0
              AND client_id IN (
                  SELECT client_id
                  FROM clients
                  WHERE LOWER(TRIM(COALESCE(group_name, ''))) = 'abc class'
              )
        """, (attended_date,))

        for client_id in selected_ids:
            cur.execute("""
                INSERT INTO attendance
                    (client_id, attended_date, present, finalized)
                VALUES (?, ?, 1, 0)
                ON CONFLICT(client_id, attended_date) DO UPDATE SET
                    present = 1
            """, (client_id, attended_date))
            saved += 1

        conn.commit()

    except Exception as exc:
        conn.rollback()
        conn.close()

        return f"""
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width, initial-scale=1.0">
        </head>

        <body style="
            background:#111;
            color:white;
            font-family:Arial;
            text-align:center;
            padding:40px;
        ">

            <h1 style="color:#d4af37;">
                TSHRT ATTENDANCE
            </h1>

            <h2>Attendance Was NOT Saved</h2>

            <p>{str(exc)}</p>

            <a href="/phone-attendance?date={attended_date}"
               style="color:#d4af37;font-size:20px;">
                Return to Attendance
            </a>

        </body>
        </html>
        """

    conn.close()

    return f"""
<!DOCTYPE html>
<html>

<head>
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>Attendance Saved</title>
</head>

<body style="
    margin:0;
    background:#111;
    color:white;
    font-family:Arial;
    text-align:center;
">

    <div style="
        background:#000;
        border-bottom:4px solid #d4af37;
        padding:25px;
    ">

        <h1 style="
            color:#d4af37;
            margin:0;
        ">
            TSHRT
        </h1>

        <p>ABC Class Attendance</p>

    </div>

    <div style="padding:45px 20px;">

        <div style="
            font-size:70px;
            margin-bottom:15px;
        ">
            ✓
        </div>

        <h2>ATTENDANCE SAVED</h2>

        <p style="font-size:20px;">
            <strong>{saved}</strong> students marked present.
        </p>

        <p>
            Date: <strong>{attended_date}</strong>
        </p>

        <a href="/phone-attendance?date={attended_date}"
           style="
               display:inline-block;
               margin-top:25px;
               padding:16px 25px;
               background:#d4af37;
               color:#000;
               text-decoration:none;
               border-radius:8px;
               font-weight:bold;
               font-size:18px;
           ">
            RETURN TO ATTENDANCE
        </a>

    </div>

</body>
</html>
"""
