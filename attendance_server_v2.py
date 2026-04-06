from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
import sqlite3
import time
import os
from datetime import datetime, timedelta

app = FastAPI()

# Render-safe writable location
DB_PATH = os.environ.get("TSHRT_DB_PATH", "/tmp/cloud.db")

DEFAULT_CHALLENGE_START = "2026-03-09"
DEFAULT_CHALLENGE_END = "2026-04-20"
DEFAULT_GROUPS = ["ABC Class", "Gym", "Personal"]


# ----------------------
# DATABASE
# ----------------------

def get_conn():
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=10
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
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
        group_name TEXT,
        snapshot_score INTEGER DEFAULT 0,
        baseline_score INTEGER DEFAULT 0,
        in_challenge INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT NOT NULL,
        attended_date TEXT NOT NULL,
        UNIQUE(client_id, attended_date)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS challenge_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # default challenge metadata
    defaults = {
        "challenge_start": DEFAULT_CHALLENGE_START,
        "challenge_end": DEFAULT_CHALLENGE_END,
        "default_days": "0,2"  # Monday, Wednesday
    }

    for key, value in defaults.items():
        cur.execute("""
        INSERT INTO challenge_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO NOTHING
        """, (key, value))

    conn.commit()
    conn.close()


init_db()


# ----------------------
# MODELS
# ----------------------

class Client(BaseModel):
    client_id: str
    display_name: str
    first_name: str
    last_name: str
    group_name: str   # ✅ THIS IS THE FIX
    snapshot_score: int = 0
    baseline_score: int = 0
    in_challenge: int = 1


class CheckIn(BaseModel):
    client_id: str
    attended_date: str


class AttendanceSaveRequest(BaseModel):
    group: str
    dates: List[str]
    selected: Dict[str, List[str]]


# ----------------------
# HELPERS
# ----------------------

def parse_date_safe(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def daterange(start_date: str, end_date: str, allowed_days: List[int]) -> List[str]:
    start = parse_date_safe(start_date)
    end = parse_date_safe(end_date)

    dates = []
    current = start
    while current <= end:
        if current.weekday() in allowed_days:
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def get_meta_value(key: str, default: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM challenge_meta WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


# --- ONLY SHOWING FIXED PARTS YOU NEED TO REPLACE ---

def load_clients_for_group(group: Optional[str] = None, only_in_challenge: bool = True):
    conn = get_conn()
    cur = conn.cursor()

    # TEMP DEBUG: show what is actually in DB
    cur.execute("SELECT DISTINCT group_name FROM clients")
    print("GROUPS IN DB:", [r[0] for r in cur.fetchall()])

    if group and group.lower() != "all":
        if only_in_challenge:
            cur.execute("""
                SELECT client_id, display_name, first_name, last_name, group_name,
                       snapshot_score, baseline_score, in_challenge
                FROM clients
                WHERE (group_name=? OR group_name IS NULL OR group_name='')
                  AND in_challenge=1
                ORDER BY COALESCE(last_name,''), COALESCE(first_name,'')
            """, (group,))
        else:
            cur.execute("""
                SELECT client_id, display_name, first_name, last_name, group_name,
                       snapshot_score, baseline_score, in_challenge
                FROM clients
                WHERE (group_name=? OR group_name IS NULL OR group_name='')
                ORDER BY COALESCE(last_name,''), COALESCE(first_name,'')
            """, (group,))
    else:
        if only_in_challenge:
            cur.execute("""
                SELECT client_id, display_name, first_name, last_name, group_name,
                       snapshot_score, baseline_score, in_challenge
                FROM clients
                WHERE in_challenge=1
                ORDER BY COALESCE(last_name,''), COALESCE(first_name,'')
            """)
        else:
            cur.execute("""
                SELECT client_id, display_name, first_name, last_name, group_name,
                       snapshot_score, baseline_score, in_challenge
                FROM clients
                ORDER BY COALESCE(last_name,''), COALESCE(first_name,'')
            """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.get("/board")
def board(
    group: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None)
):
    conn = get_conn()
    cur = conn.cursor()

    if group and group.lower() != "all":
        cur.execute("""
            SELECT client_id, display_name, first_name, last_name,
                   snapshot_score, baseline_score, group_name
            FROM clients
            WHERE in_challenge=1 AND group_name=?
            ORDER BY COALESCE(last_name,''), COALESCE(first_name,'')
        """, (group,))
    else:
        cur.execute("""
            SELECT client_id, display_name, first_name, last_name,
                   snapshot_score, baseline_score, group_name
            FROM clients
            WHERE in_challenge=1
            ORDER BY COALESCE(last_name,''), COALESCE(first_name,'')
        """)

    clients = cur.fetchall()
    result = []

    for c in clients:
        client_id = c["client_id"]
        name = c["display_name"]
        snapshot = int(c["snapshot_score"] or 0)
        baseline = int(c["baseline_score"] or 0)

        attendance_count = attendance_count_for_client(cur, client_id, start, end)
        current_score = snapshot + attendance_count
        lifetime_score = baseline + current_score

        result.append({
            "client_id": client_id,
            "name": name,
            "group": c["group_name"],
            "attendance": attendance_count,
            "current_score": current_score,
            "lifetime_score": lifetime_score
        })

    conn.close()

    return sorted(result, key=lambda x: x["current_score"], reverse=True)


def get_attendance_map(client_ids: List[str], dates: List[str]) -> Dict[str, List[str]]:
    if not client_ids or not dates:
        return {}

    conn = get_conn()
    cur = conn.cursor()

    placeholders_clients = ",".join(["?"] * len(client_ids))
    placeholders_dates = ",".join(["?"] * len(dates))

    sql = f"""
        SELECT client_id, attended_date
        FROM attendance
        WHERE client_id IN ({placeholders_clients})
          AND attended_date IN ({placeholders_dates})
    """

    params = client_ids + dates
    cur.execute(sql, params)

    result: Dict[str, List[str]] = {}
    for row in cur.fetchall():
        result.setdefault(row["client_id"], []).append(row["attended_date"])

    conn.close()
    return result


def attendance_count_for_client(cur, client_id: str, start: Optional[str] = None, end: Optional[str] = None) -> int:
    if start and end:
        cur.execute("""
            SELECT COUNT(*) AS count_val
            FROM attendance
            WHERE client_id=? AND attended_date BETWEEN ? AND ?
        """, (client_id, start, end))
    else:
        cur.execute("""
            SELECT COUNT(*) AS count_val
            FROM attendance
            WHERE client_id=?
        """, (client_id,))
    row = cur.fetchone()
    return int(row["count_val"]) if row else 0


# ----------------------
# CORE ROUTES
# ----------------------

@app.get("/")
def root():
    return {"status": "ok", "service": "TSHRT Attendance Cloud"}


@app.get("/debug")
def debug():
    return {
        "status": "server running",
        "db_path": DB_PATH,
        "challenge_start": get_meta_value("challenge_start", DEFAULT_CHALLENGE_START),
        "challenge_end": get_meta_value("challenge_end", DEFAULT_CHALLENGE_END),
        "default_days": get_meta_value("default_days", "0,2")
    }


@app.post("/sync")
def sync_clients(clients: List[Client]):
    conn = get_conn()
    cur = conn.cursor()

    for c in clients:
        cur.execute("""
            INSERT INTO clients (
                client_id, display_name, first_name, last_name, group_name,
                snapshot_score, baseline_score, in_challenge
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                display_name=excluded.display_name,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                group_name=excluded.group_name,
                snapshot_score=excluded.snapshot_score,
                baseline_score=excluded.baseline_score,
                in_challenge=excluded.in_challenge
        """, (
            c.client_id,
            c.display_name,
            c.first_name,
            c.last_name,
            c.group_name,
            c.snapshot_score,
            c.baseline_score,
            c.in_challenge
        ))

    conn.commit()
    conn.close()

    return {"status": "clients synced", "count": len(clients)}


@app.post("/checkin")
def checkin(data: CheckIn):
    retries = 3

    for _ in range(retries):
        conn = None
        try:
            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO attendance (client_id, attended_date)
                VALUES (?, ?)
            """, (data.client_id, data.attended_date))

            conn.commit()
            conn.close()

            return {"status": "checked in"}

        except sqlite3.IntegrityError:
            if conn:
                conn.close()
            return {"status": "already checked in"}

        except sqlite3.OperationalError as e:
            if conn:
                conn.close()

            if "locked" in str(e).lower():
                time.sleep(0.5)
                continue
            raise HTTPException(status_code=500, detail=str(e))

        except Exception as e:
            if conn:
                conn.close()
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=500, detail="Database locked, retry failed")


@app.get("/board")
def board(
    group: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None)
):
    conn = get_conn()
    cur = conn.cursor()

    if group and group.lower() != "all":
        cur.execute("""
            SELECT client_id, display_name, snapshot_score, baseline_score, group_name
            FROM clients
            WHERE in_challenge=1 AND group_name=?
            ORDER BY last_name, first_name
        """, (group,))
    else:
        cur.execute("""
            SELECT client_id, display_name, snapshot_score, baseline_score, group_name
            FROM clients
            WHERE in_challenge=1
            ORDER BY last_name, first_name
        """)

    clients = cur.fetchall()
    result = []

    for c in clients:
        client_id = c["client_id"]
        name = c["display_name"]
        snapshot = int(c["snapshot_score"] or 0)
        baseline = int(c["baseline_score"] or 0)

        attendance_count = attendance_count_for_client(cur, client_id, start, end)
        current_score = snapshot + attendance_count
        lifetime_score = baseline + current_score

        result.append({
            "client_id": client_id,
            "name": name,
            "group": c["group_name"],
            "attendance": attendance_count,
            "current_score": current_score,
            "lifetime_score": lifetime_score
        })

    conn.close()

    return sorted(result, key=lambda x: x["current_score"], reverse=True)


@app.get("/display")
def display(
    group: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None)
):
    data = board(group=group, start=start, end=end)
    return [
        {
            "name": x["name"],
            "score": x["current_score"]
        }
        for x in data
    ]


# ----------------------
# ATTENDANCE BOARD API
# ----------------------

@app.get("/attendance/data")
def attendance_data(
    group: str = Query(default="Gym"),
    start: str = Query(default=DEFAULT_CHALLENGE_START),
    end: str = Query(default=DEFAULT_CHALLENGE_END),
    days: str = Query(default="0,2")
):
    try:
        allowed_days = [int(x.strip()) for x in days.split(",") if x.strip() != ""]
        dates = daterange(start, end, allowed_days)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date/day setup")

    clients = load_clients_for_group(group=group, only_in_challenge=True)
    client_ids = [c["client_id"] for c in clients]
    existing = get_attendance_map(client_ids, dates)

    return {
        "group": group,
        "start": start,
        "end": end,
        "days": allowed_days,
        "dates": dates,
        "clients": clients,
        "attendance": existing
    }


@app.post("/attendance/save")
def attendance_save(payload: AttendanceSaveRequest):
    group = payload.group
    dates = sorted(set(payload.dates))
    selected = payload.selected

    clients = load_clients_for_group(group=group, only_in_challenge=True)
    client_ids = [c["client_id"] for c in clients]

    if not client_ids or not dates:
        return {"status": "nothing to save", "saved": 0}

    conn = get_conn()
    cur = conn.cursor()

    try:
        # Remove existing attendance only for this group/date universe
        client_placeholders = ",".join(["?"] * len(client_ids))
        date_placeholders = ",".join(["?"] * len(dates))

        cur.execute(f"""
            DELETE FROM attendance
            WHERE client_id IN ({client_placeholders})
              AND attended_date IN ({date_placeholders})
        """, client_ids + dates)

        saved = 0

        for client_id, client_dates in selected.items():
            if client_id not in client_ids:
                continue

            for attended_date in client_dates:
                if attended_date not in dates:
                    continue

                cur.execute("""
                    INSERT OR IGNORE INTO attendance (client_id, attended_date)
                    VALUES (?, ?)
                """, (client_id, attended_date))
                saved += 1

        conn.commit()
        conn.close()

        return {"status": "saved", "saved": saved}

    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------
# ATTENDANCE BOARD UI
# ----------------------

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>TSHRT Attendance Board</title>
<style>
    :root {{
        --bg: #0f172a;
        --panel: #111827;
        --panel-2: #1f2937;
        --line: #334155;
        --text: #e5e7eb;
        --muted: #94a3b8;
        --accent: #22c55e;
        --accent-2: #16a34a;
        --warning: #f59e0b;
        --danger: #ef4444;
        --button: #2563eb;
        --button-hover: #1d4ed8;
        --chip: #0b1220;
        --shadow: 0 8px 24px rgba(0,0,0,.28);
    }}

    * {{ box-sizing: border-box; }}

    body {{
        margin: 0;
        font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        background: linear-gradient(180deg, #0b1220 0%, #0f172a 100%);
        color: var(--text);
    }}

    .wrap {{
        max-width: 1600px;
        margin: 0 auto;
        padding: 20px;
    }}

    .topbar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        margin-bottom: 18px;
        flex-wrap: wrap;
    }}

    .title-wrap h1 {{
        margin: 0;
        font-size: 28px;
        font-weight: 800;
        letter-spacing: .2px;
    }}

    .title-wrap p {{
        margin: 6px 0 0 0;
        color: var(--muted);
        font-size: 14px;
    }}

    .status-row {{
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
    }}

    .pill {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: rgba(255,255,255,.04);
        border: 1px solid var(--line);
        padding: 10px 14px;
        border-radius: 999px;
        font-size: 13px;
        color: var(--text);
    }}

    .dot {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: var(--warning);
        box-shadow: 0 0 0 3px rgba(245,158,11,.15);
    }}

    .dot.ready {{
        background: var(--accent);
        box-shadow: 0 0 0 3px rgba(34,197,94,.15);
    }}

    .controls {{
        display: grid;
        grid-template-columns: repeat(6, minmax(140px, 1fr));
        gap: 12px;
        background: rgba(17,24,39,.95);
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 16px;
        box-shadow: var(--shadow);
        margin-bottom: 18px;
    }}

    .field {{
        display: flex;
        flex-direction: column;
        gap: 8px;
    }}

    .field label {{
        font-size: 12px;
        color: var(--muted);
        font-weight: 700;
        letter-spacing: .4px;
        text-transform: uppercase;
    }}

    select, input[type="date"] {{
        width: 100%;
        border: 1px solid var(--line);
        background: var(--chip);
        color: var(--text);
        border-radius: 12px;
        padding: 12px;
        font-size: 14px;
        outline: none;
    }}

    .days {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
    }}

    .day-btn {{
        border: 1px solid var(--line);
        background: var(--chip);
        color: var(--text);
        border-radius: 999px;
        padding: 10px 14px;
        cursor: pointer;
        font-weight: 600;
    }}

    .day-btn.active {{
        background: rgba(37,99,235,.16);
        border-color: #3b82f6;
    }}

    .actions {{
        display: flex;
        gap: 10px;
        align-items: end;
        flex-wrap: wrap;
    }}

    button {{
        border: 0;
        border-radius: 14px;
        padding: 12px 16px;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
        transition: transform .05s ease, opacity .2s ease, background .2s ease;
    }}

    button:hover {{ opacity: .96; }}
    button:active {{ transform: translateY(1px); }}

    .btn-primary {{
        background: var(--button);
        color: white;
    }}

    .btn-primary:hover {{
        background: var(--button-hover);
    }}

    .btn-green {{
        background: var(--accent-2);
        color: white;
    }}

    .btn-dark {{
        background: #374151;
        color: white;
    }}

    .btn-outline {{
        background: transparent;
        color: var(--text);
        border: 1px solid var(--line);
    }}

    .summary {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        margin-bottom: 14px;
    }}

    .card {{
        background: rgba(17,24,39,.95);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 14px 16px;
        min-width: 180px;
        box-shadow: var(--shadow);
    }}

    .card .label {{
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .4px;
        margin-bottom: 6px;
        font-weight: 700;
    }}

    .card .value {{
        font-size: 26px;
        font-weight: 800;
    }}

    .table-shell {{
        background: rgba(17,24,39,.95);
        border: 1px solid var(--line);
        border-radius: 20px;
        overflow: hidden;
        box-shadow: var(--shadow);
    }}

    .table-wrap {{
        overflow: auto;
        max-height: 72vh;
    }}

    table {{
        width: max-content;
        min-width: 100%;
        border-collapse: separate;
        border-spacing: 0;
    }}

    thead th {{
        position: sticky;
        top: 0;
        z-index: 3;
        background: #0f172a;
        color: var(--text);
        border-bottom: 1px solid var(--line);
        padding: 12px 10px;
        text-align: center;
        font-size: 12px;
        white-space: nowrap;
    }}

    thead th.sticky-left {{
        left: 0;
        z-index: 4;
        text-align: left;
        min-width: 220px;
    }}

    tbody td, tbody th {{
        border-bottom: 1px solid rgba(148,163,184,.12);
        padding: 10px;
    }}

    tbody th {{
        position: sticky;
        left: 0;
        z-index: 2;
        background: #111827;
        min-width: 220px;
        text-align: left;
        font-size: 14px;
        font-weight: 700;
    }}

    .sub {{
        display: block;
        color: var(--muted);
        font-weight: 500;
        font-size: 12px;
        margin-top: 3px;
    }}

    .cell {{
        width: 42px;
        min-width: 42px;
        height: 42px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: #0b1220;
        cursor: pointer;
        transition: background .15s ease, border-color .15s ease, transform .04s ease;
    }}

    .cell:hover {{
        border-color: #64748b;
    }}

    .cell:active {{
        transform: translateY(1px);
    }}

    .cell.on {{
        background: rgba(34,197,94,.25);
        border-color: var(--accent);
        box-shadow: inset 0 0 0 1px rgba(34,197,94,.3);
    }}

    .legend {{
        display: flex;
        gap: 16px;
        align-items: center;
        color: var(--muted);
        font-size: 13px;
        margin-top: 12px;
        padding: 0 4px 6px;
    }}

    .legend-box {{
        width: 18px;
        height: 18px;
        border-radius: 6px;
        border: 1px solid var(--line);
        background: #0b1220;
        display: inline-block;
        vertical-align: middle;
        margin-right: 6px;
    }}

    .legend-box.on {{
        background: rgba(34,197,94,.25);
        border-color: var(--accent);
    }}

    .toast {{
        position: fixed;
        right: 20px;
        bottom: 20px;
        background: rgba(17,24,39,.98);
        border: 1px solid var(--line);
        color: var(--text);
        border-radius: 14px;
        padding: 14px 16px;
        min-width: 260px;
        box-shadow: var(--shadow);
        display: none;
        z-index: 999;
    }}

    .toast.show {{
        display: block;
    }}

    @media (max-width: 1100px) {{
        .controls {{
            grid-template-columns: repeat(2, minmax(140px, 1fr));
        }}
    }}

    @media (max-width: 680px) {{
        .controls {{
            grid-template-columns: 1fr;
        }}
        .topbar {{
            align-items: flex-start;
        }}
        tbody th, thead th.sticky-left {{
            min-width: 180px;
        }}
    }}
</style>
</head>
<body>
<div class="wrap">
    <div class="topbar">
        <div class="title-wrap">
            <h1>TSHRT Attendance Board</h1>
            <p>Cloud-based challenge attendance, scoring foundation, and group control.</p>
        </div>

        <div class="status-row">
            <div class="pill">
                <span id="serverDot" class="dot"></span>
                <span id="serverStatus">Checking server...</span>
            </div>
            <button class="btn-outline" id="wakeBtn">Wake Server</button>
        </div>
    </div>

    <div class="controls">
        <div class="field">
            <label for="groupSelect">Group</label>
            <select id="groupSelect">
                <option>ABC Class</option>
                <option selected>Gym</option>
                <option>Personal</option>
            </select>
        </div>

        <div class="field">
            <label for="startDate">Challenge Start</label>
            <input id="startDate" type="date" value="{DEFAULT_CHALLENGE_START}" />
        </div>

        <div class="field">
            <label for="endDate">Challenge End</label>
            <input id="endDate" type="date" value="{DEFAULT_CHALLENGE_END}" />
        </div>

        <div class="field">
            <label>Class Days</label>
            <div class="days" id="daysWrap">
                <button class="day-btn active" data-day="0" type="button">Mon</button>
                <button class="day-btn" data-day="1" type="button">Tue</button>
                <button class="day-btn active" data-day="2" type="button">Wed</button>
                <button class="day-btn" data-day="3" type="button">Thu</button>
                <button class="day-btn" data-day="4" type="button">Fri</button>
                <button class="day-btn" data-day="5" type="button">Sat</button>
                <button class="day-btn" data-day="6" type="button">Sun</button>
            </div>
        </div>

        <div class="field actions">
            <button class="btn-primary" id="loadBtn" type="button">Load Board</button>
            <button class="btn-green" id="saveBtn" type="button">Save Attendance</button>
            <button class="btn-dark" id="finalizeBtn" type="button">Finalize Scores</button>
            <button class="btn-outline" onclick="window.print()">Print</button>
        </div>
    </div>

    <div class="summary">
        <div class="card">
            <div class="label">Group</div>
            <div class="value" id="summaryGroup">Gym</div>
        </div>
        <div class="card">
            <div class="label">Clients</div>
            <div class="value" id="summaryClients">0</div>
        </div>
        <div class="card">
            <div class="label">Dates</div>
            <div class="value" id="summaryDates">0</div>
        </div>
        <div class="card">
            <div class="label">Selected Check-ins</div>
            <div class="value" id="summarySelected">0</div>
        </div>
    </div>

    <div class="table-shell">
        <div class="table-wrap" id="boardWrap">
            <table id="boardTable">
                <thead></thead>
                <tbody></tbody>
            </table>
        </div>
    </div>

    <div class="legend">
        <span><span class="legend-box"></span> Not checked in</span>
        <span><span class="legend-box on"></span> Checked in</span>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
    const state = {{
        group: "Gym",
        start: "{DEFAULT_CHALLENGE_START}",
        end: "{DEFAULT_CHALLENGE_END}",
        days: [0, 2],
        dates: [],
        clients: [],
        attendance: {{}}
    }};

    function showToast(message) {{
        const toast = document.getElementById("toast");
        toast.textContent = message;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 2600);
    }}

    async function wakeServer() {{
        const dot = document.getElementById("serverDot");
        const status = document.getElementById("serverStatus");
        status.textContent = "Waking server...";
        dot.classList.remove("ready");

        try {{
            const res = await fetch("/debug", {{ cache: "no-store" }});
            if (!res.ok) throw new Error("wake failed");
            status.textContent = "Server ready";
            dot.classList.add("ready");
            return true;
        }} catch (e) {{
            status.textContent = "Server unavailable";
            dot.classList.remove("ready");
            return false;
        }}
    }}

    function getSelectedDays() {{
        return [...document.querySelectorAll(".day-btn.active")].map(btn => Number(btn.dataset.day));
    }}

    function updateSummary() {{
        document.getElementById("summaryGroup").textContent = state.group;
        document.getElementById("summaryClients").textContent = String(state.clients.length);
        document.getElementById("summaryDates").textContent = String(state.dates.length);

        let total = 0;
        for (const clientId of Object.keys(state.attendance)) {{
            total += state.attendance[clientId].length;
        }}
        document.getElementById("summarySelected").textContent = String(total);
    }}

    function shortDate(isoDate) {{
        const d = new Date(isoDate + "T00:00:00");
        return d.toLocaleDateString(undefined, {{ month: "short", day: "numeric" }});
    }}

    function weekdayShort(isoDate) {{
        const d = new Date(isoDate + "T00:00:00");
        return d.toLocaleDateString(undefined, {{ weekday: "short" }});
    }}

    function renderBoard() {{
        const thead = document.querySelector("#boardTable thead");
        const tbody = document.querySelector("#boardTable tbody");

        thead.innerHTML = "";
        tbody.innerHTML = "";

        const trHead = document.createElement("tr");

        const leftHead = document.createElement("th");
        leftHead.className = "sticky-left";
        leftHead.textContent = "Client";
        trHead.appendChild(leftHead);

        for (const date of state.dates) {{
            const th = document.createElement("th");
            th.innerHTML = `<div>${{weekdayShort(date)}}</div><div style="color:var(--muted);margin-top:4px;">${{shortDate(date)}}</div>`;
            trHead.appendChild(th);
        }}

        thead.appendChild(trHead);

        for (const client of state.clients) {{
            const tr = document.createElement("tr");

            const th = document.createElement("th");
            th.innerHTML = `${{client.display_name || client.name || client.client_id}}<span class="sub">${{client.group_name || state.group}}</span>`;
            tr.appendChild(th);

            for (const date of state.dates) {{
                const td = document.createElement("td");
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "cell";

                const selectedDates = state.attendance[client.client_id] || [];
                if (selectedDates.includes(date)) {{
                    btn.classList.add("on");
                }}

                btn.addEventListener("click", () => {{
                    toggleCell(client.client_id, date, btn);
                }});

                td.appendChild(btn);
                tr.appendChild(td);
            }}

            tbody.appendChild(tr);
        }}

        updateSummary();
    }}

    function toggleCell(clientId, date, button) {{
        if (!state.attendance[clientId]) {{
            state.attendance[clientId] = [];
        }}

        const idx = state.attendance[clientId].indexOf(date);

        if (idx >= 0) {{
            state.attendance[clientId].splice(idx, 1);
            button.classList.remove("on");
        }} else {{
            state.attendance[clientId].push(date);
            button.classList.add("on");
        }}

        updateSummary();
    }}

    async function loadBoard() {{
        state.group = document.getElementById("groupSelect").value;
        state.start = document.getElementById("startDate").value;
        state.end = document.getElementById("endDate").value;
        state.days = getSelectedDays();

        if (!state.start || !state.end) {{
            showToast("Please set challenge start and end dates.");
            return;
        }}

        if (state.days.length === 0) {{
            showToast("Select at least one class day.");
            return;
        }}

        const ready = await wakeServer();
        if (!ready) {{
            showToast("Server is not ready yet.");
            return;
        }}

        const params = new URLSearchParams();
        params.set("group", state.group);
        params.set("start", state.start);
        params.set("end", state.end);
        params.set("days", state.days.join(","));

        try {{
            const res = await fetch("/attendance/data?" + params.toString(), {{ cache: "no-store" }});
            if (!res.ok) throw new Error("load failed");

            const data = await res.json();
            state.dates = data.dates || [];
            state.clients = data.clients || [];
            state.attendance = data.attendance || {{}};

            renderBoard();
            showToast("Board loaded.");
        }} catch (e) {{
            showToast("Failed to load attendance board.");
        }}
    }}

    async function saveBoard() {{
        const ready = await wakeServer();
        if (!ready) {{
            showToast("Server is not ready yet.");
            return;
        }}

        try {{
            const res = await fetch("/attendance/save", {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{
                    group: state.group,
                    dates: state.dates,
                    selected: state.attendance
                }})
            }});

            if (!res.ok) throw new Error("save failed");

            const data = await res.json();
            showToast(`Saved. ${{data.saved || 0}} check-ins updated.`);
        }} catch (e) {{
            showToast("Failed to save attendance.");
        }}
    }}

    document.getElementById("wakeBtn").addEventListener("click", wakeServer);
    document.getElementById("loadBtn").addEventListener("click", loadBoard);
    document.getElementById("saveBtn").addEventListener("click", saveBoard);

    document.getElementById("finalizeBtn").addEventListener("click", () => {{
        showToast("Finalize is reserved for score locking in the next phase.");
    }});

    document.querySelectorAll(".day-btn").forEach(btn => {{
        btn.addEventListener("click", () => {{
            btn.classList.toggle("active");
        }});
    }});

    window.addEventListener("load", async () => {{
        await wakeServer();
        await loadBoard();
    }});
</script>
</body>
</html>
    """
    return HTMLResponse(content=html)
