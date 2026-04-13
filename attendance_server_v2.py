from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
import os
from typing import List, Optional

app = FastAPI()

DB_PATH = "/data/cloud.db"

# =========================================================
# DB
# =========================================================

def get_conn():
    os.makedirs("/data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()


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

    conn.commit()
    conn.close()


def upgrade_db():
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("ALTER TABLE attendance ADD COLUMN present INTEGER DEFAULT 1")
    except:
        pass

    try:
        cur.execute("ALTER TABLE attendance ADD COLUMN finalized INTEGER DEFAULT 0")
    except:
        pass

    try:
        cur.execute("ALTER TABLE clients ADD COLUMN baseline_score REAL DEFAULT 0")
    except:
        pass

    try:
        cur.execute("ALTER TABLE clients ADD COLUMN snapshot_score REAL DEFAULT 0")
    except:
        pass

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

def parse_name(display_name: str):
    display_name = (display_name or "").strip()
    if "," in display_name:
        last, first = display_name.split(",", 1)
        return first.strip(), last.strip()
    parts = display_name.split()
    return (parts[0], " ".join(parts[1:])) if len(parts) >= 2 else (display_name, "")


def group_match_sql():
    return "LOWER(TRIM(COALESCE(group_name, ''))) = LOWER(TRIM(?))"


# =========================================================
# SCORE ENGINE
# =========================================================

def build_leaderboard_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT 
            c.client_id,
            c.first_name,
            c.last_name,
            c.display_name,
            COALESCE(c.baseline_score, 0) as baseline_score,
            COALESCE(c.snapshot_score, 0) as snapshot_score,
            COUNT(a.attended_date) as attendance_count
        FROM clients c
        LEFT JOIN attendance a 
            ON c.client_id = a.client_id
            AND COALESCE(a.present, 1) = 1
        WHERE {group_match_sql()}
        GROUP BY c.client_id
    """, (group,)).fetchall()

    conn.close()

    results = []

    for r in rows:
        name = f"{r['last_name']}, {r['first_name']}".strip(", ") or r["display_name"]
        attendance = r["attendance_count"] or 0
        baseline = r["baseline_score"]
        snapshot = r["snapshot_score"]

        current = snapshot + attendance
        lifetime = baseline + snapshot + attendance

        results.append({
            "name": name,
            "attendance": attendance,
            "snapshot": snapshot,
            "current_score": round(current, 2),
            "lifetime_score": round(lifetime, 2)
        })

    results.sort(key=lambda x: x["current_score"], reverse=True)
    return results


# =========================================================
# ROUTES
# =========================================================

@app.get("/")
def home():
    return {"ok": True}


@app.get("/wake")
def wake():
    return {"ok": True}


@app.post("/sync")
def sync_clients(payload: SyncPayload):
    conn = get_conn()
    cur = conn.cursor()

    for c in payload.clients:
        cur.execute("""
        INSERT INTO clients (client_id, display_name, first_name, last_name, group_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            display_name=excluded.display_name,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            group_name=excluded.group_name
        """, (
            c.get("client_id"),
            c.get("display_name"),
            c.get("first_name"),
            c.get("last_name"),
            c.get("group_name")
        ))

    conn.commit()
    conn.close()

    return {"ok": True}


@app.get("/attendance/data")
def attendance_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT * FROM clients
        WHERE {group_match_sql()}
        ORDER BY last_name, first_name
    """, (group,)).fetchall()

    conn.close()

    return {"ok": True, "clients": [dict(r) for r in rows]}


@app.get("/attendance/load")
def load_attendance(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT a.client_id, a.attended_date
        FROM attendance a
        JOIN clients c ON a.client_id = c.client_id
        WHERE LOWER(TRIM(c.group_name)) = LOWER(TRIM(?))
    """, (group,)).fetchall()

    finalized = cur.execute("""
        SELECT attended_date FROM attendance WHERE finalized = 1
    """).fetchall()

    conn.close()

    selected = {f"{r['client_id']}|{r['attended_date']}": True for r in rows}

    return {
        "ok": True,
        "selected": selected,
        "finalized_dates": [r["attended_date"] for r in finalized]
    }


@app.post("/attendance/save")
def save_attendance(payload: dict):
    group = payload.get("group")
    records = payload.get("selected_records", [])

    sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()

    # BUILD NAME → ID MAP
    cur.execute("""
        SELECT client_id, display_name
        FROM clients
        WHERE LOWER(TRIM(group_name)) = LOWER(TRIM(?))
    """, (group,))

    name_to_id = {}
    for cid, name in cur.fetchall():
        name_to_id[name.strip().lower()] = cid

    saved = 0

    for rec in records:
        raw_name = rec.get("client_id", "").strip().lower()
        attended_date = rec.get("attended_date")

        # HANDLE BOTH FORMATS:
        # "Carrasco, Eduardo" → "Eduardo Carrasco"
        if "," in raw_name:
            last, first = [x.strip() for x in raw_name.split(",")]
            formatted = f"{first} {last}".lower()
        else:
            formatted = raw_name

        cid = name_to_id.get(formatted)

        if not cid:
            continue

        cur.execute("""
            INSERT OR REPLACE INTO attendance (client_id, attended_date, present, finalized)
            VALUES (?, ?, 1, 0)
        """, (cid, attended_date))

        saved += 1

    conn.commit()
    conn.close()

    return {"ok": True, "saved_count": saved}


@app.post("/attendance/finalize")
def finalize_date(payload: DatePayload):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE attendance SET finalized=1 WHERE attended_date=?", (payload.date,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/attendance/unfinalize")
def unfinalize_date(payload: DatePayload):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE attendance SET finalized=0 WHERE attended_date=?", (payload.date,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/leaderboard")
def leaderboard(group: str):
    return {"ok": True, "leaderboard": build_leaderboard_data(group)}


@app.get("/board", response_class=HTMLResponse)
def leaderboard_page():
    return """
<html>
<body style="background:#0f172a;color:white;font-family:Arial;padding:20px;">
<h2>Leaderboard</h2>
<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>
<button onclick="load()">Load</button>
<table id="t"></table>

<script>
async function load(){
let g=document.getElementById("group").value;
let r=await fetch("/leaderboard?group="+g);
let d=await r.json();

let html="<tr><th>#</th><th>Name</th><th>Att</th><th>Δ</th><th>C</th><th>L</th></tr>";
let i=1;

for(let x of d.leaderboard){
html+=`<tr>
<td>${i++}</td>
<td>${x.name}</td>
<td>${x.attendance}</td>
<td>${x.snapshot}</td>
<td>${x.current_score}</td>
<td>${x.lifetime_score}</td>
</tr>`;
}

document.getElementById("t").innerHTML=html;
}
</script>
</body>
</html>
"""


# =========================================================
# STARTUP
# =========================================================

init_db()
upgrade_db()
