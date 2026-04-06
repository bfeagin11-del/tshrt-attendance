# --- SAME IMPORTS ---
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
import sqlite3
import time
import os
from datetime import datetime, timedelta

app = FastAPI()

DB_PATH = os.environ.get("TSHRT_DB_PATH", "/tmp/cloud.db")

DEFAULT_CHALLENGE_START = "2026-03-09"
DEFAULT_CHALLENGE_END = "2026-04-20"

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
    <html>
    <head>
        <title>TSHRT Attendance</title>
    </head>
    <body style="background:#0f172a;color:white;font-family:sans-serif;">
        <h1 style="text-align:center;">TSHRT Attendance Board</h1>
        <p style="text-align:center;">If you see this, your route is working.</p>

        <div style="text-align:center;margin-top:30px;">
            <a href="/attendance/data" style="color:#22c55e;">Test Data Endpoint</a>
        </div>
    </body>
    </html>
    """

# ----------------------
# DATABASE
# ----------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
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
        client_id TEXT,
        attended_date TEXT,
        UNIQUE(client_id, attended_date)
    )
    """)

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
    group_name: str
    snapshot_score: int = 0
    baseline_score: int = 0
    in_challenge: int = 1


class AttendanceSaveRequest(BaseModel):
    group: str
    dates: List[str]
    selected: Dict[str, List[str]]


# ----------------------
# HELPERS
# ----------------------

def daterange(start, end, allowed_days):
    start = datetime.strptime(start, "%Y-%m-%d")
    end = datetime.strptime(end, "%Y-%m-%d")

    dates = []
    while start <= end:
        if start.weekday() in allowed_days:
            dates.append(start.strftime("%Y-%m-%d"))
        start += timedelta(days=1)
    return dates

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
def load_clients_for_group(group=None):
    conn = get_conn()
    cur = conn.cursor()

    if group:
        cur.execute("""
            SELECT * FROM clients
            WHERE in_challenge=1 AND group_name=?
            ORDER BY last_name, first_name
        """, (group,))
    else:
        cur.execute("""
            SELECT * FROM clients
            WHERE in_challenge=1
            ORDER BY last_name, first_name
        """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_attendance_map(client_ids, dates):
    if not client_ids or not dates:
        return {}

    conn = get_conn()
    cur = conn.cursor()

    placeholders_clients = ",".join(["?"] * len(client_ids))
    placeholders_dates = ",".join(["?"] * len(dates))

    cur.execute(f"""
        SELECT client_id, attended_date
        FROM attendance
        WHERE client_id IN ({placeholders_clients})
        AND attended_date IN ({placeholders_dates})
    """, client_ids + dates)

    result = {}
    for row in cur.fetchall():
        result.setdefault(row["client_id"], []).append(row["attended_date"])

    conn.close()
    return result


# ----------------------
# ROUTES
# ----------------------

@app.get("/attendance/data")
def attendance_data(
    group: str = Query(default="Gym"),
    start: str = Query(default=DEFAULT_CHALLENGE_START),
    end: str = Query(default=DEFAULT_CHALLENGE_END),
    days: str = Query(default="0,2")
):
    allowed_days = [int(x) for x in days.split(",") if x]

    dates = daterange(start, end, allowed_days)
    clients = load_clients_for_group(group)
    client_ids = [c["client_id"] for c in clients]

    attendance = get_attendance_map(client_ids, dates)

    # 🔥 CRITICAL FIX
    for cid in client_ids:
        if cid not in attendance:
            attendance[cid] = []

    return {
        "clients": clients,
        "dates": dates,
        "attendance": attendance
    }


@app.post("/attendance/save")
def attendance_save(payload: AttendanceSaveRequest):
    conn = get_conn()
    cur = conn.cursor()

    saved = 0

    for client_id, dates in payload.selected.items():
        for d in dates:
            cur.execute("""
                INSERT OR IGNORE INTO attendance (client_id, attended_date)
                VALUES (?, ?)
            """, (client_id, d))
            saved += 1

    conn.commit()
    conn.close()

    return {"saved": saved}
