from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
import os
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

    conn.commit()
    conn.close()


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

    results.sort(key=lambda x: (-x["lifetime_score"], -x["current_score"], x["name"].lower()))
    return results


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
    button { display:none; }
    select { display:none; }

    body {
        background:white !important;
        color:black !important;
    }

    table {
        width:100%;
        border-collapse:collapse;
        font-size:14px;
    }

    th, td {
        border:1px solid black;
        padding:6px;
        text-align:center;
    }
}

body { background:#0f172a; color:white; font-family:Arial; padding:20px; }
h2 { margin-bottom:20px; }
table { border-collapse:collapse; width:100%; }
th, td { border:1px solid #334155; padding:10px; text-align:center; }
th { background:#1e293b; }
.rank { font-weight:bold; }
.gold { color:#fbbf24; font-weight:bold; }
</style>
</head>
<body>

<h2>🔥 TSHRT Challenge Leaderboard</h2>

Group:
<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>

<button onclick="loadBoard()">Load</button>
<button onclick="printBoard()">🖨️ Print Leaderboard</button>

<table id="table"></table>
<div style="
    margin-top:25px;
    padding:15px;
    border:1px solid #334155;
    background:#111827;
    border-radius:10px;
    font-size:14px;
    line-height:1.8;
">

<h3 style="margin-top:0;">📘 Leaderboard Legend</h3>

<div>🔥 <b>Elite</b> = Outstanding consistency and performance</div>

<div>👍 <b>Consistent</b> = Solid steady progress</div>

<div>➖ <b>Stable</b> = Maintaining current condition</div>

<div>⚠️ <b>Needs Attention</b> = Metrics or attendance slipping</div>

<div>🚨 <b>Risk</b> = Immediate coaching intervention recommended</div>

</div>
<script>
function printBoard(){
    window.print();
}
function formatDelta(v) {

    v = Number(v);

    if (v >= 5) {
        return "🔥 Excellent (+" + v + ")";
    }

    if (v >= 1) {
        return "👍 Improving (+" + v + ")";
    }

    if (v <= -5) {
        return "⚠️ Needs Attention (" + v + ")";
    }

    if (v < 0) {
        return "➖ Stable (" + v + ")";
    }

    return "➖ Stable (0)";
}


function formatAttendance(v) {

    v = Number(v);

    if (v >= 8) {
        return v + " 🔥 Elite";
    }

    if (v >= 6) {
        return v + " 👍 Consistent";
    }

    if (v >= 4) {
        return v + " ➖ Stable";
    }

    if (v >= 2) {
        return v + " ⚠️ Slipping";
    }

    return v + " 🚨 Risk";
}
async function loadBoard(){
    let g = document.getElementById("group").value;
    let res = await fetch("/leaderboard?group=" + encodeURIComponent(g));
    let data = await res.json();

    let html = "<tr><th>#</th><th>Name</th><th>Att</th><th>Base</th><th>Δ</th><th>Current</th><th>Lifetime</th></tr>";

    let i = 1;
    for (let r of data.leaderboard){
        let cls = (i === 1) ? "gold" : "";
        html += "<tr>";
        html += "<td class='rank " + cls + "'>" + i + "</td>";
        html += "<td>" + r.name + "</td>";
        html += "<td>" + formatAttendance(r.attendance) + "</td>";
        html += "<td>" + r.baseline + "</td>";
        html += "<td>" + formatDelta(r.snapshot) + "</td>";
        html += "<td>" + r.current_score + "</td>";
        html += "<td>" + r.lifetime_score + "</td>";
        html += "</tr>";
        i++;
    }

    window.onload = async function() {

    console.log("TSHRT Attendance Script Started");

    try {

        await loadBoard();

        console.log("Board Loaded Successfully");

    } catch(err) {

        console.error("WINDOW LOAD ERROR:", err);

        setStatus("Window load failed: " + err.message);

    }
};
}
</script>

</body>
</html>
"""


# =========================================================
# SYNC
# =========================================================

@app.post("/sync")
def sync_clients(payload: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    clients = payload.get("clients", [])
    inserted = 0

    for c in clients:
        tests = c.get("tests", [])

        baseline = 0
        latest = 0

        valid_scores = []
        for t in tests:
            if isinstance(t, dict) and t.get("score") is not None:
                valid_scores.append(t.get("score"))

        if valid_scores:
            baseline = valid_scores[0]
            latest = valid_scores[-1]

        snapshot = latest - baseline

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
            c.get("client_id"),
            c.get("display_name"),
            c.get("first_name"),
            c.get("last_name"),
            c.get("group_name"),
            float(baseline),
            float(snapshot),
            float(c.get("previous_total", 0))
        ))

        inserted += 1

    conn.commit()
    conn.close()

    return {"ok": True, "received": inserted}


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
    finalizedDates: new Set()
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
        if (selectedDays.indexOf(cursor.getDay()) !== -1) {
            const y = cursor.getFullYear();
            const m = String(cursor.getMonth() + 1).padStart(2, "0");
            const d = String(cursor.getDate()).padStart(2, "0");
            dates.push(y + "-" + m + "-" + d);
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

window.onload = async function() {

    console.log("TSHRT Attendance Script Started");

    try {

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
                snapshot_score = 0
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
def start_challenge(start_date: str, weeks: int = 6):
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
# STARTUP
# =========================================================

init_db()
upgrade_db()
