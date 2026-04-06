from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List
import sqlite3

app = FastAPI()
DB_PATH = "cloud.db"

# ----------------------
# CONNECTION FIRST
# ----------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------------
# THEN INIT DB
# ----------------------

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
        UNIQUE(client_id, attended_date)
    )
    """)

    conn.commit()
    conn.close()

# ----------------------
# THEN CALL IT
# ----------------------

init_db()

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
# ----------------------
# MODELS
# ----------------------

class Client(BaseModel):
    client_id: str
    display_name: str
    first_name: str = ""
    last_name: str = ""
    group_name: str = ""
    snapshot_score: int = 0
    baseline_score: int = 0
    in_challenge: int = 1

# ----------------------
# ROUTES
# ----------------------

@app.get("/debug")
def debug():
    return {"status": "server running"}

# ----------------------
# SYNC (OPTION 17)
# ----------------------

@app.post("/sync")
def sync_clients(clients: List[Client]):
    conn = get_conn()
    cur = conn.cursor()

    for c in clients:
        cur.execute("""
        INSERT INTO clients (client_id, display_name, first_name, last_name, group_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            display_name=excluded.display_name,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            group_name=excluded.group_name
        """, (
            c.client_id,
            c.display_name,
            c.first_name,
            c.last_name,
            c.group_name
        ))

    conn.commit()
    conn.close()

    return {"status": "clients synced", "count": len(clients)}

# ----------------------
# LOAD DATA
# ----------------------

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
<html>
<head>
<style>
body { background:#0f172a; color:white; font-family:sans-serif; }
table { border-collapse: collapse; }
td, th { border:1px solid #333; padding:6px; text-align:center; }
.cell { cursor:pointer; }
.green { background:#16a34a; }
</style>
</head>

<body>

<h2>Attendance Board</h2>

<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>

<button onclick="load()">Load</button>
<button onclick="save()">Save</button>

<br><br>

<table id="grid"></table>

<script>

let state = {
    clients: [],
    dates: [],
    selected: {}
};

function buildDates() {
    let start = new Date("2026-03-09");
    let dates = [];

    for (let i = 0; i < 42; i++) {
        let d = new Date(start);
        d.setDate(start.getDate() + i);

        let day = d.getDay();
        if (day === 1 || day === 3) { // Mon / Wed
            dates.push(d.toISOString().slice(0,10));
        }
    }

    return dates;
}

async function load() {
    let group = document.getElementById("group").value;

    let res = await fetch("/attendance/data?group=" + group);
    let data = await res.json();

    state.clients = data.clients;
    state.dates = buildDates();

    render();
}

function render() {
    let html = "<tr><th>Name</th>";

    for (let d of state.dates) {
        html += "<th>" + d.slice(5) + "</th>";
    }

    html += "</tr>";

    state.clients.sort((a,b)=>a.display_name.localeCompare(b.display_name));

    state.clients.forEach((c, i) => {
        html += "<tr><td>" + c.display_name + "</td>";

        state.dates.forEach((d, j) => {
            let key = c.client_id + "_" + d;
            let active = state.selected[key] ? "green" : "";

            html += "<td class='cell " + active + "' onclick=\\"toggle('" + c.client_id + "','" + d + "')\\"></td>";
        });

        html += "</tr>";
    });

    document.getElementById("grid").innerHTML = html;
}

function toggle(id, date) {
    let key = id + "_" + date;

    if (state.selected[key]) {
        delete state.selected[key];
    } else {
        state.selected[key] = true;
    }

    render();
}

async function save() {
    let payload = {};

    for (let key in state.selected) {
        let parts = key.split("_");
        let id = parts[0];
        let date = parts.slice(1).join("_");

        if (!payload[id]) payload[id] = [];
        payload[id].push(date);
    }

    await fetch("/attendance/save", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({selected: payload})
    });

    alert("Saved!");
}

</script>

</body>
</html>
"""

# ----------------------
# SAVE
# ----------------------

@app.get("/attendance/data")
def attendance_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM clients WHERE group_name=?", (group,))
    clients = cur.fetchall()

    result = []
    for c in clients:
        result.append({
            "client_id": c["client_id"],
            "display_name": c["display_name"],
            "group_name": c["group_name"]
        })

    conn.close()

    return {
        "clients": result,
        "attendance": {}
    }

@app.post("/attendance/save")
def save_attendance(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    saved = 0

    for client_id, dates in data.get("selected", {}).items():
        for d in dates:
            try:
                cur.execute("""
                INSERT INTO attendance (client_id, attended_date)
                VALUES (?, ?)
                """, (client_id, d))
                saved += 1
            except:
                pass

    conn.commit()
    conn.close()

    return {"saved": saved}

# ----------------------
# UI (OPTION 8)
# ----------------------

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
<html>
<body style="background:#0f172a;color:white;font-family:sans-serif;">

<h2>TSHRT Attendance</h2>

<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>

<button onclick="load()">Load</button>
<button onclick="save()">Save</button>

<div id="board"></div>

<script>

let state = {clients:[], attendance:{}};

async function load() {
    let group = document.getElementById("group").value;

    let res = await fetch("/attendance/data?group=" + group);
    let data = await res.json();

    state.clients = data.clients;
    render();
}

function render() {
    let html = "";

    for (let c of state.clients) {
        html += "<div>" + c.display_name + " ";
        html += "<button onclick=\\"check('" + c.client_id + "')\\">Check</button></div>";
    }

    document.getElementById("board").innerHTML = html;
}

function check(id) {
    if (!state.attendance[id]) state.attendance[id] = [];
    state.attendance[id].push("2026-04-04");
    alert("checked");
}

async function save() {
    let res = await fetch("/attendance/save", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({selected: state.attendance})
    });

    let data = await res.json();
    alert("Saved " + data.saved);
}

</script>

</body>
</html>
"""
