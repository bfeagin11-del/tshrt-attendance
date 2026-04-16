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


def build_leaderboard_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.display_name,
            COALESCE(c.baseline_score, 0) AS baseline_score,
            COALESCE(c.snapshot_score, 0) AS snapshot_score,
            COUNT(a.attended_date) AS attendance_count
        FROM clients c
        LEFT JOIN attendance a
            ON c.client_id = a.client_id
            AND COALESCE(a.present, 1) = 1
        WHERE {group_match_sql()}
        GROUP BY c.client_id, c.first_name, c.last_name, c.display_name, c.baseline_score, c.snapshot_score
    """, (group,)).fetchall()

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

        attendance = r["attendance_count"] or 0
        baseline = r["baseline_score"] or 0
        snapshot = r["snapshot_score"] or 0

        current = snapshot + attendance
        lifetime = baseline + snapshot + attendance

        results.append({
            "client_id": r["client_id"],
            "name": name,
            "attendance": attendance,
            "baseline": round(baseline, 2),
            "snapshot": round(snapshot, 2),
            "current_score": round(current, 2),
            "lifetime_score": round(lifetime, 2),
        })

    results.sort(key=lambda x: (-x["current_score"], -x["lifetime_score"], x["name"].lower()))
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
        SELECT client_id, display_name, first_name, last_name, group_name,
               COALESCE(baseline_score, 0) AS baseline_score,
               COALESCE(snapshot_score, 0) AS snapshot_score
        FROM clients
        ORDER BY group_name, last_name, first_name
    """).fetchall()

    conn.close()

    return {"ok": True, "count": len(rows), "clients": [dict(r) for r in rows]}


# =========================================================
# SYNC
# =========================================================

@app.post("/sync")
def sync_clients(payload: SyncPayload):
    conn = get_conn()
    cur = conn.cursor()

    count = 0

    for c in payload.clients:
        client_id = str(c.get("client_id", "")).strip()
        display_name = str(c.get("display_name", "") or "").strip()
        first_name = str(c.get("first_name", "") or "").strip()
        last_name = str(c.get("last_name", "") or "").strip()
        group_name = str(c.get("group_name", "") or "").strip()

        if not client_id:
            continue

        if (not first_name or not last_name) and display_name:
            p_first, p_last = parse_name(display_name)
            first_name = first_name or p_first
            last_name = last_name or p_last

        cur.execute("""
        INSERT INTO clients (client_id, display_name, first_name, last_name, group_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            display_name = excluded.display_name,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            group_name = excluded.group_name
        """, (client_id, display_name, first_name, last_name, group_name))

        count += 1

    conn.commit()
    conn.close()

    return {"ok": True, "count": count}


# =========================================================
# ATTENDANCE DATA
# =========================================================

@app.get("/attendance/data")
def attendance_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT
            client_id, first_name, last_name, display_name, group_name
        FROM clients
        WHERE {group_match_sql()}
        ORDER BY last_name, first_name, display_name
    """, (group,)).fetchall()

    conn.close()

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

    return {"ok": True, "clients": clients}


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

    # Build lookup maps for this group
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

    # Finalized dates must never be overwritten
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

        # Accept either real ID or name
        if raw_client in valid_ids:
            cid = raw_client
        else:
            cid = name_to_id.get(raw_client.lower())

        if not cid:
            continue

        if attended_date in finalized_dates:
            continue

        selected_set.add((cid, attended_date))

    # Delete only NON-finalized attendance for THIS GROUP
    cur.execute(f"""
        DELETE FROM attendance
        WHERE client_id IN (
            SELECT client_id
            FROM clients
            WHERE {group_match_sql()}
        )
        AND COALESCE(finalized, 0) = 0
    """, (group,))

    # Insert current selection
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

<table id="table"></table>

<script>
async function loadBoard(){
    let g = document.getElementById("group").value;
    let res = await fetch("/leaderboard?group=" + encodeURIComponent(g));
    let data = await res.json();

    let html = "<tr><th>#</th><th>Name</th><th>Attend</th><th>Δ</th><th>C</th><th>L</th></tr>";

    let i = 1;
    for (let r of data.leaderboard){
        let cls = (i === 1) ? "gold" : "";
        html += "<tr>";
        html += "<td class='rank " + cls + "'>" + i + "</td>";
        html += "<td>" + r.name + "</td>";
        html += "<td>" + r.attendance + "</td>";
        html += "<td>" + r.snapshot + "</td>";
        html += "<td>" + r.current_score + "</td>";
        html += "<td>" + r.lifetime_score + "</td>";
        html += "</tr>";
        i++;
    }

    document.getElementById("table").innerHTML = html;
}
</script>

</body>
</html>
"""


@app.get("/display", response_class=HTMLResponse)
def display_page(group: str = "ABC Class"):
    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>TSHRT Display Board</title>
<style>
body {{ background:#000; color:#fff; font-family:Arial; padding:24px; }}
h1 {{ color:#fbbf24; text-align:center; margin-bottom:24px; }}
#grid {{ display:grid; grid-template-columns:repeat(2, 1fr); gap:18px; max-width:1200px; margin:0 auto; }}
.card {{ background:#111827; border:2px solid #334155; border-radius:14px; padding:18px; }}
.name {{ font-size:28px; font-weight:bold; margin-bottom:10px; }}
.score {{ font-size:22px; }}
.small {{ color:#cbd5e1; font-size:16px; }}
</style>
</head>
<body>
<h1>TSHRT Display Board — {group}</h1>
<div id="grid"></div>

<script>
async function loadDisplay(){{
    let res = await fetch("/leaderboard?group=" + encodeURIComponent("{group}"));
    let data = await res.json();

    let html = "";
    let rank = 1;

    for (let r of data.leaderboard.slice(0, 10)){{
        html += `
        <div class="card">
            <div class="name">#${{rank}} ${{r.name}}</div>
            <div class="score">C: ${{r.current_score}} | L: ${{r.lifetime_score}}</div>
            <div class="small">Attendance: ${{r.attendance}} | Δ: ${{r.snapshot}}</div>
        </div>`;
        rank++;
    }}

    document.getElementById("grid").innerHTML = html;
}}

loadDisplay();
setInterval(loadDisplay, 30000);
</script>
</body>
</html>
"""


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
.controls { margin-bottom:16px; line-height: 2.0; }
table { border-collapse:collapse; }
td, th { border:1px solid #334155; padding:8px; text-align:center; }
.name { text-align:left; background:#1f2937; min-width:220px; position:sticky; left:0; z-index:2; }
th { background:#1e293b; font-size:12px; min-width:110px; vertical-align:bottom; }
.cell { width:40px; height:40px; cursor:pointer; background:#0b1836; }
.active { background:#22c55e; }
.finalized-col { box-shadow: inset 0 0 0 2px #d4af37; }
.locked { background:#475569; cursor:not-allowed; }
.wrap { overflow-x:auto; }
button { margin-right:6px; }
.small { font-size:12px; color:#cbd5e1; margin-top:10px; }
.legend { margin-top:10px; font-size:12px; color:#cbd5e1; }
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

Start: <input type="date" id="start" value="2026-03-09">
End: <input type="date" id="end" value="2026-04-20">

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
<button onclick="finalizeDate()">Finalize</button>
<button onclick="unfinalizeDate()">Unfinalize</button>
<button onclick="wakeServer()">Wake</button>
</div>

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

function getSelectedDays() {
    return Array.from(document.querySelectorAll(".daybox:checked"))
        .map(c => parseInt(c.value));
}

function buildDates() {
    let s = new Date(document.getElementById("start").value + "T12:00:00");
    let e = new Date(document.getElementById("end").value + "T12:00:00");
    let days = getSelectedDays();
    let arr = [];

    while (s <= e) {
        if (days.includes(s.getDay())) {
            let y = s.getFullYear();
            let m = String(s.getMonth() + 1).padStart(2, "0");
            let d = String(s.getDate()).padStart(2, "0");
            arr.push(`${y}-${m}-${d}`);
        }
        s.setDate(s.getDate() + 1);
    }
    return arr;
}

function formatHeaderDate(dateStr) {
    const dt = new Date(dateStr + "T12:00:00");
    const weekdays = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
    const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    const dayName = weekdays[dt.getDay()];
    const dayNum = dt.getDate();
    const monthName = months[dt.getMonth()];
    const yearShort = String(dt.getFullYear()).slice(-2);
    return `${dayName}, ${dayNum} ${monthName} ${yearShort}`;
}

function safeDisplayName(c) {
    if ((c.last_name || "").trim() || (c.first_name || "").trim()) {
        return `${c.last_name || ""}, ${c.first_name || ""}`.replace(/^,\\s*/, "").trim();
    }
    return c.display_name || "Unknown";
}

async function loadBoard() {
    try {
        let g = document.getElementById("group").value;

        let clientsRes = await fetch("/attendance/data?group=" + encodeURIComponent(g));
        let clientsData = await clientsRes.json();

        let attRes = await fetch("/attendance/load?group=" + encodeURIComponent(g));
        let attData = await attRes.json();

        if (!clientsRes.ok || clientsData.ok === false) {
            throw new Error("Client load failed");
        }
        if (!attRes.ok || attData.ok === false) {
            throw new Error("Attendance load failed");
        }

        state.clients = clientsData.clients || [];
        state.selected = attData.selected || {};
        state.finalizedDates = new Set(attData.finalized_dates || []);
        state.dates = buildDates();

        render();
    } catch (err) {
        console.error("LOAD ERROR:", err);
        alert("Load failed. Press F12 and check Console.");
    }
}

function render() {
    let html = "<tr><th class='name'>Name</th>";

    for (let d of state.dates) {
        let cls = state.finalizedDates.has(d) ? "finalized-col" : "";
        html += "<th class='" + cls + "'>" + formatHeaderDate(d) + "</th>";
    }
    html += "</tr>";

    for (let c of state.clients) {
        html += "<tr><td class='name'>" + safeDisplayName(c) + "</td>";

        for (let d of state.dates) {
            let key = c.client_id + "|" + d;
            let classes = state.selected[key] ? "cell active" : "cell";
            let locked = state.finalizedDates.has(d);

            if (locked) classes += " locked finalized-col";

            if (locked) {
                html += "<td class='" + classes + "'></td>";
            } else {
                html += "<td class='" + classes + "' onclick=\\"toggleCell('" + c.client_id + "','" + d + "')\\"></td>";
            }
        }

        html += "</tr>";
    }

    document.getElementById("grid").innerHTML = html;
}

function toggleCell(clientId, dateStr) {
    if (state.finalizedDates.has(dateStr)) return;

    let key = clientId + "|" + dateStr;
    if (state.selected[key]) {
        delete state.selected[key];
    } else {
        state.selected[key] = true;
    }
    render();
}

async function saveBoard() {
    try {
        let groupName = document.getElementById("group").value;
        let selectedRecords = [];

        for (let key in state.selected) {
            let parts = key.split("|");
            if (parts.length !== 2) continue;

            selectedRecords.push({
                client_id: parts[0],
                attended_date: parts[1]
            });
        }

        let res = await fetch("/attendance/save", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                group: groupName,
                selected_records: selectedRecords
            })
        });

        let data = await res.json();
        if (!res.ok || data.ok === false) {
            throw new Error("Save failed");
        }

        alert("Saved " + data.saved_count + " attendance records.");
        await loadBoard();
    } catch (err) {
        console.error("SAVE ERROR:", err);
        alert("Save failed. Press F12 and check Console.");
    }
}

async function finalizeDate() {
    let d = prompt("Enter date to finalize (YYYY-MM-DD)");
    if (!d) return;

    try {
        await saveBoard();

        let res = await fetch("/attendance/finalize", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ date: d })
        });

        let data = await res.json();
        if (!res.ok || data.ok === false) {
            throw new Error("Finalize failed");
        }

        alert("Finalized " + d);
        await loadBoard();
    } catch (err) {
        console.error("FINALIZE ERROR:", err);
        alert("Finalize failed.");
    }
}

async function unfinalizeDate() {
    let d = prompt("Enter date to unfinalize (YYYY-MM-DD)");
    if (!d) return;

    try {
        let res = await fetch("/attendance/unfinalize", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ date: d })
        });

        let data = await res.json();
        if (!res.ok || data.ok === false) {
            throw new Error("Unfinalize failed");
        }

        alert("Unfinalized " + d);
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
</script>

</body>
</html>
"""


# =========================================================
# STARTUP
# =========================================================

init_db()
upgrade_db()
